//! Plugin settings.
//!
//! AstroBox v2 has no config API of its own: a plugin just writes a file into
//! its own directory, which is the only place WASI lets it touch. Saving is
//! write-to-temp plus rename, with a plain-write fallback, because not every
//! WASI filesystem implements an atomic rename.

use serde::{Deserialize, Serialize};

pub const CONFIG_FILE: &str = "./omsu-band-schedule.config.json";
pub const CURRENT_VERSION: u32 = 1;

pub const DEFAULT_DAYS: u16 = 14;
pub const MAX_DAYS: u16 = 21;
pub const DEFAULT_PACKAGE: &str = "ru.omsu.bandschedule";

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default)]
pub struct Settings {
    pub version: u32,
    /// Base URL of the schedule server, without a trailing slash.
    pub server_url: String,
    pub token: String,
    pub group_id: u32,
    /// None means "keep every lesson", which is what a student with no
    /// subgroup split wants. 1 or 2 keeps common lessons plus that subgroup.
    pub subgroup: Option<u8>,
    pub days: u16,
    /// Package name of the quick app on the band; this is the QAIC address.
    pub package_name: String,
    /// Bluetooth address of the band, remembered between runs.
    pub device_addr: Option<String>,
    /// Hash of the payload the band last confirmed, used for If-None-Match.
    pub last_hash: Option<String>,
    pub last_sync: Option<String>,
}

impl Default for Settings {
    fn default() -> Self {
        Settings {
            version: CURRENT_VERSION,
            server_url: String::new(),
            token: String::new(),
            group_id: 0,
            subgroup: None,
            days: DEFAULT_DAYS,
            package_name: DEFAULT_PACKAGE.to_string(),
            device_addr: None,
            last_hash: None,
            last_sync: None,
        }
    }
}

impl Settings {
    pub fn from_json(text: &str) -> Result<Self, String> {
        let parsed: Settings = serde_json::from_str(text).map_err(|e| e.to_string())?;
        if parsed.version != CURRENT_VERSION {
            return Err(format!("unsupported settings version {}", parsed.version));
        }
        Ok(parsed)
    }

    pub fn to_json(&self) -> String {
        serde_json::to_string_pretty(self).unwrap_or_else(|_| "{}".to_string())
    }

    /// Everything that stops a sync from working, in the order a user would fix it.
    pub fn problems(&self) -> Vec<String> {
        let mut out = Vec::new();

        let url = self.server_url.trim();
        if url.is_empty() {
            out.push("не указан адрес сервера".to_string());
        } else if !(url.starts_with("http://") || url.starts_with("https://")) {
            out.push("адрес сервера должен начинаться с http:// или https://".to_string());
        }

        if self.token.trim().is_empty() {
            out.push("не указан токен".to_string());
        }
        if self.group_id == 0 {
            out.push("не указан номер группы".to_string());
        }
        if self.days == 0 || self.days > MAX_DAYS {
            out.push(format!("число дней должно быть от 1 до {MAX_DAYS}"));
        }
        if self.package_name.trim().is_empty() {
            out.push("не указан package name приложения на браслете".to_string());
        }
        if let Some(sub) = self.subgroup {
            if sub == 0 || sub > 9 {
                out.push("подгруппа должна быть от 1 до 9".to_string());
            }
        }
        out
    }

    pub fn is_ready(&self) -> bool {
        self.problems().is_empty()
    }

    /// Full URL for the schedule endpoint. The token travels in the header,
    /// never here, so it cannot end up in a log or a crash report.
    pub fn schedule_url(&self) -> String {
        let base = self.server_url.trim().trim_end_matches('/');
        let mut url = format!(
            "{base}/api/v1/schedule?group={}&days={}",
            self.group_id, self.days
        );
        if let Some(sub) = self.subgroup {
            url.push_str(&format!("&subgroup={sub}"));
        }
        url
    }

    pub fn bearer(&self) -> String {
        format!("Bearer {}", self.token.trim())
    }

    /// Accepts "", "нет", "1", "2"... An unparseable value clears the filter
    /// rather than failing: a typo should not silently keep the old subgroup.
    pub fn set_subgroup_from_text(&mut self, text: &str) {
        let trimmed = text.trim();
        self.subgroup = if trimmed.is_empty() {
            None
        } else {
            trimmed.parse::<u8>().ok().filter(|v| (1..=9).contains(v))
        };
    }

    pub fn subgroup_text(&self) -> String {
        self.subgroup.map(|v| v.to_string()).unwrap_or_default()
    }
}

/// Redacts the token so settings can be written to a log.
pub fn describe(settings: &Settings) -> String {
    format!(
        "server={} group={} days={} subgroup={} package={} token={}",
        if settings.server_url.is_empty() {
            "—"
        } else {
            &settings.server_url
        },
        settings.group_id,
        settings.days,
        settings
            .subgroup
            .map(|v| v.to_string())
            .unwrap_or_else(|| "все".to_string()),
        settings.package_name,
        if settings.token.is_empty() { "нет" } else { "***" },
    )
}
