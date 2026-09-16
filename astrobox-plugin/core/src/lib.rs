//! Logic of the OmSU schedule sync plugin, with no AstroBox dependency.
//!
//! Split out from the plugin crate on purpose: the WIT bindings only compile
//! for `wasm32-wasip2`, so anything living beside them cannot be unit-tested.
//! Everything here builds and runs on the host.

pub mod protocol;
pub mod settings;

pub use protocol::{
    error, frames_in_flight, inspect_payload, parse_inbound, plan_send, split_chunks, Inbound,
    PayloadInfo, SendPlan, ACK_WINDOW, CHUNK_BYTES, MAX_FRAME_BYTES,
};
pub use settings::{describe, Settings, CONFIG_FILE, DEFAULT_DAYS, DEFAULT_PACKAGE, MAX_DAYS};
