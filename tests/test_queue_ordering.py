from uuid import uuid4

import pytest

from contracts import ClassificationResult, NotificationInput, Settings
from server.store import QueueStore


@pytest.fixture
def queue(tmp_path):
    store = QueueStore(Settings(_env_file=None, data_dir=tmp_path, grouping_delay_seconds=0))
    store.initialize()
    return store


def add(queue, priority=None, *, sender=None, ready=True, received_at=None):
    fields = {"app": "Messages", "sender": sender or str(uuid4()), "body": "Synthetic message"}
    if received_at:
        fields["received_at"] = received_at
    item = NotificationInput(**fields)
    event_id = str(item.event_id)
    queue.enqueue(item)
    if priority is None:
        return event_id
    with queue.transaction() as connection:
        connection.execute("UPDATE messages SET status = 'processing' WHERE id = ?", (event_id,))
    queue.finish_classification(
        event_id,
        ClassificationResult(
            priority=priority,
            reason="Synthetic test decision",
            spoken_text="Synthetic speech",
            evidence="sufficient",
            deadline_at=None,
        ),
    )
    with queue.transaction() as connection:
        group_id = connection.execute(
            "SELECT group_id FROM group_members WHERE event_id = ?", (event_id,)
        ).fetchone()[0]
    if ready:
        queue.finish_summary(group_id, "Synthetic group speech")
        queue.audio_path(group_id).write_bytes(b"test-audio")
        queue.finish_speech(group_id)
    return group_id


def play_next(queue):
    delivery = queue.claim("pager")
    assert delivery is not None
    queue.acknowledge(delivery["lease_id"], "pager", "played")
    return delivery["message_id"]


def test_priority_descending_then_source_arrival_order_within_each_tier(queue):
    early_three = add(queue, 3, received_at="2026-11-14T23:00:00Z")
    later_four = add(queue, 4, received_at="2026-11-14T22:00:00Z")
    last_three = add(queue, 3, received_at="2026-11-14T23:15:00Z")
    last_four = add(queue, 4, received_at="2026-11-14T21:00:00Z")
    urgent_first = add(queue, 5)
    urgent_second = add(queue, 5)
    expected = [urgent_first, urgent_second, last_four, later_four, early_three, last_three]
    assert [item["id"] for item in queue.snapshot()["items"]] == expected
    assert [play_next(queue) for _ in expected] == expected


def test_new_member_keeps_first_ingested_groups_source_timestamp(queue):
    first_group = add(queue, 3, sender="Sam", received_at="2026-11-14T21:00:00Z")
    unrelated = add(queue, 4, sender="Alex", received_at="2026-11-14T20:00:00Z")
    assert add(queue, 4, sender="Sam", received_at="2026-11-14T19:00:00Z") == first_group
    items = queue.snapshot()["items"]
    assert [item["id"] for item in items] == [unrelated, first_group]
    assert items[1]["notification_count"] == 2
    assert items[1]["received_at"] == "2026-11-14T21:00:00+00:00"
    assert play_next(queue) == unrelated
    lease = queue.claim("pager")
    assert lease["message_id"] == first_group
    assert lease["received_at"] == items[1]["received_at"]
    queue.acknowledge(lease["lease_id"], "pager", "played")
    assert queue.snapshot()["counts"]["played"] == 3


def test_unclassified_message_has_no_priority_and_does_not_block_ranked_audio(queue):
    earlier = add(queue)
    later = add(queue, 4)
    assert play_next(queue) == later
    assert queue.claim("pager") is None
    assert queue.snapshot()["items"][0]["id"] == earlier


def test_pending_urgent_audio_blocks_normal_but_bypasses_older_unknown(queue):
    unknown = add(queue)
    normal = add(queue, 4)
    urgent = add(queue, 5, ready=False)
    assert queue.claim("pager") is None
    queue.audio_path(urgent).write_bytes(b"test-audio")
    queue.finish_speech(urgent)
    assert play_next(queue) == urgent
    assert play_next(queue) == normal
    assert queue.claim("pager") is None
    assert queue.snapshot()["items"][0]["id"] == unknown


def test_priority_five_does_not_interrupt_an_existing_lease(queue):
    active = add(queue, 3)
    lease = queue.claim("pager")
    assert lease["message_id"] == active
    normal = add(queue, 4)
    assert queue.claim("pager") == lease
    urgent = add(queue, 5)
    assert queue.claim("pager") == lease
    queue.acknowledge(lease["lease_id"], "pager", "played")
    assert play_next(queue) == urgent
    assert play_next(queue) == normal


def test_rebuilding_earliest_group_blocks_later_ready_audio(queue):
    group = add(queue, 3, sender="Sam")
    later = add(queue, 3, sender="Alex")
    assert add(queue, 3, sender="Sam", ready=False) == group
    assert queue.claim("pager") is None
    queue.finish_summary(group, "Two notifications from Sam")
    queue.audio_path(group).write_bytes(b"test-audio")
    queue.finish_speech(group)
    assert play_next(queue) == group
    assert play_next(queue) == later


def test_pending_priority_four_holds_position_ahead_of_ready_priority_three(queue):
    low = add(queue, 3)
    high = add(queue, 4, ready=False)
    assert queue.claim("pager") is None
    queue.audio_path(high).write_bytes(b"test-audio")
    queue.finish_speech(high)
    assert play_next(queue) == high
    assert play_next(queue) == low


def test_pending_lower_priority_does_not_block_ready_higher_priority(queue):
    low = add(queue, 3, ready=False)
    high = add(queue, 4)
    assert play_next(queue) == high
    assert queue.claim("pager") is None
    queue.fail_job(low, "speech_unavailable")
    later = add(queue, 3)
    assert play_next(queue) == later


def test_equal_source_times_preserve_server_arrival_order(queue):
    shared_time = "2026-11-14T20:56:41Z"
    first = add(queue, 4, received_at=shared_time)
    second = add(queue, 4, received_at=shared_time)
    assert [play_next(queue), play_next(queue)] == [first, second]


def test_legacy_group_migration_preserves_root_source_timestamp(queue):
    root_id = add(queue, 3, sender="Sam", received_at="2026-11-14T20:56:41Z")
    assert add(queue, 4, sender="Sam", received_at="2026-11-14T20:30:00Z") == root_id
    with queue.transaction() as connection:
        connection.execute("DROP INDEX messages_delivery_order")
        connection.execute("ALTER TABLE messages DROP COLUMN received_at")

    queue.initialize()
    queue.initialize()
    lease = queue.claim("pager")
    assert lease["message_id"] == root_id
    assert lease["notification_count"] == 2
    assert lease["received_at"] == "2026-11-14T20:56:41+00:00"
