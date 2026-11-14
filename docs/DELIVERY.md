> The deployed Pi MVP uses the compatibility routes documented in [PI_HANDOFF.md](PI_HANDOFF.md). They preserve the underlying lease and one-item delivery flow below; ACK success in stub mode does not prove audible playback.

# One-message delivery protocol

The device pulls one ready item when the user presses its playback button. The server never pushes a batch of audio files. The Mac browser exercises this protocol now; a Pi client can later implement the same requests.

A delivery item can represent one notification or a group of up to fifty. A group contains one count-prefixed brief and one WAV. Claiming permanently seals membership; subsequent arrivals form another group. Completion acknowledges and deletes every member atomically. See GROUPING.md for the separate ingress batching policy.

1. POST `/api/delivery/claim` with a stable device ID. If a lease is already active for this device, the server returns it instead of assigning another item. Otherwise it selects priority 5, then 4, then 3, with oldest notification source timestamp first within each tier, using server arrival to break ties. Groups retain the source timestamp of their first-arriving member. Unclassified items do not yet have a priority and cannot block classified work. If the highest-ranked classified item is still summarizing or generating audio, claim returns no delivery until it is ready; lower-ranked ready items cannot overtake it. Explicitly failed items are skipped until retried. Active leases are never interrupted by a new arrival.
2. Download the one audio URL in the lease. Keep one audio buffer/file on the device. Do not ask for another item while holding this lease.
3. Renew the lease every 20 seconds while downloading/playing via its heartbeat endpoint. Default lease duration is 90 seconds. Stop playback if the lease is no longer valid.
4. After the audio finishes, POST an acknowledgment with `outcome: played`. Persist the acknowledgment intent locally until the server confirms it. If the response is lost, retry the same lease acknowledgment; do not replay the audio just because the acknowledgment response was lost.
5. If playback is stopped or fails, send `outcome: retry`. The message becomes available for another explicit button press, subject to the attempt limit. There is no automatic next-message playback.

An item belongs to at most one active lease. A device holds at most one active lease. Claiming is transactional so concurrent requests cannot assign two messages to the same device. Tokens from an expired or superseded lease cannot acknowledge a newer delivery. The server keeps the newest 10,000 opaque acknowledgment receipts and newest 10,000 completed-event IDs to make recent retries idempotent. Older pruned event IDs may be treated as new; lifetime aggregate counters remain accurate.

If the client disappears, the lease expires and the server makes the message eligible again. At most five delivery attempts are allowed by default before the item becomes failed and requires an explicit retry. SQLite persistence preserves queue and lease state across a server restart.

This is an at-least-once delivery system. A crash after sound has played but before the client has durably recorded completion can cause a repeat. Network acknowledgments cannot prove a human heard the message. We reduce duplicates with durable receipts, but do not promise exactly-once sound.

## Resource bounds

- Default maximum of 100 outstanding original content-bearing notifications, including grouped members and queued, leased, and failed work. Reject excess input rather than growing indefinitely.
- One provider worker; no unlimited background-task creation.
- One bounded WAV per item, at most 45 seconds and 5 MB by default.
- 300 provider operations by default, persisted across restart. This is an operation cap, not a dollar billing limit. Raising it is an explicit configuration change.
- Priority-5 metadata can appear while another message is playing. It does not download or start another voice clip.
- Priorities 1–2 are deleted after classification and never enter delivery. Original phone notifications are untouched.

## Local boundary and future deployment

This prototype binds to loopback and accepts same-origin local browser requests. Device IDs and unguessable lease IDs support the delivery state machine but are not a replacement for production device authentication. The EC2 demo setup in EC2.md adds a password-protected HTTPS proxy and keeps the app port private. It is a single shared demo, not per-device authorization or multi-user isolation. Provisioned device credentials remain necessary before broader hardware service use. Do not expose the local app port directly to a network.
