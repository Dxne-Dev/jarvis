//! Raccourci clavier global « Parler à Jarvis », par le portail GlobalShortcuts.
//!
//! Sous Wayland, une application ne peut pas écouter le clavier des autres fenêtres :
//! elle demande un raccourci au portail du bureau. GNOME affiche une fenêtre de
//! confirmation au premier lancement, où l'utilisateur peut aussi changer la touche.

use std::sync::Mutex;

use ashpd::desktop::global_shortcuts::{GlobalShortcuts, NewShortcut};
use futures_util::StreamExt;
use serde::Serialize;
use tauri::{AppHandle, Emitter, Manager};

pub const APP_ID: &str = "io.github.octavebahoun.ojarvis";
const SHORTCUT_ID: &str = "parler";
const PREFERRED_TRIGGER: &str = "CTRL+ALT+J";

/// Ce que l'interface affiche dans Réglages : la touche retenue, ou pourquoi il n'y en a pas.
#[derive(Clone, Debug, Default, Serialize)]
pub struct ShortcutStatus {
    pub state: &'static str,
    pub trigger: Option<String>,
    pub error: Option<String>,
}

#[derive(Default)]
pub struct ShortcutState(pub Mutex<ShortcutStatus>);

fn set_status(app: &AppHandle, status: ShortcutStatus) {
    if let Some(state) = app.try_state::<ShortcutState>()
        && let Ok(mut current) = state.0.lock()
    {
        *current = status.clone();
    }
    let _ = app.emit("shortcut://etat", status);
}

/// Lance l'écoute en tâche de fond ; un échec n'empêche jamais l'app de démarrer.
pub fn spawn(app: AppHandle) {
    tauri::async_runtime::spawn(async move {
        set_status(
            &app,
            ShortcutStatus {
                state: "demande",
                ..ShortcutStatus::default()
            },
        );
        if let Err(error) = listen(&app).await {
            log::warn!("raccourci global indisponible : {error}");
            set_status(
                &app,
                ShortcutStatus {
                    state: "indisponible",
                    trigger: None,
                    error: Some(error.to_string()),
                },
            );
        }
    });
}

async fn listen(app: &AppHandle) -> ashpd::Result<()> {
    // Hors Flatpak, le portail doit savoir quelle application parle (fichier .desktop).
    if let Ok(app_id) = ashpd::AppID::try_from(APP_ID)
        && let Err(error) = ashpd::register_host_app(app_id).await
    {
        log::info!("enregistrement auprès du portail refusé : {error}");
    }
    let portal = GlobalShortcuts::new().await?;
    let session = portal.create_session(Default::default()).await?;
    let shortcut =
        NewShortcut::new(SHORTCUT_ID, "Parler à Jarvis").preferred_trigger(PREFERRED_TRIGGER);
    let bound = portal
        .bind_shortcuts(&session, &[shortcut], None, Default::default())
        .await?
        .response()?;
    let trigger = bound
        .shortcuts()
        .iter()
        .find(|s| s.id() == SHORTCUT_ID)
        .map(|s| s.trigger_description().to_owned())
        .filter(|t| !t.is_empty());
    log::info!("raccourci global prêt : {}", trigger.as_deref().unwrap_or("(à choisir)"));
    set_status(
        app,
        ShortcutStatus {
            state: "pret",
            trigger,
            error: None,
        },
    );
    let mut activations = portal.receive_activated().await?;
    while let Some(event) = activations.next().await {
        if event.shortcut_id() == SHORTCUT_ID {
            let _ = app.emit("shortcut://parler", ());
        }
    }
    // La session doit vivre aussi longtemps que l'écoute, sinon le raccourci disparaît.
    drop(session);
    Ok(())
}

#[tauri::command]
pub fn shortcut_status(state: tauri::State<'_, ShortcutState>) -> ShortcutStatus {
    state.0.lock().map(|s| s.clone()).unwrap_or_default()
}
