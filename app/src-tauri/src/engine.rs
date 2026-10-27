//! Cycle de vie du moteur Python, lancé comme processus enfant.
//!
//! Poignée de main : l'app écrit un jeton neuf sur l'entrée standard du moteur et la
//! garde ouverte ; le moteur répond `OJARVIS_READY {"port": ...}` sur sa sortie
//! standard. Fermer l'entrée standard arrête le moteur proprement : si l'app meurt,
//! le moteur s'arrête aussi.

use std::future::Future;
use std::path::{Path, PathBuf};
use std::pin::Pin;
use std::process::Stdio;
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, AtomicU32, AtomicU64, Ordering};
use std::time::{Duration, Instant};

use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Emitter, Manager};
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader, Lines};
use tokio::process::{ChildStdin, ChildStdout, Command};
use tokio::sync::{Mutex, oneshot, watch};

const READY_PREFIX: &str = "OJARVIS_READY ";
const READY_TIMEOUT: Duration = Duration::from_secs(90);
const GRACEFUL_STOP: Duration = Duration::from_secs(7);
const MAX_RESTARTS: u32 = 3;
/// Sortie du moteur quand un autre tient déjà le dossier de données
/// (`ojarvis.shell.connection.EXIT_LOCKED`) : un terminal `ojarvis-shell` lancé avant l'app.
const EXIT_LOCKED: i32 = 3;
pub const STATUS_EVENT: &str = "engine://status";

#[derive(Clone, Debug, Serialize, PartialEq)]
#[serde(rename_all = "lowercase")]
pub enum EngineStatus {
    Starting,
    Ready,
    Failed,
}

/// Ce que l'interface reçoit : l'adresse et le jeton du moteur, ou l'erreur.
#[derive(Clone, Debug, Serialize, PartialEq)]
pub struct EngineInfo {
    pub status: EngineStatus,
    pub base_url: Option<String>,
    pub token: Option<String>,
    pub error: Option<String>,
    pub perf_probe: bool,
}

impl EngineInfo {
    fn starting(perf_probe: bool) -> Self {
        Self {
            status: EngineStatus::Starting,
            base_url: None,
            token: None,
            error: None,
            perf_probe,
        }
    }

    fn ready(port: u16, token: String, perf_probe: bool) -> Self {
        Self {
            status: EngineStatus::Ready,
            base_url: Some(format!("http://127.0.0.1:{port}")),
            token: Some(token),
            error: None,
            perf_probe,
        }
    }
}

type StdoutLines = Lines<BufReader<ChildStdout>>;

/// Lit la sortie du moteur jusqu'à sa poignée de main ; `None` s'il s'arrête avant.
async fn wait_ready(lines: &mut StdoutLines) -> Option<u16> {
    while let Ok(Some(line)) = lines.next_line().await {
        if let Some(port) = parse_ready(&line) {
            return Some(port);
        }
    }
    None
}

/// Vide la sortie du moteur : un tuyau plein le bloquerait.
async fn drain(mut lines: StdoutLines) {
    while let Ok(Some(_)) = lines.next_line().await {}
}

#[derive(Deserialize)]
struct ReadyLine {
    port: u16,
}

/// Commande qui lance le moteur.
#[derive(Debug, Clone, PartialEq)]
pub struct EngineCommand {
    pub program: PathBuf,
    pub args: Vec<String>,
    pub cwd: Option<PathBuf>,
    /// Variables d'environnement données en plus au moteur.
    pub env: Vec<(String, String)>,
}

