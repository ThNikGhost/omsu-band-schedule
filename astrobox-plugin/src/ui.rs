//! Settings screen inside AstroBox.

use astrobox_ng_wit::astrobox::psys_host::{self, ui_v3};

use crate::state::{log_line, save_settings, with_state};
use crate::sync;

pub const EVENT_SERVER: &str = "field_server";
pub const EVENT_TOKEN: &str = "field_token";
pub const EVENT_GROUP: &str = "field_group";
pub const EVENT_SUBGROUP: &str = "field_subgroup";
pub const EVENT_DAYS: &str = "field_days";
pub const EVENT_PACKAGE: &str = "field_package";
pub const EVENT_SYNC: &str = "btn_sync";
pub const EVENT_SAVE: &str = "btn_save";

const CARD_BG: &str = "#1E1E1F";
const FIELD_BG: &str = "#141415";
const BTN_BG: &str = "#2A2A2A";
const ACCENT: &str = "#3A6EA5";
const TEXT: &str = "#E6E6E6";
const MUTED: &str = "#8A8A8A";
const WARN: &str = "#D08A3A";
const RADIUS: u32 = 10;

pub async fn render_main_ui(element_id: &str) {
    with_state(|s| s.root = Some(element_id.to_string()));
    sync::refresh_device().await;
    psys_host::ui_v3::render(element_id, build_ui());
}

pub async fn handle_ui_event(event: ui_v3::Event, event_id: &str, payload: &str) {
    match event {
        ui_v3::Event::Input | ui_v3::Event::Change => {
            let value = extract_value(payload);
            apply_field(event_id, &value);
            // Fields are not redrawn on every keystroke: re-rendering would
            // move the caret and fight the user.
        }
        ui_v3::Event::Click => match event_id {
            EVENT_SAVE => {
                let settings = with_state(|s| s.settings.clone());
                match save_settings(&settings) {
                    Ok(()) => log_line("настройки сохранены"),
                    Err(err) => log_line(err),
                }
                sync::redraw().await;
            }
            EVENT_SYNC => {
                let settings = with_state(|s| s.settings.clone());
                let _ = save_settings(&settings);
                sync::sync_now(true).await;
            }
            _ => {}
        },
        _ => {}
    }
}

/// The host may deliver an input value as a bare string or wrapped in JSON;
/// accept both rather than betting on one.
fn extract_value(payload: &str) -> String {
    let trimmed = payload.trim();
    if trimmed.is_empty() {
        return String::new();
    }
    match serde_json::from_str::<serde_json::Value>(trimmed) {
        Ok(serde_json::Value::String(text)) => text,
        Ok(serde_json::Value::Object(map)) => map
            .get("value")
            .and_then(|v| v.as_str().map(|s| s.to_string()).or_else(|| Some(v.to_string())))
            .unwrap_or_else(|| trimmed.to_string()),
        _ => trimmed.to_string(),
    }
}

fn apply_field(event_id: &str, value: &str) {
    with_state(|s| match event_id {
        EVENT_SERVER => s.settings.server_url = value.trim().to_string(),
        EVENT_TOKEN => s.settings.token = value.trim().to_string(),
        EVENT_GROUP => s.settings.group_id = value.trim().parse().unwrap_or(0),
        EVENT_SUBGROUP => s.settings.set_subgroup_from_text(value),
        EVENT_DAYS => {
            if let Ok(days) = value.trim().parse::<u16>() {
                s.settings.days = days;
            }
        }
        EVENT_PACKAGE => s.settings.package_name = value.trim().to_string(),
        _ => {}
    });
}

// ------------------------------------------------------------- building

