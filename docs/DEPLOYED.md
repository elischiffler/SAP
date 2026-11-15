# Live SAP deployment

Verified November 14, 2026. Dashboard and server: https://sap.elischiffler.dev on the existing shared EC2 host at 52.9.192.172 (us-west-1). The product showcase is separate.

## Current release

- Release: `/srv/sap/releases/781015c55ffcd61e`; active symlink `/srv/sap/current`.
- Image: `sap-pager:781015c55ffcd61e`, Linux AMD64.
- Archive SHA256: `781015c55ffcd61eeaa7f10168a0ad0bdfe7889f23c1162d8f22feff48dd07bf`.
- Source: committed and pushed to [GitHub main](https://github.com/elischiffler/SAP/tree/main)
  before deployment. Release files are checked byte-for-byte against that commit.
- Compose project `sap`; containers `sap-app-1`, `sap-caddy-1`; persistent volume `sap_sap_data`.
- Secrets: `/etc/sap/env.production`, root-owned mode 0600. Do not print expanded Compose configuration.
- Provider-operation cap: **5,000**, with existing usage preserved (44 at verification). This is not a dollar budget.
- Prior Pi deployment: `68b2b04ddfeddbf5`. Prior history deployment: `2460afb7dd171a9a`. Prior original-payload release: `822907784fd32ba4`.

## Clipped notification previews

The reported Discord preview was already ellipsis-ended in the accepted ESP
request, before classification or TTS. Request history redacts secrets/URLs, so
its byte count cannot establish the original BLE capture length. We have not
established whether the running firmware, iOS or Discord supplied the cutoff.

A trailing Unicode ellipsis or three dots now selects a **partial summary**
even when the preview would fit a short source quote. It reuses the existing
classification response and adds `Preview may be incomplete.` The same hint
and an attribution-aware character budget are supplied to single and batch
classification. Prompts forbid completing missing words or inventing the unseen
ending. Invalid, unfinished or oversized summaries use a check-your-phone cue.
Group-member digests preserve the warning for later group summarization.
Complete short messages still use redacted source quotes. Existing audio is
not regenerated, and no previously played notification is replayed.

The hint is deliberately uncertain: writers can use ellipses intentionally.
The ESP source requests 4096 bytes, but the running hardware must be flashed to
use it. Even then, an app-provided shortened preview may remain shortened.
[Apple's ANCS specification](https://developer.apple.com/library/archive/documentation/CoreBluetooth/Reference/AppleNotificationCenterServiceSpecification/Specification/Specification.html)
defines attribute byte limits and response reassembly; the server cannot fetch
unseen Discord content through this notification payload.

327 local tests passed, including the Discord-shaped regression, both ellipsis
forms, classification-call count, batch hints, bounded speech, hidden content,
and warning preservation for groups. Production checks are read-only; no live
notifications are submitted, claimed, downloaded or acknowledged. Previous
release: `f840d2f5fc896093`.

## Phone events and Snapchat typing

Snapchat now uses a strict allowlist: a named sender in `title`, empty `subtitle`,
no group/conversation metadata, visible content, and the exact body `sent you a
chat` is P3 with speech “On Snapchat, [sender] sent you a message.” This matches
the observed individual-chat payload. Group chats observed in production carry
the group name in `subtitle` and are excluded. With only five ESP fields, this
is template recognition, not independent proof of conversation membership.
Unrecognized future formats remain P2 rather than being promoted by the model.
Typing indicators (including the sender-less body `is typing...`) are P1; all
other Snapchat alerts are P2. Both P1 and P2 are discarded without provider calls.
No Snapchat rule produces P4/P5. Other apps retain their existing classification.

Startup reconciles old unsealed, standalone Snapchat queue items using retained
source payloads. Eligible chats get corrected speech and regenerated audio;
ineligible or unrecoverable items are discarded. Sealed deliveries and completed
history are not rewritten. Original accepted payloads remain unchanged. Once
recognized, eligible chats remain valid after the raw history expires.

314 tests passed for this release; lint and JavaScript syntax checks passed.
The prior release was `ad76a8cd6b6b41a3`. Live checks are read-only and compare
the existing queue against the new allowlist without injecting test events or
playing/acknowledging real notifications. Verification:
`artifacts/snapchat-direct-release-verification.json`.

Exact Snapchat typing indicators (`com.toyopagroup.picaboo`, body ending in
`is typing...`/`is typing…`, no additional content) are deterministically priority
1 and discarded before classification/TTS. Invisible Unicode formatting marks
are normalized for detection; original history payloads are preserved. The strict
Snapchat allowlist above supersedes the earlier classifier-based Snapchat policy.

Exact Phone `Incoming Call` and `Missed Call` events are priority 3 and speak
“Incoming call from [caller]” or “Missed call from [caller]”. The caller comes from
sender/title, with an unknown-caller fallback. An incoming event is never renamed
missed without a missed-call event. A uniquely matching pair from the same known
caller is coalesced while unsealed: source timestamps must be ordered within
120 seconds and arrivals within 120 seconds. The five-field ESP payload has no
call ID, so this is a conservative correlation heuristic; ambiguous repeated
calls, unknown callers and already claimed deliveries are not combined. Speech
in progress finishes before its queued audio can be replaced. The final message
is “Missed call from [caller]”, without a group-summary provider call. Both source
event IDs retain retry deduplication and complete together on playback ACK.

Rules apply to new events, not previously played/discarded history. No Pi or ESP
update is needed for these rules. 301 tests passed. Deployment verification uses
read-only requests; no real messages are automatically played or acknowledged.
Previous release: `94e5ea7c3360dff8`. Verification artifact:
`artifacts/call-rules-release-verification.json`.

## Pi download receipts

The Pi delivery panel now displays the speech text, source app/sender and priority
for each retained transfer. It distinguishes audio sent by the server from a WAV
saved and validated by the updated Pi client. Audio responses include
`X-Pi-Transfer-ID`; `POST /api/pi/downloaded` accepts `id`, `transfer_id`, `size`
and `sha256`, verifies the current lease and matching server file, and records a
separate download-confirmation timestamp. It does not play, ACK, remove or renew
the message. The client reports only after full WAV validation and file/directory
fsync. Receipt failure does not produce a false confirmation badge.

Old clients still download/play/ACK but cannot provide this confirmation. Apply
`bridges/pi/update.sh` on the Pi to activate it; production deployment does not
install device code. The Pi was disconnected during this deployment, so live
device confirmation remains pending. Physical speaker output remains unverified.
Message text is joined from the live queue, not copied into transfer history;
it disappears when playback acknowledgment removes that content.

283 local tests passed, including legacy-schema migration, checksum and lease
validation, idempotent download receipts, durable ACK recovery and no ACK after
download failure. A local browser fixture verified the confirmed-download card
and speech text. Production verification used GETs only; no notifications were
injected, downloaded, played or acknowledged. Evidence:
`artifacts/pi-download-receipt-verification.json`. Prior release:
`c7fd271c23e6eeec`. The temporary transaction-consistent migration backup was
removed after successful health and schema verification.

## Priority-5-only LED behavior

`GET /status` now includes boolean `led_on`, independent of its single advertised
audio item. It is true only for priority-5 items pending/preparing/ready/leased,
and false after the last eligible urgent item is removed or acknowledged.
Priority 3/4 playback and one-at-a-time delivery are unchanged. The Pi must adopt
`bridges/pi/led.py` in its polling loop and remove queue-count/connectivity blink
rules; deploying the server cannot modify an existing device's GPIO code.

## Long-message speech

This release reads short previews verbatim after redaction and emoji naming. If the
complete quote (including app/sender introduction) would exceed 350 characters,
it reuses the existing classification summary and says `Summary:`. No extra
model request is made for single-message summarization. Oversized or missing
summaries receive a check-your-phone cue; summaries are never silently cut mid-sentence.
The prompt covers the full received body, including late corrections and deadlines.
Existing generated audio is not regenerated by deployment.

ESP source now requests 4096 UTF-8 bytes, with an 8192-byte response buffer and
UTF-8-safe boundaries. **Hardware must be rebuilt and flashed** to activate this;
EC2 cannot recover content already truncated by old firmware. The updated ESP32-C3
firmware compiled successfully in PlatformIO; it has not been flashed or tested on hardware.

## Access and device handoff

The dashboard, audio and playback controls remain public by the owner's explicit choice. Manual/sample submission is disabled. The Pi adapter shares that public demo access and fixed logical Pi device; it is not authenticated device identity.

ESP ingress remains `POST /api/esp/notifications` with the existing bearer token, available through HTTPS and the explicitly approved temporary HTTP exception. The five JSON fields are app/title/subtitle/message/date; subtitle is optional for older firmware. Source timestamps use America/Los_Angeles. See [ESP setup](ESP.md); ignored `artifacts/esp-device.env` contains device-only connection details.

Pi routes are HTTPS `GET /status`, `GET /audio/<id>`, and `POST /ack`. At most one item is advertised and transferred; one button press handles one item. See [Pi handoff](PI_HANDOFF.md), including the priority-5-only `led_on` flag and Pi GPIO integration instructions. The Pi delivery panel distinguishes recent contact, sending, waiting for acknowledgment, acknowledged completion, interrupted transfer and expiry. No Pi has contacted the adapter at verification; GPIO, actual device code and speaker output remain unverified.

## Request history

History source labels use the shared 92-app mapping. Messages is labeled `Text message / SMS`; the app identifier alone does not distinguish SMS from iMessage. A derived `app_label` is supplied when reading history, including old records. Original `app` metadata and raw payloads remain unchanged; unknown apps retain their identifier.

The right-hand history is independently scrollable. It retains the latest 1,000 records in SQLite, with 50 per page and Newer/Older navigation. Each request keeps its own priority and original accepted payload keys/values, including local ANCS date and Unicode. Generated event IDs and queue status are separate metadata. Secret values are redacted and labeled. Invalid/rejected bodies and authorization headers are excluded.

Payloads expire two hours after server receipt. Cleanup runs at most 30 seconds apart in the worker and immediately on history reads; metadata remains until the record bound. The delivery queue still drops priority 1–2 without TTS and removes played audio/content after ACK. Debug history can retain those original payloads only within the two-hour window. Temporary migration backups and the one-time imported history export were removed after successful verification so they do not retain extra payload copies. Older pre-history payloads/priorities that were already deleted cannot be reconstructed.

## Host operations and verification

Native Caddy terminates TLS and forwards to SAP's loopback port 18080. Other HTTP paths redirect to HTTPS. The app port is private. Host-specific routing is recorded in `deploy/Caddyfile.ec2-site`.

```sh
cd /srv/sap/current
sudo docker compose --env-file /etc/sap/env.production -p sap \
  -f compose.yaml -f deploy/compose.shared-host.yaml -f deploy/compose.release.yaml ps
sudo docker logs --tail 80 sap-app-1
```

Use `/var/lock/hosting-ops-deploy.lock` for shared-host updates and preserve other services/data volumes. The deployment helper verifies the archive and image architecture, waits for health and restores the prior release on startup failure. Back up SQLite before schema changes; remove temporary payload-containing backups after validation.

262 tests passed, including priority-5-only LED status, urgent arrivals behind active lower-priority audio, last-urgent acknowledgment, the GPIO helper and native C++ UTF-8 boundaries. The final deployment was checked read-only: no notifications posted, claimed, played or ACKed. The remaining synthetic queue item was removed by an exact event-ID allowlist; real items were preserved. Roadtrips, Mentro and UMami all returned 200, with their containers not restarted. Current release verification: `artifacts/urgent-led-release-verification.json`. Prior evidence: `artifacts/history-deploy-verification.json`, `artifacts/pi-release-verification.json`, and `artifacts/live-pi-handoff.jpg`.

`main` was fetched before each release and again after deployment; the teammate's ESP32 commit `14b2bd2` was fast-forwarded locally without replacing server work. No Pi firmware implementation was present, only the supplied tech spec. No recurring test sender exists, and live synthetic submissions have stopped.
