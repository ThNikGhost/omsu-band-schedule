//! Shared plugin state and settings persistence.
//!
//! WASI gives the plugin exactly one writable directory - its own - so the
//! config is a plain file there. Saving writes a temp file and renames it;
//! if the host filesystem has no atomic rename, it falls back to a direct
//! write rather than losing the settings.

use std::fs;
use std::sync::{Mutex, OnceLock};

use omsu_sync_core::settings::{Settings, CONFIG_FILE};

const MAX_LOG_LINES: usize = 40;

pub struct AppState {
    pub settings: Settings,
    /// Id of the UI root element, needed to redraw after every change.
    pub root: Option<String>,
    pub device_addr: String,
    pub device_name: String,
    pub status: String,
    pub busy: bool,
    pub log: Vec<String>,
    /// Frames of the current transfer, and how far it has got.
    pub pending: Option<Transfer>,
}

pub struct Transfer {
    pub frames: Vec<String>,
    pub sent: usize,
    pub acked: usize,
    pub hash: String,
}

static STATE: OnceLock<Mutex<AppState>> = OnceLock::new();

pub fn state() -> &'static Mutex<AppState> {
    STATE.get_or_init(|| {
        Mutex::new(AppState {
            settings: load_settings(),
            root: None,
            device_addr: String::new(),
            device_name: String::new(),
            status: "Готов к работе".to_string(),
            busy: false,
            log: Vec::new(),
            pending: None,
        })
    })
}

/// A poisoned lock still holds usable data; a panic in one handler must not
/// brick the settings screen.
pub fn with_state<R>(f: impl FnOnce(&mut AppState) -> R) -> R {
    let mut guard = state()
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner());
    f(&mut guard)
}

pub fn log_line(text: impl Into<String>) {
    let line = text.into();
    tracing::info!("{}", line);
    with_state(|s| {
        s.log.push(line);
        if s.log.len() > MAX_LOG_LINES {
            let overflow = s.log.len() - MAX_LOG_LINES;
            s.log.drain(0..overflow);
        }
    });
}

pub fn set_status(text: impl Into<String>) {
    let text = text.into();
    with_state(|s| s.status = text);
}

pub fn load_settings() -> Settings {
    match fs::read_to_string(CONFIG_FILE) {
        Ok(text) => match Settings::from_json(&text) {
            Ok(settings) => settings,
            Err(err) => {
                tracing::warn!("не удалось разобрать настройки, беру значения по умолчанию: {err}");
                Settings::default()
            }
        },
        Err(_) => Settings::default(),
    }
}

pub fn save_settings(settings: &Settings) -> Result<(), String> {
    let body = settings.to_json();
    let tmp = format!("{CONFIG_FILE}.tmp");

    if fs::write(&tmp, &body).is_ok() && fs::rename(&tmp, CONFIG_FILE).is_ok() {
        return Ok(());
    }
    let _ = fs::remove_file(&tmp);

    // Not every WASI filesystem implements rename; a direct write is still
    // better than dropping the user's settings on the floor.
    fs::write(CONFIG_FILE, &body).map_err(|e| format!("не удалось сохранить настройки: {e}"))
}