/// Ordre de recherche : moteur empaqueté, dossier imposé, puis sources du dépôt.
pub fn resolve_command(
    resource_dir: Option<&Path>,
    engine_dir_env: Option<&str>,
    dev: bool,
) -> Result<EngineCommand, String> {
    let mut args = Vec::new();
    if dev {
        args.push("--dev".to_string());
    }
    if let Some(resources) = resource_dir {
        let bundled = resources.join("engine").join("ojarvis-engine");
        if bundled.is_file() {
            return Ok(EngineCommand {
                program: bundled,
                args,
                cwd: None,
                env: Vec::new(),
            });
        }
    }
    let source_dir = match engine_dir_env {
        Some(dir) if !dir.is_empty() => PathBuf::from(dir),
        _ => PathBuf::from(concat!(env!("CARGO_MANIFEST_DIR"), "/../../engine")),
    };
    let python = source_dir.join(".venv").join("bin").join("python");
    if python.is_file() {
        let mut full = vec!["-m".to_string(), "ojarvis".to_string()];
        full.extend(args);
        // Depuis les sources (développement, lanceur « un clic ») : le `.env` du dépôt, que le
        // moteur ne lirait sinon qu'en mode développement. Une variable déjà posée gagne.
        let mut env = Vec::new();
        let dotenv = source_dir.join("..").join(".env");
        if std::env::var_os("OJARVIS_DOTENV").is_none() && dotenv.is_file() {
            env.push(("OJARVIS_DOTENV".to_string(), dotenv.display().to_string()));
        }
        return Ok(EngineCommand {
            program: python,
            args: full,
            cwd: Some(source_dir),
            env,
        });
    }
    Err(format!(
        "moteur introuvable : ni moteur empaqueté, ni environnement Python dans {} (lance scripts/install-dev.sh)",
        source_dir.display()
    ))
}

/// Jeton de session : 32 octets aléatoires, en hexadécimal.
pub fn new_token() -> Result<String, String> {
    let mut bytes = [0u8; 32];
    getrandom::fill(&mut bytes).map_err(|e| format!("aléa indisponible : {e}"))?;
    Ok(bytes.iter().map(|b| format!("{b:02x}")).collect())
}

pub fn parse_ready(line: &str) -> Option<u16> {
    let json = line.strip_prefix(READY_PREFIX)?;
    serde_json::from_str::<ReadyLine>(json).ok().map(|r| r.port)
}

struct Running {
    stdin: Option<ChildStdin>,
    kill: Option<oneshot::Sender<()>>,
    exited: watch::Receiver<bool>,
    pid: Option<u32>,
}

pub struct EngineManager {
    info: watch::Sender<EngineInfo>,
    running: Mutex<Option<Running>>,
    quitting: AtomicBool,
    restarts: AtomicU32,
    /// Numéro du lancement en cours : un ancien moteur qui s'arrête ne relance rien.
    generation: AtomicU64,
    perf_probe: bool,
}

impl EngineManager {
    pub fn new(perf_probe: bool) -> Arc<Self> {
        let (info, _) = watch::channel(EngineInfo::starting(perf_probe));
        Arc::new(Self {
            info,
            running: Mutex::new(None),
            quitting: AtomicBool::new(false),
            restarts: AtomicU32::new(0),
            generation: AtomicU64::new(0),
            perf_probe,
        })
    }

    fn publish(&self, app: &AppHandle, info: EngineInfo) {
        self.info.send_replace(info.clone());
        if let Err(error) = app.emit(STATUS_EVENT, info) {
            log::warn!("émission de l'état du moteur impossible : {error}");
        }
    }

    /// Attend que le moteur soit prêt (ou en échec) et renvoie son état.
    pub async fn wait_info(&self) -> EngineInfo {
        let mut rx = self.info.subscribe();
        let deadline = Instant::now() + READY_TIMEOUT;
        loop {
            let current = rx.borrow().clone();
            if current.status != EngineStatus::Starting {
                return current;
            }
            let remaining = deadline.saturating_duration_since(Instant::now());
            if remaining.is_zero() || tokio::time::timeout(remaining, rx.changed()).await.is_err() {
                return rx.borrow().clone();
            }
        }
    }

