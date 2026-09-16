//! Protocol framing, checked against the real server payload.

use omsu_sync_core::protocol::{
    frames_in_flight, inspect_payload, parse_inbound, plan_send, split_chunks, Inbound, ACK_WINDOW,
    CHUNK_BYTES, MAX_FRAME_BYTES,
};

/// The actual response for group 5028, as committed in shared/example.json.
const EXAMPLE: &str = include_str!("../../../shared/example.json");

fn compact(text: &str) -> String {
    let value: serde_json::Value = serde_json::from_str(text).unwrap();
    serde_json::to_string(&value).unwrap()
}

// ------------------------------------------------------------- inbound

#[test]
fn parses_sync_request_with_a_known_hash() {
    let msg = parse_inbound(r#"{"type":"sync_req","have":"70bbe23f4e25"}"#);
    assert_eq!(
        msg,
        Inbound::SyncReq {
            have: Some("70bbe23f4e25".to_string())
        }
    );
}

#[test]
fn a_band_with_no_cache_sends_no_hash() {
    assert_eq!(
        parse_inbound(r#"{"type":"sync_req"}"#),
        Inbound::SyncReq { have: None }
    );
    // An empty string means the same thing as absent.
    assert_eq!(
        parse_inbound(r#"{"type":"sync_req","have":""}"#),
        Inbound::SyncReq { have: None }
    );
}

#[test]
fn parses_ack_and_done() {
    assert_eq!(
        parse_inbound(r#"{"type":"ack","i":3}"#),
        Inbound::Ack { index: 3 }
    );
    assert_eq!(
        parse_inbound(r#"{"type":"done","h":"abc123abc123"}"#),
        Inbound::Done {
            hash: "abc123abc123".to_string()
        }
    );
}

#[test]
fn unknown_messages_never_panic() {
    // A newer band app may speak messages this plugin predates; that must be
    // survivable, not fatal.
    for text in [
        "",
        "не json",
        "{}",
        r#"{"type":"from_the_future"}"#,
        r#"{"type":123}"#,
        "[1,2,3]",
    ] {
        match parse_inbound(text) {
            Inbound::Unknown { .. } => {}
            other => panic!("ожидался Unknown для {text:?}, получено {other:?}"),
        }
    }
}

#[test]
fn ack_without_an_index_is_treated_as_the_first_frame() {
    assert_eq!(
        parse_inbound(r#"{"type":"ack"}"#),
        Inbound::Ack { index: 0 }
    );
}

// ---------------------------------------------------------------- plan

#[test]
fn the_real_payload_fits_in_a_single_frame() {
    // This is the whole reason chunking is a fallback and not the main path.
    let payload = compact(EXAMPLE);
    let plan = plan_send(&payload, "70bbe23f4e25");

    assert!(plan.single, "ожидалась отправка одним сообщением");
    assert_eq!(plan.frame_count(), 1);
    assert!(
        plan.frames[0].len() < MAX_FRAME_BYTES,
        "кадр {} байт, потолок {}",
        plan.frames[0].len(),
        MAX_FRAME_BYTES
    );
}

#[test]
fn the_single_frame_carries_the_payload_as_an_object() {
    let payload = compact(EXAMPLE);
    let plan = plan_send(&payload, "70bbe23f4e25");
    let parsed: serde_json::Value = serde_json::from_str(&plan.frames[0]).unwrap();

    assert_eq!(parsed["type"], "sync_full");
    assert_eq!(parsed["h"], "70bbe23f4e25");
    // Embedded as an object, not as an escaped string: escaping would inflate
    // every Cyrillic character and roughly double the frame.
    assert!(parsed["d"].is_object());
    assert_eq!(parsed["d"]["gid"], 5028);
    assert_eq!(parsed["d"]["days"].as_array().unwrap().len(), 9);
}

#[test]
fn an_oversized_payload_is_chunked_with_begin_and_end() {
    let big = format!(r#"{{"v":1,"pad":"{}"}}"#, "я".repeat(20_000));
    let plan = plan_send(&big, "deadbeef1234");

    assert!(!plan.single);
    let parts = plan.frame_count() - 2;
    assert!(parts >= 2, "ожидалось несколько частей, получено {parts}");

    let begin: serde_json::Value = serde_json::from_str(&plan.frames[0]).unwrap();
    assert_eq!(begin["type"], "sync_begin");
    assert_eq!(begin["parts"], parts);
    assert_eq!(begin["size"], big.len());

    let end: serde_json::Value = serde_json::from_str(plan.frames.last().unwrap()).unwrap();
    assert_eq!(end["type"], "sync_end");
    assert_eq!(end["h"], "deadbeef1234");
}

#[test]
fn chunks_reassemble_into_the_original_payload() {
    let big = format!(r#"{{"v":1,"pad":"{}"}}"#, "щ".repeat(20_000));
    let plan = plan_send(&big, "h");

    let mut rebuilt = String::new();
    for frame in &plan.frames[1..plan.frames.len() - 1] {
        let parsed: serde_json::Value = serde_json::from_str(frame).unwrap();
        rebuilt.push_str(parsed["d"].as_str().unwrap());
    }
    assert_eq!(rebuilt, big);
}

#[test]
fn part_indices_are_sequential_from_zero() {
    let big = format!(r#"{{"v":1,"pad":"{}"}}"#, "a".repeat(30_000));
    let plan = plan_send(&big, "h");

    for (expected, frame) in plan.frames[1..plan.frames.len() - 1].iter().enumerate() {
        let parsed: serde_json::Value = serde_json::from_str(frame).unwrap();
        assert_eq!(parsed["i"], expected);
    }
}

#[test]
fn every_frame_stays_under_the_ceiling() {
    let big = format!(r#"{{"v":1,"pad":"{}"}}"#, "ю".repeat(60_000));
    let plan = plan_send(&big, "h");
    for (i, frame) in plan.frames.iter().enumerate() {
        assert!(
            frame.len() <= MAX_FRAME_BYTES,
            "кадр {i} занял {} байт",
            frame.len()
        );
    }
}

// -------------------------------------------------------------- chunks

#[test]
fn chunks_never_split_a_cyrillic_character() {
    // Every Cyrillic letter is two bytes, so an odd-sized byte split would
    // corrupt roughly half of them.
    let text = "ё".repeat(5000);
    let chunks = split_chunks(&text, 1001);
    assert!(chunks.len() > 1);
    for chunk in &chunks {
        assert!(chunk.chars().all(|c| c == 'ё'));
        assert!(chunk.len() <= 1001);
    }
    assert_eq!(chunks.concat(), text);
}

#[test]
fn a_character_larger_than_the_chunk_still_survives() {
    let chunks = split_chunks("😀😀", 2);
    assert_eq!(chunks.concat(), "😀😀");
}

#[test]
fn empty_input_yields_one_empty_chunk() {
    assert_eq!(split_chunks("", CHUNK_BYTES), vec![String::new()]);
}

// --------------------------------------------------------- flow control

#[test]
fn the_window_limits_frames_in_flight() {
    // Nothing sent: the whole window is available.
    assert_eq!(frames_in_flight(0, 0), ACK_WINDOW);
    // Window full: wait.
    assert_eq!(frames_in_flight(ACK_WINDOW, 0), 0);
    // One ack frees exactly one slot.
    assert_eq!(frames_in_flight(ACK_WINDOW, 1), 1);
    // Acks cannot outrun sends into a negative window.
    assert_eq!(frames_in_flight(1, 5), ACK_WINDOW);
}

// ------------------------------------------------------------- payload

#[test]
fn accepts_the_real_server_response() {
    let info = inspect_payload(EXAMPLE).expect("реальный ответ должен приниматься");
    assert_eq!(info.v, 1);
    assert_eq!(info.h, "70bbe23f4e25");
    assert_eq!(info.g.as_deref(), Some("МБС-301-О-01"));
    assert_eq!(info.days.len(), 9);
    assert_eq!(info.lesson_count(), 34);
    assert!(!info.stale);
}

#[test]
fn an_empty_schedule_is_valid() {
    // Normal once the university stops publishing further ahead.
    let body = r#"{"v":1,"gid":5028,"gen":"x","src":"y","stale":false,"h":"abcabcabcabc","days":[]}"#;
    let info = inspect_payload(body).unwrap();
    assert_eq!(info.days.len(), 0);
    assert_eq!(info.lesson_count(), 0);
}

#[test]
fn rejects_a_wrong_format_version() {
    let body = r#"{"v":2,"h":"abcabcabcabc","days":[]}"#;
    assert!(inspect_payload(body).unwrap_err().contains("версия"));
}

#[test]
fn rejects_a_response_without_a_hash() {
    let body = r#"{"v":1,"days":[]}"#;
    assert!(inspect_payload(body).unwrap_err().contains("хэш"));
}

#[test]
fn rejects_html_error_pages() {
    // A misconfigured reverse proxy answers with HTML, not JSON.
    assert!(inspect_payload("<html>502 Bad Gateway</html>").is_err());
}

#[test]
fn error_messages_are_truncated_but_valid_json() {
    let long = "х".repeat(500);
    let frame = omsu_sync_core::protocol::error(&long);
    let parsed: serde_json::Value = serde_json::from_str(&frame).unwrap();
    assert_eq!(parsed["type"], "error");
    assert!(parsed["msg"].as_str().unwrap().chars().count() <= 161);
}

#[test]
fn up_to_date_carries_the_hash() {
    let parsed: serde_json::Value =
        serde_json::from_str(&omsu_sync_core::protocol::up_to_date("70bbe23f4e25")).unwrap();
    assert_eq!(parsed["type"], "up_to_date");
    assert_eq!(parsed["h"], "70bbe23f4e25");
}
