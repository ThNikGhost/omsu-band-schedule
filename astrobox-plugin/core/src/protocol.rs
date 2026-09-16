//! Wire protocol between the plugin and the quick app on the band.
//!
//! Every message is a JSON object with a `type` field, carried by
//! `interconnect::send-qaic-message` one string at a time.
//!
//! Two deliberate departures from the original spec, both recorded in
//! docs/DECISIONS.md:
//!
//! 1. A payload that fits in one frame is sent as one `sync_full` message.
//!    Ours is about 4.4 KB for 14 days against a 16 KB single-frame ceiling,
//!    so in practice chunking never runs.
//!
//! 2. When chunking is needed, the band acknowledges *every* frame and the
//!    sender keeps at most `ACK_WINDOW` frames in flight. Blasting all frames
//!    from one `on_event` call without yielding back to the host deadlocks the
//!    BLE queue - this is the documented failure that made the official
//!    FetchBridge plugin rewrite its own protocol.

use serde::{Deserialize, Serialize};

/// Largest single frame, in bytes of UTF-8. Taken from FetchBridge's
/// MAX_UNCHUNKED_WIRE_LEN; conservative, since ours is four times smaller.
pub const MAX_FRAME_BYTES: usize = 16 * 1024;

/// Chunk size for the fallback path, matching FetchBridge's default.
pub const CHUNK_BYTES: usize = 4096;

/// Frames allowed in flight before waiting for an ack.
pub const ACK_WINDOW: usize = 4;

pub const PROTOCOL_VERSION: u32 = 1;

// ---------------------------------------------------------------- inbound

/// What the band can say to us.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Inbound {
    /// The app opened, or the user pressed refresh. `have` is the hash it
    /// already holds, so an unchanged schedule costs nothing.
    SyncReq { have: Option<String> },
    /// One frame arrived intact.
    Ack { index: u32 },
    /// The whole payload was reassembled and stored.
    Done { hash: String },
    /// The band gave up.
    Failed { message: String },
    /// Anything we do not recognise. Never an error: a newer band app may
    /// send messages this plugin predates.
    Unknown { raw: String },
}

#[derive(Deserialize)]
struct RawInbound {
    #[serde(rename = "type")]
    kind: Option<String>,
    have: Option<String>,
    i: Option<u32>,
    h: Option<String>,
    msg: Option<String>,
}

pub fn parse_inbound(text: &str) -> Inbound {
    let raw: RawInbound = match serde_json::from_str(text) {
        Ok(value) => value,
        Err(_) => {
            return Inbound::Unknown {
                raw: truncate(text, 120),
            }
        }
    };

    match raw.kind.as_deref() {
        Some("sync_req") => Inbound::SyncReq {
            have: raw.have.filter(|h| !h.is_empty()),
        },
        Some("ack") => Inbound::Ack {
            index: raw.i.unwrap_or(0),
        },
        Some("done") => Inbound::Done {
            hash: raw.h.unwrap_or_default(),
        },
        Some("failed") => Inbound::Failed {
            message: raw.msg.unwrap_or_default(),
        },
        _ => Inbound::Unknown {
            raw: truncate(text, 120),
        },
    }
}

// --------------------------------------------------------------- outbound

#[derive(Serialize)]
struct UpToDate<'a> {
    #[serde(rename = "type")]
    kind: &'a str,
    v: u32,
    h: &'a str,
}

#[derive(Serialize)]
struct ErrorMessage<'a> {
    #[serde(rename = "type")]
    kind: &'a str,
    v: u32,
    msg: &'a str,
}

/// Nothing changed since the band's last successful sync.
pub fn up_to_date(hash: &str) -> String {
    serde_json::to_string(&UpToDate {
        kind: "up_to_date",
        v: PROTOCOL_VERSION,
        h: hash,
    })
    .unwrap_or_default()
}

/// Something went wrong on our side; the band keeps showing its cache.
pub fn error(message: &str) -> String {
    serde_json::to_string(&ErrorMessage {
        kind: "error",
        v: PROTOCOL_VERSION,
        msg: &truncate(message, 160),
    })
    .unwrap_or_default()
}

// ------------------------------------------------------------------ plan

/// The frames to send, in order.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SendPlan {
    pub frames: Vec<String>,
    /// True when the payload went out as a single `sync_full`.
    pub single: bool,
    pub hash: String,
    pub payload_bytes: usize,
}

