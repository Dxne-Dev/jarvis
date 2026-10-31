//! Tests du cycle de vie du moteur (`engine.rs`), à part pour garder ce fichier court.

use super::*;

#[test]
fn token_is_64_hex_chars_and_unique() {
    let a = new_token().unwrap();
    let b = new_token().unwrap();
    assert_eq!(a.len(), 64);
    assert!(a.chars().all(|c| c.is_ascii_hexdigit()));
    assert_ne!(a, b);
}

#[test]
fn ready_line_is_parsed() {
    assert_eq!(
        parse_ready(r#"OJARVIS_READY {"port": 4242, "pid": 1, "version": "0.1.0"}"#),
        Some(4242)
    );
    assert_eq!(parse_ready("autre chose"), None);
    assert_eq!(parse_ready("OJARVIS_READY {pas du json}"), None);
}

#[test]
fn command_prefers_bundled_engine() {
    let dir = std::env::temp_dir().join(format!("ojarvis-test-{}", std::process::id()));
    let bundled = dir.join("engine");
    std::fs::create_dir_all(&bundled).unwrap();
    std::fs::write(bundled.join("ojarvis-engine"), b"").unwrap();
    let cmd = resolve_command(Some(&dir), None, false).unwrap();
    assert_eq!(cmd.program, bundled.join("ojarvis-engine"));
    assert!(cmd.args.is_empty());
    std::fs::remove_dir_all(&dir).unwrap();
}

#[test]
fn command_uses_engine_dir_venv() {
    let dir = std::env::temp_dir().join(format!("ojarvis-src-{}", std::process::id()));
    let bin = dir.join(".venv").join("bin");
    std::fs::create_dir_all(&bin).unwrap();
    std::fs::write(bin.join("python"), b"").unwrap();
    let cmd = resolve_command(None, dir.to_str(), true).unwrap();
    assert_eq!(cmd.program, bin.join("python"));
    assert_eq!(cmd.args, vec!["-m", "ojarvis", "--dev"]);
    assert_eq!(cmd.cwd.as_deref(), Some(dir.as_path()));
    std::fs::remove_dir_all(&dir).unwrap();
}

#[test]
fn engine_from_sources_reads_the_repository_dotenv() {
    let root = std::env::temp_dir().join(format!("ojarvis-depot-{}", std::process::id()));
    let engine = root.join("engine");
    let bin = engine.join(".venv").join("bin");
    std::fs::create_dir_all(&bin).unwrap();
    std::fs::write(bin.join("python"), b"").unwrap();
    let without = resolve_command(None, engine.to_str(), false).unwrap();
    assert!(without.env.is_empty());
    std::fs::write(root.join(".env"), b"GROQ_API_KEY=\n").unwrap();
    let with = resolve_command(None, engine.to_str(), false).unwrap();
    if std::env::var_os("OJARVIS_DOTENV").is_none() {
        let (key, value) = &with.env[0];
        assert_eq!(key, "OJARVIS_DOTENV");
        assert!(std::path::Path::new(value).is_file());
    }
    std::fs::remove_dir_all(&root).unwrap();
}

#[test]
fn missing_engine_is_a_clear_error() {
    let error = resolve_command(None, Some("/chemin/inexistant"), false).unwrap_err();
    assert!(error.contains("moteur introuvable"));
}

#[tokio::test]
async fn late_handshake_is_still_read_after_a_timeout() {
    let mut child = Command::new("sh")
        .args([
            "-c",
            "echo démarrage; sleep 0.3; echo 'OJARVIS_READY {\"port\": 4321}'; echo suite",
        ])
        .stdout(Stdio::piped())
        .spawn()
        .unwrap();
    let mut lines = BufReader::new(child.stdout.take().unwrap()).lines();
    // Le délai expire d'abord…
    let early = tokio::time::timeout(Duration::from_millis(50), wait_ready(&mut lines)).await;
    assert!(early.is_err());
    // …puis la poignée de main arrive : rien n'a été perdu entre-temps.
    assert_eq!(wait_ready(&mut lines).await, Some(Handshake::Ready(4321)));
    drain(lines).await;
    child.wait().await.unwrap();
}

#[tokio::test]
async fn an_engine_already_running_is_joined() {
    let mut child = Command::new("sh")
        .args([
            "-c",
            r#"echo 'OJARVIS_RUNNING {"port": 4242, "pid": 77, "token": "abc"}'; exit 3"#,
        ])
        .stdout(Stdio::piped())
        .spawn()
        .unwrap();
    let mut lines = BufReader::new(child.stdout.take().unwrap()).lines();
    let expected = join::Running {
        port: 4242,
        pid: 77,
        token: "abc".to_string(),
    };
    assert_eq!(
        wait_ready(&mut lines).await,
        Some(Handshake::Joined(expected))
    );
    child.wait().await.unwrap();
}

#[tokio::test]
async fn engine_exiting_before_handshake_is_reported() {
    let mut child = Command::new("sh")
        .args(["-c", "echo erreur"])
        .stdout(Stdio::piped())
        .spawn()
        .unwrap();
    let mut lines = BufReader::new(child.stdout.take().unwrap()).lines();
    assert_eq!(wait_ready(&mut lines).await, None);
    child.wait().await.unwrap();
}