    /// Démarre le moteur. Le futur est typé explicitement (`Send`) : le redémarrage
    /// automatique rappelle `start` depuis la tâche de surveillance, et sans ce type
    /// le compilateur ne peut pas prouver que ce cycle passe d'un thread à l'autre.
    pub fn start(self: &Arc<Self>, app: AppHandle) -> Pin<Box<dyn Future<Output = ()> + Send>> {
        let this = Arc::clone(self);
        Box::pin(async move { this.start_once(app).await })
    }

    async fn start_once(self: Arc<Self>, app: AppHandle) {
        self.publish(&app, EngineInfo::starting(self.perf_probe));
        match self.spawn(&app).await {
            Ok(port_token) => {
                let (port, token) = port_token;
                log::info!("moteur prêt sur 127.0.0.1:{port}");
                self.publish(&app, EngineInfo::ready(port, token, self.perf_probe));
            }
            Err(error) => {
                log::error!("le moteur n'a pas démarré : {error}");
                self.publish(
                    &app,
                    EngineInfo {
                        status: EngineStatus::Failed,
                        base_url: None,
                        token: None,
                        error: Some(error),
                        perf_probe: self.perf_probe,
                    },
                );
            }
        }
    }

    async fn spawn(self: &Arc<Self>, app: &AppHandle) -> Result<(u16, String), String> {
        let resource_dir = app.path().resource_dir().ok();
        let engine_dir = std::env::var("OJARVIS_ENGINE_DIR").ok();
        let dev = cfg!(debug_assertions) || std::env::var("OJARVIS_DEV").is_ok_and(|v| v == "1");
        let command = resolve_command(resource_dir.as_deref(), engine_dir.as_deref(), dev)?;
        let token = new_token()?;

        let mut cmd = Command::new(&command.program);
        cmd.args(&command.args)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .env_remove("OJARVIS_TOKEN")
            .kill_on_drop(true);
        for (key, value) in &command.env {
            cmd.env(key, value);
        }
        if let Some(cwd) = &command.cwd {
            cmd.current_dir(cwd);
        }
        let mut child = cmd
            .spawn()
            .map_err(|e| format!("lancement impossible : {e}"))?;
        let generation = self.generation.fetch_add(1, Ordering::SeqCst) + 1;
        let pid = child.id();
        let mut stdin = child.stdin.take().ok_or("entrée standard indisponible")?;
        let stdout = child.stdout.take().ok_or("sortie standard indisponible")?;
        let stderr = child.stderr.take().ok_or("sortie d'erreur indisponible")?;

        stdin
            .write_all(format!("{token}\n").as_bytes())
            .await
            .map_err(|e| format!("envoi du jeton impossible : {e}"))?;
        stdin
            .flush()
            .await
            .map_err(|e| format!("envoi du jeton impossible : {e}"))?;

        tokio::spawn(async move {
            let mut lines = BufReader::new(stderr).lines();
            while let Ok(Some(line)) = lines.next_line().await {
                log::info!(target: "engine", "{line}");
            }
        });

        let (kill_tx, kill_rx) = oneshot::channel::<()>();
        let (exited_tx, exited_rx) = watch::channel(false);
        let manager = Arc::clone(self);
        let app_for_exit = app.clone();
        tokio::spawn(async move {
            let status = tokio::select! {
                status = child.wait() => status.ok(),
                _ = kill_rx => {
                    let _ = child.start_kill();
                    child.wait().await.ok()
                }
            };
            let _ = exited_tx.send(true);
            manager
                .on_exit(app_for_exit, generation, status.and_then(|s| s.code()))
                .await;
        });

        *self.running.lock().await = Some(Running {
            stdin: Some(stdin),
            kill: Some(kill_tx),
            exited: exited_rx,
            pid,
        });

        let mut lines = BufReader::new(stdout).lines();
        match tokio::time::timeout(READY_TIMEOUT, wait_ready(&mut lines)).await {
            Ok(Some(port)) => {
                tokio::spawn(drain(lines));
                Ok((port, token))
            }
            Ok(None) => {
                Err("le moteur s'est arrêté pendant son démarrage (voir les logs)".to_string())
            }
            Err(_) => {
                // Démarrage lent (trousseau à déverrouiller, machine chargée) : l'app le
                // signale, mais garde l'oreille tendue et se connecte dès que le moteur est prêt.
                let manager = Arc::clone(self);
                let app = app.clone();
                tokio::spawn(async move {
                    let Some(port) = wait_ready(&mut lines).await else {
                        return;
                    };
                    if manager.generation.load(Ordering::SeqCst) == generation {
                        log::info!("moteur prêt (en retard) sur 127.0.0.1:{port}");
                        manager.publish(&app, EngineInfo::ready(port, token, manager.perf_probe));
                    }
                    drain(lines).await;
                });
                Err(
                    "il tarde à répondre (trousseau à déverrouiller ?) ; l'app s'y connectera dès \
                     qu'il sera prêt"
                        .to_string(),
                )
            }
        }
    }

