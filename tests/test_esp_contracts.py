import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from contracts.esp import parse_esp_json, parse_esp_packet

_PACIFIC = "America/Los_Angeles"
_SAMPLE = "com.apple.MobileSMS | Eli Schiffler | This is an example text | 20261114T125641"
_JSON_SAMPLE = {
    "app": "com.apple.MobileSMS",
    "title": "Matthew Cheese Ellis",
    "message": "T minus 10 min",
    "date": "20261114T130105",
}


def test_json_fields_map_to_notification_and_match_equivalent_text_packet():
    notification = parse_esp_json(json.dumps(_JSON_SAMPLE), timezone_name=_PACIFIC)
    assert notification.sender == notification.title == "Matthew Cheese Ellis"
    assert notification.body == "T minus 10 min"
    assert notification.received_at == datetime(2026, 11, 14, 21, 1, 5, tzinfo=UTC)
    assert notification == parse_esp_packet(
        "com.apple.MobileSMS | Matthew Cheese Ellis | T minus 10 min | 20261114T130105",
        timezone_name=_PACIFIC,
    )


def test_json_preserves_pipes_in_title_and_body():
    packet = _JSON_SAMPLE | {
        "app": "com.example.news",
        "title": " A | B ",
        "message": "C | D 😀",
    }
    notification = parse_esp_json(
        json.dumps(packet, ensure_ascii=False).encode(), timezone_name=_PACIFIC
    )
    assert notification.title == " A | B "
    assert notification.sender is None
    assert notification.body == "C | D 😀"


@pytest.mark.parametrize(
    "overrides",
    [
        {"app": "not-a-bundle-id"},
        {"title": 1},
        {"message": None},
        {"message": ["not", "a", "string"]},
        {"date": 20261114130105},
        {"date": "20260229T130105"},
        {"date": "20261101T013000"},
        {"date": "20260308T023000"},
        {"body": "unsupported"},
        {"event_id": "header only"},
    ],
)
def test_json_rejects_invalid_fields_and_local_dates(overrides):
    with pytest.raises(ValueError):
        parse_esp_json(json.dumps(_JSON_SAMPLE | overrides), timezone_name=_PACIFIC)


@pytest.mark.parametrize("payload", ["{", "[]", "null", b'{"app":"\xff"}'])
def test_json_rejects_malformed_payload(payload):
    with pytest.raises(ValueError):
        parse_esp_json(payload, timezone_name=_PACIFIC)


def test_messages_sample_maps_sender_and_timestamp():
    notification = parse_esp_packet(_SAMPLE, timezone_name=_PACIFIC)
    assert notification.app == "com.apple.MobileSMS"
    assert notification.sender == notification.title == "Eli Schiffler"
    assert notification.body == "This is an example text"
    assert notification.received_at == datetime(2026, 11, 14, 20, 56, 41, tzinfo=UTC)
    assert not notification.content_hidden


@pytest.mark.parametrize(
    "app", ["com.apple.mobilemail", "com.tinyspeck.slack", "net.example-app.News"]
)
def test_general_app_keeps_title_without_inventing_sender(app):
    packet = f"{app} | Jordan | Agenda | 20261114T125641"
    notification = parse_esp_packet(packet, timezone_name=_PACIFIC)
    assert notification.app == app
    assert notification.title == "Jordan"
    assert notification.sender is None
    assert notification.conversation_id is None


def test_body_preserves_pipes_unicode_newline_and_internal_spaces():
    packet = " com.example.news | Résumé |  | ¡Hola!  😀\none | two || three | 20261114T125641 "
    notification = parse_esp_packet(packet, timezone_name=_PACIFIC)
    assert notification.title == "Résumé"
    assert notification.body == "| ¡Hola!  😀\none | two || three"


def test_empty_messages_preview_is_hidden_and_general_title_is_still_available():
    incoming = parse_esp_packet(
        "com.apple.MobileSMS | Sam |  | 20261114T125641", timezone_name=_PACIFIC
    )
    calendar = parse_esp_packet(
        "com.apple.mobilecal | Meeting starts now |  | 20261114T125641", timezone_name=_PACIFIC
    )
    assert incoming.content_hidden
    assert not calendar.content_hidden
    assert calendar.title == "Meeting starts now"


def test_packet_without_sender_does_not_invent_one():
    notification = parse_esp_packet(
        "com.apple.MobileSMS || Dinner? | 20261114T125641", timezone_name="UTC"
    )
    assert notification.sender is None
    assert not notification.content_hidden


@pytest.mark.parametrize(
    "packet",
    [
        "",
        "com.apple.MobileSMS | sender | body",
        "com.apple.MobileSMS | sender | body | 20261114T125641 |",
        " | sender | body | 20261114T125641",
        "Messages | sender | body | 20261114T125641",
        "com.apple..MobileSMS | sender | body | 20261114T125641",
        "com.apple.MóbileSMS | sender | body | 20261114T125641",
        "com.apple.MobileSMS | sender | body | 2026-11-14T12:56:41",
        "com.apple.MobileSMS | sender | body | 20261114T125641Z",
        "com.apple.MobileSMS | sender | body | ２０２６１１１４T125641",
        "com.apple.MobileSMS | sender | body | 20261114t125641",
        "com.apple.MobileSMS | sender | body | 20261114T245641",
        "com.apple.MobileSMS | sender | body | 20260229T125641",
        "com.apple.MobileSMS | sender | body | 20261314T125641",
    ],
)
def test_invalid_packets_are_rejected(packet):
    with pytest.raises(ValueError):
        parse_esp_packet(packet, timezone_name=_PACIFIC)