pub fn build_ui() -> ui_v3::Element {
    let (settings, status, device_name, busy, log) = with_state(|s| {
        (
            s.settings.clone(),
            s.status.clone(),
            s.device_name.clone(),
            s.busy,
            s.log.clone(),
        )
    });

    let device_line = if device_name.is_empty() {
        text("Браслет не подключён", 14, WARN)
    } else {
        text(&format!("Браслет: {device_name}"), 14, MUTED)
    };

    let problems = settings.problems();
    let hint = if problems.is_empty() {
        text(&status, 15, TEXT)
    } else {
        text(&format!("Не заполнено: {}", problems.join(", ")), 14, WARN)
    };

    let mut root = column()
        .width_full()
        .padding(16)
        .gap(12)
        .child(text("Расписание ОмГУ", 20, TEXT))
        .child(device_line)
        .child(
            card()
                .child(field("Адрес сервера", EVENT_SERVER, &settings.server_url, "https://..."))
                .child(field("Токен", EVENT_TOKEN, &settings.token, "выдан сервером"))
                .child(field(
                    "Группа",
                    EVENT_GROUP,
                    &group_text(settings.group_id),
                    "5028",
                ))
                .child(field(
                    "Подгруппа",
                    EVENT_SUBGROUP,
                    &settings.subgroup_text(),
                    "пусто = все пары",
                ))
                .child(field("Дней вперёд", EVENT_DAYS, &settings.days.to_string(), "14"))
                .child(field(
                    "Приложение на браслете",
                    EVENT_PACKAGE,
                    &settings.package_name,
                    "ru.omsu.bandschedule",
                )),
        )
        .child(
            row()
                .gap(8)
                .child(button("Сохранить", EVENT_SAVE, BTN_BG, busy))
                .child(button(
                    if busy { "Синхронизация…" } else { "Синхронизировать" },
                    EVENT_SYNC,
                    ACCENT,
                    busy || !problems.is_empty(),
                )),
        )
        .child(hint);

    if !log.is_empty() {
        let mut list = column().gap(4);
        for line in log.iter().rev().take(12) {
            list = list.child(text(line, 12, MUTED));
        }
        root = root.child(
            card()
                .child(text("Журнал", 14, MUTED))
                .child(list),
        );
    }

    root
}

fn group_text(group_id: u32) -> String {
    if group_id == 0 {
        String::new()
    } else {
        group_id.to_string()
    }
}

fn field(label: &str, event_id: &str, value: &str, placeholder: &str) -> ui_v3::Element {
    column()
        .gap(4)
        .width_full()
        .child(text(label, 13, MUTED))
        .child(
            ui_v3::Element::new(ui_v3::ElementType::Input, None)
                .prop("value", value)
                .prop("placeholder", placeholder)
                .width_full()
                .padding(8)
                .radius(8)
                .bg(FIELD_BG)
                .text_color(TEXT)
                .size(15)
                .on(ui_v3::Event::Input, event_id)
                .on(ui_v3::Event::Change, event_id),
        )
}

fn button(label: &str, event_id: &str, background: &str, disabled: bool) -> ui_v3::Element {
    let element = ui_v3::Element::new(ui_v3::ElementType::Button, Some(label))
        .padding(10)
        .radius(RADIUS)
        .bg(background)
        .text_color(TEXT)
        .size(15);

    if disabled {
        element.disabled().opacity(0.5)
    } else {
        element.on(ui_v3::Event::Click, event_id)
    }
}

fn text(content: &str, size: u32, color: &str) -> ui_v3::Element {
    ui_v3::Element::new(ui_v3::ElementType::P, Some(content))
        .size(size)
        .text_color(color)
}

fn card() -> ui_v3::Element {
    column().width_full().padding(12).gap(10).radius(RADIUS).bg(CARD_BG)
}

fn column() -> ui_v3::Element {
    ui_v3::Element::new(ui_v3::ElementType::Div, None)
        .flex()
        .flex_direction(ui_v3::FlexDirection::Column)
}

fn row() -> ui_v3::Element {
    ui_v3::Element::new(ui_v3::ElementType::Div, None)
        .flex()
        .flex_direction(ui_v3::FlexDirection::Row)
        .align_center()
}