    async fn on_exit(self: Arc<Self>, app: AppHandle, generation: u64, code: Option<i32>) {
        if generation != self.generation.load(Ordering::SeqCst) {
            return;
        }
        self.running.lock().await.take();
        if self.quitting.load(Ordering::SeqCst) {
            return;
        }
        log::warn!("le moteur s'est arrêté (code {code:?})");
        if code == Some(EXIT_LOCKED) {
            // Pas une panne : relancer ne servirait à rien tant que ce terminal est ouvert.
            self.publish(
                &app,
                EngineInfo {
                    status: EngineStatus::Failed,
                    base_url: None,
                    token: None,
                    error: Some(
                        "Jarvis tourne déjà dans un terminal (ojarvis-shell) : ferme-le, puis \
                         rouvre l'app"
                            .to_string(),
                    ),
                    perf_probe: self.perf_probe,
                },
            );
            return;
        }
        let attempt = self.restarts.fetch_add(1, Ordering::SeqCst) + 1;
        if attempt > MAX_RESTARTS {
            self.publish(
                &app,
                EngineInfo {
                    status: EngineStatus::Failed,
                    base_url: None,
                    token: None,
                    error: Some(format!(
                        "le moteur s'est arrêté (code {code:?}) et ne redémarre plus"
                    )),
                    perf_probe: self.perf_probe,
                },
            );
            return;
        }
        tokio::time::sleep(Duration::from_millis(500 * u64::from(attempt))).await;
        self.start(app).await;
    }

    /// Arrêt propre : fermer l'entrée standard, attendre, puis tuer si besoin.
    pub async fn stop(&self) {
        self.quitting.store(true, Ordering::SeqCst);
        let Some(mut running) = self.running.lock().await.take() else {
            return;
        };
        drop(running.stdin.take());
        let graceful = tokio::time::timeout(GRACEFUL_STOP, async {
            while !*running.exited.borrow() {
                if running.exited.changed().await.is_err() {
                    break;
                }
            }
        })
        .await;
        if graceful.is_err() {
            log::warn!("le moteur ne s'arrête pas : arrêt forcé");
            if let Some(kill) = running.kill.take() {
                let _ = kill.send(());
            } else if let Some(pid) = running.pid {
                // Dernier recours si la tâche de surveillance a disparu.
                unsafe {
                    libc::kill(pid as libc::pid_t, libc::SIGKILL);
                }
            }
        }
    }

    pub async fn restart(self: &Arc<Self>, app: AppHandle) {
        self.stop().await;
        self.quitting.store(false, Ordering::SeqCst);
        self.restarts.store(0, Ordering::SeqCst);
        self.start(app).await;
    }
}

#[cfg(test)]
mod tests {
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
        assert_eq!(wait_ready(&mut lines).await, Some(4321));
        drain(lines).await;
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
}