def test_valid_leap_day_and_iana_timezone_conversion():
    notification = parse_esp_packet(
        "com.example.news | Leap day | Happy leap day | 20240229T010203", timezone_name="Asia/Tokyo"
    )
    assert notification.received_at == datetime(2024, 2, 28, 16, 2, 3, tzinfo=UTC)


@pytest.mark.parametrize(
    "stamp, error",
    [
        ("20260308T023000", "skipped local hour"),
        ("20261101T013000", "ambiguous"),
    ],
)
def test_dst_gaps_and_folds_require_explicit_offset(stamp, error):
    with pytest.raises(ValueError, match=error):
        parse_esp_packet(f"com.example.news | Title | Body | {stamp}", timezone_name=_PACIFIC)


def test_invalid_timezone_rejected():
    with pytest.raises(ValueError, match="valid IANA timezone"):
        parse_esp_packet(_SAMPLE, timezone_name="Not/A/Timezone")


def test_field_length_limits_measure_unicode_characters():
    max_body = "神" * 4096
    max_label = "é" * 256
    notification = parse_esp_packet(
        f"com.example.news | {max_label} | {max_body} | 20261114T125641",
        timezone_name=_PACIFIC,
    )
    assert notification.title == max_label
    assert notification.body == max_body
    with pytest.raises(ValueError):
        parse_esp_packet(
            f"com.example.news | {max_label} | {max_body}X | 20261114T125641",
            timezone_name=_PACIFIC,
        )
    with pytest.raises(ValueError):
        parse_esp_packet(
            f"com.apple.MobileSMS | {'a' * 121} | Body | 20261114T125641", timezone_name=_PACIFIC
        )
    with pytest.raises(ValueError):
        parse_esp_packet(
            f"com.example.news | {max_label}X | Body | 20261114T125641", timezone_name=_PACIFIC
        )


def test_id_stable_for_same_normalized_fields_and_accepts_explicit_id():
    first = parse_esp_packet(_SAMPLE, timezone_name=_PACIFIC)
    retry = parse_esp_packet(
        "com.apple.MobileSMS|Eli Schiffler|This is an example text|20261114T205641",
        timezone_name="UTC",
    )
    separate_device_event = uuid4()
    explicit = parse_esp_packet(_SAMPLE, timezone_name=_PACIFIC, event_id=separate_device_event)
    later = parse_esp_packet(_SAMPLE.replace("125641", "125642"), timezone_name=_PACIFIC)
    assert first == retry
    assert first.event_id.version == 5
    assert explicit.event_id == separate_device_event != first.event_id
    assert first.event_id != later.event_id


def test_named_text_group_shares_identity_across_senders_but_not_dm_or_other_chat():
    from server.store import grouping_key

    def parse(sender, subtitle, app="com.apple.MobileSMS"):
        return parse_esp_json(
            json.dumps(_JSON_SAMPLE | {"title": sender, "subtitle": subtitle, "app": app}),
            timezone_name=_PACIFIC,
        )

    first = parse("Sam", "Hackathon Team")
    second = parse("Alex", "  Hackathon   Team ")
    assert grouping_key(first) == grouping_key(second)
    assert first.sender == "Sam" and second.sender == "Alex"
    assert first.conversation_name == "Hackathon Team"
    assert second.subtitle == "  Hackathon   Team "
    assert grouping_key(first) != grouping_key(parse("Sam", "Family"))
    assert grouping_key(first) != grouping_key(parse("Sam", ""))
    assert parse("Sam", " ").conversation_id is None
    assert parse("Sam", "Hackathon Team", "com.apple.mobilemail").conversation_id is None


def test_unnamed_text_group_combines_sender_and_other_recipient():
    from server.store import grouping_key

    def parse(sender, subtitle, message="Hello"):
        return parse_esp_json(
            json.dumps(_JSON_SAMPLE | {"title": sender, "subtitle": subtitle, "message": message}),
            timezone_name=_PACIFIC,
        )

    first = parse("Sam", "To you & Alex")
    second = parse("Alex", "To you & Sam", "See you soon")
    assert grouping_key(first) == grouping_key(second)
    assert first.conversation_name == second.conversation_name == "Group with Alex, Sam"
    assert first.sender == "Sam" and second.sender == "Alex"
    assert grouping_key(first) != grouping_key(parse("Sam", "To you & Riley"))
    assert grouping_key(first) != grouping_key(parse("Sam", ""))


@pytest.mark.parametrize(
    "subtitle", ["To you & 2 others", "To you & Alex, Riley", "To you & Alex…", "Family…"]
)
def test_ambiguous_or_clipped_chat_labels_do_not_merge(subtitle):
    first = parse_esp_json(
        json.dumps(_JSON_SAMPLE | {"subtitle": subtitle}), timezone_name=_PACIFIC
    )
    second = parse_esp_json(
        json.dumps(_JSON_SAMPLE | {"subtitle": subtitle, "message": "Different message"}),
        timezone_name=_PACIFIC,
    )
    assert first.conversation_id != second.conversation_id
    assert first.conversation_id.startswith("ancs-unresolved:")


def test_long_group_names_keep_full_identity_without_rejecting_valid_subtitle():
    first = parse_esp_json(
        json.dumps(_JSON_SAMPLE | {"subtitle": "a" * 255 + "b"}), timezone_name=_PACIFIC
    )
    second = parse_esp_json(
        json.dumps(_JSON_SAMPLE | {"subtitle": "a" * 255 + "c"}), timezone_name=_PACIFIC
    )
    assert len(first.conversation_name) <= 120
    assert first.conversation_id != second.conversation_id
