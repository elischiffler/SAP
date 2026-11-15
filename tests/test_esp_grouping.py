"""Group identity derived from the Messages wire labels reaches the real queue."""

import json

import pytest

from contracts import ClassificationResult, Settings
from contracts.esp import parse_esp_json
from server.store import QueueStore


def notification(sender, subtitle, message, date="20261114T150000"):
    return parse_esp_json(
        json.dumps(
            {
                "app": "com.apple.MobileSMS",
                "title": sender,
                "subtitle": subtitle,
                "message": message,
                "date": date,
            }
        ),
        timezone_name="America/Los_Angeles",
    )


@pytest.mark.parametrize("subtitles", [("Team", "Team"), ("To you & Alex", "To you & Sam")])
def test_group_keeps_speakers_max_priority_and_first_timestamp(tmp_path, subtitles):
    store = QueueStore(Settings(_env_file=None, data_dir=tmp_path, grouping_delay_seconds=0))
    store.initialize()
    first = notification("Sam", subtitles[0], "Please bring the demo")
    second = notification("Alex", subtitles[1], "We need it now", "20261114T145900")
    for item, priority in ((first, 3), (second, 5)):
        store.enqueue(item)
        with store.transaction() as connection:
            connection.execute(
                "UPDATE messages SET status='processing' WHERE id=?", (str(item.event_id),)
            )
        store.finish_classification(
            str(item.event_id),
            ClassificationResult(
                priority=priority,
                reason="Offline fixture",
                spoken_text=item.body,
                evidence="sufficient",
                deadline_at=None,
            ),
        )
    state = store.snapshot()
    assert len(state["items"]) == 1
    assert state["items"][0]["priority"] == 5
    assert state["items"][0]["received_at"] == first.received_at.isoformat()
    group = store.group_for_summary(str(first.event_id))
    assert {m.sender for m in group.members} == {"Sam", "Alex"}
    assert group.sender == first.conversation_name


def test_batch_matches_chat_across_senders_and_excludes_direct_messages(tmp_path):
    store = QueueStore(Settings(_env_file=None, data_dir=tmp_path))
    store.initialize()
    items = [
        notification("Sam", "Team", "Bring the demo"),
        notification("Alex", "Team", "I'll bring it"),
        notification("Sam", "", "Dinner tonight?"),
        notification("Sam", "Family", "See you tonight"),
    ]
    for item in items:
        store.enqueue(item)
    first = store.reserve_job()
    assert first["id"] == str(items[0].event_id)
    batch = store.reserve_classification_batch(first["id"], 10)
    assert {row["id"] for row in batch} == {str(item.event_id) for item in items[:2]}
