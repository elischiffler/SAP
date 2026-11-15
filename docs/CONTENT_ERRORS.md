# Unavailable content and sender labels

Insufficient-evidence classification is a terminal processing failure: request
history shows Failed and a sanitized explanation, and the notification does not
enter grouping, TTS, the dashboard queue, or Pi delivery. HTTP 202 still means
that ingestion was accepted; the later classification error is separate.
Opaque completion IDs prevent transport retries from resurrecting the item.
Accepted payload history retains its existing redaction and two-hour expiry.

Startup removes recognizable unsealed standalone legacy unavailable cues and
cleans their saved audio. Claimed/sealed deliveries are preserved.

ESP title-to-sender detection covers recognized messaging, social, mail, and
calling applications. Generic app titles, notification counts and channel labels
are excluded. Explicit `From ...` labels work on unknown applications too.
Unknown layouts cannot reliably identify a sender and retain an unknown sender.
Raw title, subtitle and body are preserved. Inferred sender names are display
labels, not authenticated identities. Newly recognized senders do not cause
separate platform conversations to merge. Existing Messages grouping and
Snapchat filtering remain unchanged.

409 local mocked tests pass, including terminal errors, history after restart,
retry deduplication, legacy cleanup versus sealed audio, sender detection across
14 communication apps, and generic-title rejection. JavaScript syntax and Python
lint checks pass. Production verification uses read-only requests.
