//! AstroBox v2 plugin: pulls the OmSU schedule from the server and pushes it
//! to the quick app on a Xiaomi Smart Band 10.
//!
//! The band has no internet of its own, so this plugin is the only path data
//! can take. All of the protocol and settings logic lives in the `omsu-sync-core`
//! crate next door, which builds for the host and is unit-tested there; the
//! WIT bindings only compile for wasm32-wasip2.

use astrobox_ng_wit::exports::astrobox::psys_plugin::{
    event_v3::{self, EventType},
    lifecycle,
};
use astrobox_ng_wit::FutureReader;

pub mod logger;
pub mod state;
pub mod sync;
pub mod ui;

struct OmsuPlugin;

fn immediate_string() -> FutureReader<String> {
    let (writer, reader) = astrobox_ng_wit::wit_future::new::<String>(String::new);
    astrobox_ng_wit::spawn(async move {
        let _ = writer.write(String::new()).await;
    });
    reader
}

fn immediate_unit() -> FutureReader<()> {
    let (writer, reader) = astrobox_ng_wit::wit_future::new::<()>(|| ());
    astrobox_ng_wit::spawn(async move {
        let _ = writer.write(()).await;
    });
    reader
}

impl event_v3::Guest for OmsuPlugin {
    fn on_event(event_type: EventType, event_payload: String) -> FutureReader<String> {
        if matches!(event_type, EventType::InterconnectMessage) {
            // Host calls must be driven to completion here: returning early
            // would leave the message half-handled.
            astrobox_ng_wit::block_on(async {
                sync::handle_inbound(&event_payload).await;
            });
        } else if matches!(event_type, EventType::DeviceAction) {
            astrobox_ng_wit::block_on(async {
                sync::ensure_subscribed().await;
            });
        } else {
            tracing::debug!("событие {:?}: {}", event_type, event_payload);
        }
        immediate_string()
    }

    fn on_ui_event_v3(
        event_id: String,
        event: event_v3::Event,
        event_payload: String,
    ) -> FutureReader<String> {
        astrobox_ng_wit::block_on(async {
            ui::handle_ui_event(event, &event_id, &event_payload).await;
        });
        immediate_string()
    }

    fn on_ui_render(element_id: String) -> FutureReader<()> {
        astrobox_ng_wit::block_on(async {
            ui::render_main_ui(&element_id).await;
        });
        immediate_unit()
    }

    fn on_card_render(_card_id: String) -> FutureReader<()> {
        immediate_unit()
    }
}

impl lifecycle::Guest for OmsuPlugin {
    fn on_load() {
        logger::init();
        let settings = state::with_state(|s| s.settings.clone());
        tracing::info!(
            "плагин расписания ОмГУ загружен: {}",
            omsu_sync_core::settings::describe(&settings)
        );

        // Without this subscription the band's messages never reach us: the
        // host routes interconnect traffic only to plugins that asked for it,
        // matching on device address plus package name exactly.
        astrobox_ng_wit::block_on(async {
            sync::ensure_subscribed().await;
        });
    }
}

astrobox_ng_wit::export!(OmsuPlugin);
