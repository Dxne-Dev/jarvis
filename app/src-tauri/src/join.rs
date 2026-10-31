//! Rejoindre le moteur déjà lancé par un terminal (`ojarvis-shell` ouvert avant l'app).
//!
//! Un seul moteur complet tourne sur les mêmes données. Quand le terminal l'a lancé, le
//! moteur que l'app démarre s'arrête aussitôt (le dossier de données est déjà tenu) en
//! donnant la connexion du premier : `OJARVIS_RUNNING {"port": …, "pid": …, "token": …}`.
//! L'app s'y branche ; si ce moteur s'arrête (le terminal se ferme), l'app relance le sien.

use std::path::Path;
use std::time::Duration;

use serde::Deserialize;

pub const RUNNING_PREFIX: &str = "OJARVIS_RUNNING ";
/// Tous les combien l'app vérifie que le moteur rejoint tourne encore.
const WATCH_EVERY: Duration = Duration::from_secs(2);

/// Le moteur déjà lancé : où le joindre, et son jeton de session.
#[derive(Debug, Clone, Deserialize, PartialEq)]
pub struct Running {
    pub port: u16,
    pub pid: u32,
    pub token: String,
}

pub fn parse_running(line: &str) -> Option<Running> {
    let json = line.strip_prefix(RUNNING_PREFIX)?;
    serde_json::from_str::<Running>(json).ok()
}

/// Rend la main quand le processus n'existe plus.
pub async fn wait_gone(pid: u32) {
    let proc = format!("/proc/{pid}");
    while Path::new(&proc).exists() {
        tokio::time::sleep(WATCH_EVERY).await;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn running_line_is_parsed() {
        let line = r#"OJARVIS_RUNNING {"port": 4242, "pid": 77, "token": "abc"}"#;
        assert_eq!(
            parse_running(line),
            Some(Running {
                port: 4242,
                pid: 77,
                token: "abc".to_string(),
            })
        );
        assert_eq!(parse_running(r#"OJARVIS_READY {"port": 4242}"#), None);
        assert_eq!(parse_running("OJARVIS_RUNNING {pas du json}"), None);
    }

    #[tokio::test]
    async fn a_finished_process_is_seen_gone() {
        let mut child = tokio::process::Command::new("true").spawn().unwrap();
        let pid = child.id().unwrap();
        child.wait().await.unwrap();
        tokio::time::timeout(Duration::from_secs(5), wait_gone(pid))
            .await
            .expect("le processus fini doit être vu disparu");
    }
}
