//! Fetching the schedule and pushing it to the band.

use astrobox_ng_wit::astrobox::psys_host;
use omsu_sync_core::protocol::{
    frames_in_flight, inspect_payload, plan_send, up_to_date, Inbound,
};
use omsu_sync_core::settings::Settings;

use crate::state::{log_line, save_settings, set_status, with_state, Transfer};

/// The quick app has to be running to receive anything, so it is launched
/// first and given a moment to come up. Borrowed from the behaviour of the
/// official sync plugins.
const LAUNCH_WAIT_MS: u64 = 2000;
pub const ENTRY_PAGE: &str = "pages/index";

pub async fn refresh_device() {
    let devices = psys_host::device::get_connected_device_list().await;
    match devices.first() {
        Some(device) => {
            with_state(|s| {
                s.device_addr = device.addr.clone();
                s.device_name = device.name.clone();
            });
        }
        None => {
            with_state(|s| {
                s.device_addr.clear();
                s.device_name.clear();
            });
        }
    }
}

/// Full sync: fetch from the server, then hand the payload to the band.
///
/// `force` ignores the stored hash, for when the user presses the button and
/// wants something to happen even if nothing changed.
pub async fn sync_now(force: bool) {
    if with_state(|s| s.busy) {
        log_line("синхронизация уже идёт");
        return;
    }
    with_state(|s| s.busy = true);
    let result = run_sync(force).await;
    with_state(|s| s.busy = false);

    if let Err(message) = result {
        set_status(format!("Ошибка: {message}"));
        log_line(format!("ошибка: {message}"));
        let (addr, package) = with_state(|s| (s.device_addr.clone(), s.settings.package_name.clone()));
        if !addr.is_empty() {
            let frame = omsu_sync_core::protocol::error(&message);
            let _ = psys_host::interconnect::send_qaic_message(&addr, &package, &frame).await;
        }
    }
    redraw().await;
}

async fn run_sync(force: bool) -> Result<(), String> {
    let settings = with_state(|s| s.settings.clone());

    let problems = settings.problems();
    if !problems.is_empty() {
        return Err(problems.join("; "));
    }

    refresh_device().await;
    let addr = with_state(|s| s.device_addr.clone());
    if addr.is_empty() {
        return Err("браслет не подключён".to_string());
    }

    set_status("Запрашиваю расписание…");
    log_line(format!("запрос: {}", settings.schedule_url()));

    let known_hash = if force { None } else { settings.last_hash.clone() };
    let response = fetch_schedule(&settings, known_hash.as_deref())?;

    match response {
        Fetched::NotModified => {
            let hash = settings.last_hash.clone().unwrap_or_default();
            log_line("сервер ответил 304: расписание не менялось");
            set_status("Расписание не менялось");
            let frame = up_to_date(&hash);
            send_one(&addr, &settings.package_name, &frame).await?;
            Ok(())
        }
        Fetched::Body(body) => {
            let info = inspect_payload(&body)?;
            log_line(format!(
                "получено: {} дн., {} пар, хэш {}{}",
                info.days.len(),
                info.lesson_count(),
                info.h,
                if info.stale { ", данные устарели" } else { "" }
            ));

            let plan = plan_send(&body, &info.h);
            log_line(format!(
                "{} — {} байт, кадров: {}",
                if plan.single { "одно сообщение" } else { "с нарезкой" },
                plan.payload_bytes,
                plan.frame_count()
            ));

            ensure_app_running(&addr, &settings.package_name).await;

            with_state(|s| {
                s.pending = Some(Transfer {
                    frames: plan.frames.clone(),
                    sent: 0,
                    acked: 0,
                    hash: info.h.clone(),
                })
            });

            set_status("Отправляю на браслет…");
            pump_frames(&addr, &settings.package_name).await?;

            if plan.single {
                // Nothing to wait for: one frame means the transfer is done
                // as soon as the host accepted it.
                finish(&info.h)?;
            }
            Ok(())
        }
    }
}

enum Fetched {
    NotModified,
    Body(String),
}

