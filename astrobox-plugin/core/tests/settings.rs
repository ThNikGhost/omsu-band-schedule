//! Settings: validation, URL building, round-tripping through JSON.

use omsu_sync_core::settings::{describe, Settings, DEFAULT_DAYS, DEFAULT_PACKAGE, MAX_DAYS};

fn ready() -> Settings {
    Settings {
        server_url: "https://example.org".to_string(),
        token: "secret-token".to_string(),
        group_id: 5028,
        subgroup: Some(1),
        ..Settings::default()
    }
}

#[test]
fn defaults_match_the_project() {
    let settings = Settings::default();
    assert_eq!(settings.days, DEFAULT_DAYS);
    assert_eq!(settings.package_name, DEFAULT_PACKAGE);
    assert_eq!(settings.subgroup, None);
    assert!(!settings.is_ready(), "пустые настройки не готовы к работе");
}

#[test]
fn a_filled_in_configuration_is_ready() {
    assert_eq!(ready().problems(), Vec::<String>::new());
}

#[test]
fn reports_every_missing_field_at_once() {
    // A user fixing a form wants the whole list, not one problem per attempt.
    let problems = Settings::default().problems();
    assert_eq!(problems.len(), 3);
    assert!(problems.iter().any(|p| p.contains("адрес")));
    assert!(problems.iter().any(|p| p.contains("токен")));
    assert!(problems.iter().any(|p| p.contains("группы")));
}

#[test]
fn rejects_a_url_without_a_scheme() {
    let mut settings = ready();
    settings.server_url = "example.org".to_string();
    assert!(settings.problems().iter().any(|p| p.contains("http://")));
}

#[test]
fn rejects_an_out_of_range_day_count() {
    let mut settings = ready();
    settings.days = 0;
    assert!(!settings.is_ready());
    settings.days = MAX_DAYS + 1;
    assert!(!settings.is_ready());
    settings.days = MAX_DAYS;
    assert!(settings.is_ready());
}

#[test]
fn builds_the_schedule_url() {
    assert_eq!(
        ready().schedule_url(),
        "https://example.org/api/v1/schedule?group=5028&days=14&subgroup=1"
    );
}

#[test]
fn a_trailing_slash_does_not_double_up() {
    let mut settings = ready();
    settings.server_url = "https://example.org/".to_string();
    assert!(settings.schedule_url().starts_with("https://example.org/api/v1/"));
}

#[test]
fn no_subgroup_means_no_query_parameter() {
    let mut settings = ready();
    settings.subgroup = None;
    let url = settings.schedule_url();
    assert!(!url.contains("subgroup"), "{url}");
}

#[test]
fn the_token_never_appears_in_the_url() {
    // It goes in the Authorization header precisely so it cannot leak into
    // logs, crash reports or a proxy's access log.
    let settings = ready();
    assert!(!settings.schedule_url().contains("secret-token"));
    assert_eq!(settings.bearer(), "Bearer secret-token");
}

#[test]
fn subgroup_is_parsed_leniently() {
    let mut settings = Settings::default();

    settings.set_subgroup_from_text("2");
    assert_eq!(settings.subgroup, Some(2));

    settings.set_subgroup_from_text("  1 ");
    assert_eq!(settings.subgroup, Some(1));

    // Empty means "no filter".
    settings.set_subgroup_from_text("");
    assert_eq!(settings.subgroup, None);

    // Nonsense clears the filter rather than silently keeping the old value.
    settings.set_subgroup_from_text("2");
    settings.set_subgroup_from_text("ой");
    assert_eq!(settings.subgroup, None);

    settings.set_subgroup_from_text("0");
    assert_eq!(settings.subgroup, None);
}

#[test]
fn subgroup_text_round_trips() {
    let mut settings = Settings::default();
    assert_eq!(settings.subgroup_text(), "");
    settings.subgroup = Some(2);
    assert_eq!(settings.subgroup_text(), "2");
}

#[test]
fn survives_a_round_trip_through_json() {
    let mut original = ready();
    original.device_addr = Some("AA:BB:CC:DD:EE:FF".to_string());
    original.last_hash = Some("70bbe23f4e25".to_string());

    let restored = Settings::from_json(&original.to_json()).unwrap();
    assert_eq!(restored, original);
}

#[test]
fn missing_fields_fall_back_to_defaults() {
    // An older config file must not stop the plugin from loading.
    let restored = Settings::from_json(r#"{"version":1,"group_id":5028}"#).unwrap();
    assert_eq!(restored.group_id, 5028);
    assert_eq!(restored.days, DEFAULT_DAYS);
    assert_eq!(restored.package_name, DEFAULT_PACKAGE);
}

#[test]
fn refuses_a_config_from_a_future_version() {
    let err = Settings::from_json(r#"{"version":99}"#).unwrap_err();
    assert!(err.contains("99"), "{err}");
}

#[test]
fn refuses_broken_json() {
    assert!(Settings::from_json("{не json").is_err());
}

#[test]
fn the_log_line_hides_the_token() {
    let line = describe(&ready());
    assert!(!line.contains("secret-token"), "{line}");
    assert!(line.contains("***"));
    assert!(line.contains("5028"));
}