impl SendPlan {
    pub fn frame_count(&self) -> usize {
        self.frames.len()
    }
}

/// Build the frames for one payload.
///
/// `payload` is the server's JSON exactly as received; it is forwarded
/// verbatim so the hash the band checks is the hash the server computed.
pub fn plan_send(payload: &str, hash: &str) -> SendPlan {
    let single = format!(
        r#"{{"type":"sync_full","v":{PROTOCOL_VERSION},"h":{},"d":{}}}"#,
        json_string(hash),
        payload
    );

    if single.len() <= MAX_FRAME_BYTES {
        return SendPlan {
            frames: vec![single],
            single: true,
            hash: hash.to_string(),
            payload_bytes: payload.len(),
        };
    }

    let chunks = split_chunks(payload, CHUNK_BYTES);
    let mut frames = Vec::with_capacity(chunks.len() + 2);

    frames.push(format!(
        r#"{{"type":"sync_begin","v":{PROTOCOL_VERSION},"h":{},"parts":{},"size":{}}}"#,
        json_string(hash),
        chunks.len(),
        payload.len()
    ));

    for (index, chunk) in chunks.iter().enumerate() {
        frames.push(format!(
            r#"{{"type":"sync_part","v":{PROTOCOL_VERSION},"i":{index},"d":{}}}"#,
            json_string(chunk)
        ));
    }

    frames.push(format!(
        r#"{{"type":"sync_end","v":{PROTOCOL_VERSION},"h":{}}}"#,
        json_string(hash)
    ));

    SendPlan {
        frames,
        single: false,
        hash: hash.to_string(),
        payload_bytes: payload.len(),
    }
}

/// Split on character boundaries, never mid-codepoint: the schedule is mostly
/// Cyrillic, where every letter is two bytes, so a naive byte split would
/// produce invalid UTF-8 about half the time.
pub fn split_chunks(text: &str, chunk_bytes: usize) -> Vec<String> {
    assert!(chunk_bytes > 0, "chunk size must be positive");
    let mut chunks = Vec::new();
    let mut current = String::new();

    for ch in text.chars() {
        if current.len() + ch.len_utf8() > chunk_bytes && !current.is_empty() {
            chunks.push(std::mem::take(&mut current));
        }
        current.push(ch);
    }
    if !current.is_empty() {
        chunks.push(current);
    }
    if chunks.is_empty() {
        chunks.push(String::new());
    }
    chunks
}

/// How many frames may go out before the next ack, given what is confirmed.
pub fn frames_in_flight(sent: usize, acked: usize) -> usize {
    ACK_WINDOW.saturating_sub(sent.saturating_sub(acked))
}

fn json_string(value: &str) -> String {
    serde_json::to_string(value).unwrap_or_else(|_| "\"\"".to_string())
}

fn truncate(text: &str, max_chars: usize) -> String {
    if text.chars().count() <= max_chars {
        return text.to_string();
    }
    text.chars().take(max_chars).collect::<String>() + "…"
}

// -------------------------------------------------------------- payload

/// The few fields we need out of the server response. Everything else is
/// forwarded to the band untouched.
#[derive(Debug, Clone, Deserialize)]
pub struct PayloadInfo {
    #[serde(default)]
    pub v: u32,
    #[serde(default)]
    pub h: String,
    #[serde(default)]
    pub g: Option<String>,
    #[serde(default)]
    pub gen: Option<String>,
    #[serde(default)]
    pub stale: bool,
    #[serde(default)]
    pub days: Vec<DayInfo>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct DayInfo {
    #[serde(default)]
    pub d: String,
    #[serde(default)]
    pub l: Vec<serde_json::Value>,
}

impl PayloadInfo {
    pub fn lesson_count(&self) -> usize {
        self.days.iter().map(|day| day.l.len()).sum()
    }
}

/// Reject anything we would not want to hand to the band.
pub fn inspect_payload(body: &str) -> Result<PayloadInfo, String> {
    let info: PayloadInfo =
        serde_json::from_str(body).map_err(|e| format!("сервер вернул не тот JSON: {e}"))?;

    if info.v != 1 {
        return Err(format!("версия формата {} не поддерживается", info.v));
    }
    if info.h.is_empty() {
        return Err("в ответе сервера нет хэша".to_string());
    }
    // An empty days array is valid: the university publishes about ten days
    // ahead, so the tail of the term is legitimately empty.
    Ok(info)
}
