//! Coque de bureau d'O-jarvis : fenêtre, icône dans la barre système, moteur Python.

mod engine;
mod shortcut;

use std::sync::Arc;

use engine::{EngineInfo, EngineManager};
use tauri::menu::{Menu, MenuItem};
use tauri::tray::TrayIconBuilder;
use tauri::{AppHandle, Manager, RunEvent, State};

#[tauri::command]
async fn engine_info(manager: State<'_, Arc<EngineManager>>) -> Result<EngineInfo, String> {
    Ok(manager.wait_info().await)
}

#[tauri::command]
async fn engine_restart(
    app: AppHandle,
    manager: State<'_, Arc<EngineManager>>,
) -> Result<(), String> {
    let manager = Arc::clone(&manager);
    manager.restart(app).await;
    Ok(())
}

/// Une ligne de log venue de la fenêtre : tronquée, sans retour à la ligne ni caractère
/// de contrôle (impossible de forger une fausse ligne de log).
fn sanitize_log_line(message: &str) -> String {
    message
        .chars()
        .take(2000)
        .map(|c| if c.is_control() { ' ' } else { c })
        .collect()
}

/// Journal de l'interface vers les logs du shell (disponible même sans moteur).
#[tauri::command]
fn ui_log(level: &str, message: &str) {
    let text = sanitize_log_line(message);
    match level {
        "error" => log::error!(target: "ui", "{text}"),
        "warn" => log::warn!(target: "ui", "{text}"),
        _ => log::info!(target: "ui", "{text}"),
    }
}

/// Quitter l'app (Ctrl+Q) : arrête aussi le moteur, via l'événement de sortie.
#[tauri::command]
fn app_quit(app: AppHandle) {
    app.exit(0);
}

/// Argument passé par l'entrée de démarrage automatique : on reste dans la barre système.
const AUTOSTART_ARG: &str = "--au-demarrage";

fn show_main_window(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.unminimize();
        let _ = window.show();
        let _ = window.set_focus();
    }
}

fn build_tray(app: &AppHandle) -> tauri::Result<()> {
    let open = MenuItem::with_id(app, "open", "Ouvrir O-jarvis", true, None::<&str>)?;
    let quit = MenuItem::with_id(app, "quit", "Quitter", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&open, &quit])?;
    let mut builder = TrayIconBuilder::with_id("main")
        .tooltip("O-jarvis")
        .menu(&menu)
        .on_menu_event(|app, event| match event.id().as_ref() {
            "open" => show_main_window(app),
            "quit" => app.exit(0),
            _ => {}
        });
    if let Some(icon) = app.default_window_icon() {
        builder = builder.icon(icon.clone());
    }
    builder.build(app)?;
    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let perf_probe = std::env::var("OJARVIS_PERF_PROBE").is_ok_and(|v| v == "1");
    let manager = EngineManager::new(perf_probe);

    let app = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            show_main_window(app);
        }))
        .plugin(tauri_plugin_opener::init())
        // Démarrage à l'ouverture de session (désactivable dans Réglages) : discret, dans la
        // barre système, prêt pour « Hey Jarvis ».
        .plugin(tauri_plugin_autostart::init(
            tauri_plugin_autostart::MacosLauncher::LaunchAgent,
            Some(vec![AUTOSTART_ARG]),
        ))
        .plugin(tauri_plugin_notification::init())
        .plugin(
            tauri_plugin_log::Builder::default()
                .level(log::LevelFilter::Info)
                .max_file_size(5_000_000)
                .build(),
        )
        .manage(Arc::clone(&manager))
        .manage(shortcut::ShortcutState::default())
        .invoke_handler(tauri::generate_handler![
            engine_info,
            engine_restart,
            ui_log,
            app_quit,
            shortcut::shortcut_status
        ])
        .setup(move |app| {
            build_tray(app.handle())?;
            // La fenêtre est créée cachée : visible tout de suite, sauf au démarrage de session.
            if !std::env::args().any(|arg| arg == AUTOSTART_ARG) {
                show_main_window(app.handle());
            }
            shortcut::spawn(app.handle().clone());
            let handle = app.handle().clone();
            let manager = Arc::clone(&manager);
            tauri::async_runtime::spawn(async move {
                manager.start(handle).await;
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("impossible de construire l'application");

    app.run(|app, event| {
        if let RunEvent::Exit = event {
            let manager = Arc::clone(app.state::<Arc<EngineManager>>().inner());
            tauri::async_runtime::block_on(async move {
                manager.stop().await;
            });
        }
    });
}

#[cfg(test)]
mod tests {
    use super::sanitize_log_line;

    #[test]
    fn log_lines_cannot_be_forged() {
        let forged = "ok\n[2026-01-01][00:00:00][engine][INFO] faux\r\u{1b}[31m";
        let clean = sanitize_log_line(forged);
        assert!(!clean.contains('\n'));
        assert!(!clean.contains('\r'));
        assert!(!clean.contains('\u{1b}'));
        assert_eq!(sanitize_log_line(&"é".repeat(5000)).chars().count(), 2000);
    }
}