fn fetch_schedule(settings: &Settings, known_hash: Option<&str>) -> Result<Fetched, String> {
    let url = settings.schedule_url();
    let mut request = waki::Client::new()
        .get(&url)
        .header("Authorization", settings.bearer())
        .header("Accept", "application/json");

    if let Some(hash) = known_hash.filter(|h| !h.is_empty()) {
        request = request.header("If-None-Match", format!("\"{hash}\""));
    }

    let response = request
        .send()
        .map_err(|e| format!("сервер недоступен: {e}"))?;

    let status = response.status_code();
    let body = response
        .body()
        .map_err(|e| format!("не удалось прочитать ответ: {e}"))?;

    match status {
        200 => String::from_utf8(body)
            .map(Fetched::Body)
            .map_err(|_| "ответ сервера не в UTF-8".to_string()),
        304 => Ok(Fetched::NotModified),
        401 | 403 => Err("сервер не принял токен".to_string()),
        503 => Err("сервер ещё не загрузил расписание".to_string()),
        other => Err(format!("сервер ответил {other}")),
    }
}

/// Launch the quick app if it is installed, so there is someone to receive
/// the message. Failure is not fatal: the app may already be open.
async fn ensure_app_running(addr: &str, package: &str) {
    let apps = match psys_host::thirdpartyapp::get_thirdparty_app_list(addr).await {
        Ok(apps) => apps,
        Err(_) => {
            log_line("не удалось получить список приложений браслета");
            return;
        }
    };

    match apps.iter().find(|app| app.package_name == package) {
        Some(app) => {
            let _ = psys_host::thirdpartyapp::launch_qa(addr, app, ENTRY_PAGE).await;
            psys_host::timer::set_timeout(LAUNCH_WAIT_MS, "launch").await;
            log_line("приложение на браслете запущено");
        }
        None => log_line(format!("приложение {package} не установлено на браслете")),
    }
}

/// Send as many frames as the ack window allows, then return control to the
/// host. Sending everything in one go without yielding is what deadlocks the
/// BLE queue; see docs/DECISIONS.md.
pub async fn pump_frames(addr: &str, package: &str) -> Result<(), String> {
    loop {
        let next = with_state(|s| match &s.pending {
            Some(transfer) => {
                let allowance = frames_in_flight(transfer.sent, transfer.acked);
                if allowance == 0 || transfer.sent >= transfer.frames.len() {
                    None
                } else {
                    Some((transfer.sent, transfer.frames[transfer.sent].clone()))
                }
            }
            None => None,
        });

        let Some((index, frame)) = next else {
            return Ok(());
        };

        psys_host::interconnect::send_qaic_message(addr, package, &frame)
            .await
            .map_err(|_| format!("браслет не принял кадр {index}"))?;

        with_state(|s| {
            if let Some(transfer) = s.pending.as_mut() {
                transfer.sent += 1;
            }
        });
    }
}

async fn send_one(addr: &str, package: &str, frame: &str) -> Result<(), String> {
    psys_host::interconnect::send_qaic_message(addr, package, frame)
        .await
        .map_err(|_| "браслет не принял сообщение".to_string())
}

fn finish(hash: &str) -> Result<(), String> {
    let settings = with_state(|s| {
        s.pending = None;
        s.settings.last_hash = Some(hash.to_string());
        s.settings.clone()
    });
    save_settings(&settings)?;
    set_status("Расписание отправлено");
    log_line(format!("готово, хэш {hash}"));
    Ok(())
}

/// A message arrived from the band.
pub async fn handle_inbound(text: &str) {
    let (addr, package) = with_state(|s| (s.device_addr.clone(), s.settings.package_name.clone()));

    match omsu_sync_core::parse_inbound(text) {
        Inbound::SyncReq { have } => {
            log_line(match &have {
                Some(hash) => format!("браслет просит обновление, у него хэш {hash}"),
                None => "браслет просит расписание, кэша у него нет".to_string(),
            });
            with_state(|s| s.settings.last_hash = have);
            sync_now(false).await;
        }
        Inbound::Ack { index } => {
            with_state(|s| {
                if let Some(transfer) = s.pending.as_mut() {
                    transfer.acked = transfer.acked.max(index as usize + 1);
                }
            });
            if !addr.is_empty() {
                let _ = pump_frames(&addr, &package).await;
            }
        }
        Inbound::Done { hash } => {
            log_line(format!("браслет подтвердил приём, хэш {hash}"));
            let _ = finish(&hash);
            redraw().await;
        }
        Inbound::Failed { message } => {
            log_line(format!("браслет сообщил об ошибке: {message}"));
            set_status("Браслет не принял данные");
            with_state(|s| s.pending = None);
            redraw().await;
        }
        Inbound::Unknown { raw } => {
            tracing::debug!("неизвестное сообщение от браслета: {raw}");
        }
    }
}

/// Ask the host to re-render the settings screen.
pub async fn redraw() {
    let root = with_state(|s| s.root.clone());
    if let Some(root) = root {
        psys_host::ui_v3::render(&root, crate::ui::build_ui());
    }
}
