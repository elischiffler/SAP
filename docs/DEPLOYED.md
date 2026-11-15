# Live SAP deployment

Latest recorded deployment verification: November 14, 2026. Dashboard and server: https://sap.elischiffler.dev on the existing shared EC2 host at 52.9.192.172 (us-west-1). The product showcase is separate.

## Latest recorded release

- Release: `/srv/sap/releases/33276bd9c8890736`; active symlink `/srv/sap/current`.
- Image: `sap-pager:33276bd9c8890736`, Linux AMD64.
- Archive SHA256: `33276bd9c8890736312ee18480f487fe5b7e778e0ef9c7b791ea82e39d597101`.
- Source: committed and pushed to [GitHub main](https://github.com/elischiffler/SAP/tree/main)
  before deployment. Release files are checked byte-for-byte against that commit.
- Compose project `sap`; containers `sap-app-1`, `sap-caddy-1`; persistent volume `sap_sap_data`.
- Secrets: `/etc/sap/env.production`, root-owned mode 0600. Do not print expanded Compose configuration.
- Provider-operation cap: **5,000**, with existing usage preserved on restart. This is not a dollar budget; older usage readings below belong to their dated releases.
- Prior Pi deployment: `68b2b04ddfeddbf5`. Prior history deployment: `2460afb7dd171a9a`. Prior original-payload release: `822907784fd32ba4`.

## Urgent content before the remaining-message count

Release `33276bd9c8890736` packages GitHub commit `5c54e3e`. Mixed-priority
speech now leads with the urgent summary, then says "Also, you have N more
messages from [sender]:" before the P3/P4 summary. The count excludes the P5
messages already summarized. Group-chat labels, unknown senders, singular/plural
forms and non-messaging app notifications are handled explicitly. Both sections
still share the 350-character speech budget; all-priority-equal summaries retain
their existing format. Already-generated WAVs are not rewritten.

422 mocked backend tests and lint passed. Application hashes in the running
container match the packaged GitHub revision. An in-memory formatter check in
that container verified the exact new wording without queue writes, audio
playback or provider calls. Health, state, Pi-status, status and dashboard routes
returned HTTP 200. Evidence: `artifacts/mixed-count-release-verification.json`.
Only SAP's app container was recreated; the temporary database backup was
removed after verification. Previous release: `3799107dbad7a4ec`.

## Call priorities and Pi dashboard

Release `3799107dbad7a4ec` packages commit `9eddb4b` from GitHub main. Incoming
calls are discarded at P2 without speech. Missed calls with named caller labels
are P4; numeric, unknown/private and "Maybe:" callers are P3. Names are a proxy
for saved contacts: the ANCS payload has no contacts-membership field. Startup
corrects evidenced, unsealed standalone calls without rewriting claimed deliveries.

The browser Playback panel and Space-key playback shortcut are removed. The Pi
delivery, queue and history lists scroll independently within the viewport; very
short windows retain page scrolling for accessibility. `/status` still returns
`items` (zero or one `{id, priority}`) and `led_on`, which covers any pending P5.

All 419 backend tests passed. The deployed application files match the packaged
GitHub revision; rule checks inside the running container returned P2/P4/P3.
Live health/state/Pi-status routes returned HTTP 200, and desktop/mobile browser
checks passed without playback or acknowledgment requests. Evidence is in
`artifacts/call-priority-release-verification.json`. Only SAP's app container was
recreated. A transaction-consistent backup was taken for the update and removed
after verification. Previous release: `1d8daba4ce8ccc08` (same call fix and Playback
removal, before panel sizing); prior baseline: `893a8c77fa6a5f37`.

## Historical verification snapshot — November 14, 2026

The prior artifact, `artifacts/content-errors-release-verification.json`,
records release `893a8c77fa6a5f37` from commit
`b8d1f50107fc39d53435d68142a8ffba055c7d16` and **409 passing tests**. It records
HTTP 200 for `/healthz`, `/api/state`, `/api/ingress-log` and `/api/pi/status`.
The history response included the new errors field and reported zero content
errors at that check. The local release archive was compared byte-for-byte with
that commit during this documentation update. No new live requests, paid API
calls or hardware tests were performed.

Historical snapshot — also November 14, 2026:
`artifacts/natural-transition-release-verification.json` recorded release
`5afa0b4f793edf6e`, commit `0dbc0de15072464a225c7c81ca6d79001d5f42ca`, GitHub/source
agreement and 387 passing tests. Its health/state/Pi-status checks returned HTTP
200 with valid JSON. That snapshot remains evidence for the earlier release.

The repository now includes a real ALSA Pi client, installer, updater, LED helper,
systemd unit and download-only diagnostic. See [installation/update instructions](../bridges/pi/README.md)
and [the API handoff](PI_HANDOFF.md). A saved-file receipt confirms a reported
validated download; a playback ACK from this client follows successful `aplay`.
Neither independently establishes physically audible sound.

The earlier `94e5ea7c3360dff8` receipt-verification artifact recorded no recent Pi
contact and zero transfers. The latest artifact records endpoint health and history-schema checks,
not current contact/download counts. Do not treat the older disconnected snapshot
as a current device-status claim. GPIO, installed device versions, flashed ESP
firmware and audible speaker output require separate hardware evidence.

The feature notes below retain their original release-specific test counts and
verification scope from November 14, 2026. They are not claims that hardware was
retested with each newer release.

## Unavailable content and sender labels

Release `893a8c77fa6a5f37` adds content-error reporting to request history and
cross-platform sender detection. The original accepted payload is retained under
its existing retention policy. See [content-error behavior](CONTENT_ERRORS.md)
and the 409-test verification snapshot above. Prior release: `5afa0b4f793edf6e`.

## Natural follow-up transition

Mixed-priority debriefs now join the lower-priority complete sentence with
“Also,” instead of “They also said:”. For example: “Also, Eli asked what your
favorite food is.” Speaker names remain available for group conversations.
The prompt discourages redundant reporting clauses. Existing audio is unchanged.
387 mocked local tests passed, including the reported question and multiple
speakers. Prior release: `a0da0f39ed5c5101`. Evidence:
`artifacts/natural-transition-release-verification.json`.

## Mixed-priority summaries

Newly generated mixed P5/P3/P4 group summaries include urgent updates first,
then “Also,” and the lower-priority updates. Both sections have
reserved space within the existing 350-character speech limit. Validation
requires nonempty sections and complete per-tier message-index coverage; it
rejects missing coverage or oversized sections. This checks structure, not
semantic fidelity. Later corrections across tiers remain part of the prompt.
Uniform-priority summaries retain their existing format. Existing generated
or downloaded audio is not rewritten, and played messages are not restored.

385 local tests passed using mocked providers, including four-message mixed
priority coverage, invalid responses, 50-member length bounds, and unchanged
uniform-priority formatting. Prior release: `4bf6aee4618c02c6`.
Production verification is read-only, with no synthetic notifications or audio
playback/acknowledgment. Evidence: `artifacts/mixed-summary-release-verification.json`.

## Urgent P5 speech

P5 solo speech starts “Urgent message from [sender] on [app]” for messaging apps,
or “Urgent notification from [sender] on [app]” for other sources. Without a
known sender it says “Urgent notification on [app]”. P5 groups use “Urgent messages
in [chat] on [app]”, or “Urgent messages from [sender] on [app]” for direct-contact
groups, followed by the count and summary. Unknown group sources use “Urgent
notifications on [app]”. Urgency comes only from P5/max member priority.

P3 and P4 prefixes, classification, grouping, hidden-preview behavior and speech
length limits are unchanged. This affects newly generated speech; in-flight audio
is not rewritten. No queued P5 items were present at pre-deployment inspection.
Previous release: `77cf2931bc3cd6e1`. Verification artifact:
`artifacts/urgent-speech-release-verification.json`.
369 tests passed, including exact P3/P4 wording regression checks, P5 group/source
variants, bounded long-label speech and the TTS delivery pipeline. Production
checks are read-only; no synthetic notifications or automatic playback/ACKs.

## Combine unplayed conversations until delivery

Unclaimed notifications with the same conversation key now combine regardless of
elapsed time, up to 50 original notifications per group. Startup consolidates
existing unsealed queue fragments; ordinary summary/TTS finish callbacks also
consolidate fragments created while provider work was in progress. Groups keep
the earliest canonical queue position and the maximum retained priority, and
regenerate their summary/audio before becoming playable. Different conversations,
unknown identities, Phone-event rules and Snapchat rules remain separate.

The Pi's `/status` polling does not seal a group. Beginning `/audio/<id>` claims
and permanently seals it; the browser's existing claim path seals too. Later
arrivals form a new group, including after interrupted delivery or lease expiry.
The 50-member cap, provider-budget protections and explicit failed-job handling
remain in place. The 60-second configuration now limits raw classification
batching only, with zero still disabling grouping; it no longer expires group
membership. See [grouping behavior](GROUPING.md).

352 tests passed, including hours-apart grouping, startup consolidation, a
51-message split, arrival during TTS, and Pi poll/claim/expiry boundaries.
Previous release: `8bb0d4d797ac63b4`. Production verification uses read-only
requests and metadata checks; no notifications are injected, downloaded, played
or acknowledged. Evidence: `artifacts/unplayed-groups-release-verification.json`.

## Find My separation preference

Routine Find My device-separation reminders are priority 2 by user preference.
The observed numbered `devices were left behind` title and standard two-sentence
body are recognized before classification and discarded without GPT/TTS calls.
The classifier prompt also treats routine separation as passive information;
unknown trackers, theft, danger and concrete urgent consequences remain evaluated
on their own evidence. The rule does not mute the entire Find My app.

On startup, matching unsealed standalone queue items are discarded only when
the original input or retained ESP payload proves the template matches. History
priority becomes 2, the original payload keeps its normal retention window, and
orphaned audio is removed. Sealed/active deliveries and missing evidence are left
alone. All 347 tests passed; live checks submit no synthetic notifications.

## Messages group-chat identity

New ESP Messages notifications use a nonblank named-chat subtitle as the chat
label. The observed unnamed form `To you & <other contact>` combines that contact
with the sender in `title`, producing the same identity when they take turns
speaking. Named and participant-based keys have separate namespaces. The sender
remains attached to each group member; DMs with blank subtitles keep per-contact
grouping. Other applications do not use this Messages-specific interpretation.

Ambiguous, abbreviated or clipped recipient labels stay separate. Label-based
identity cannot distinguish two named chats with identical names; see GROUPING.md.
Raw payloads, retry IDs, existing sealed deliveries, priorities, and first-member
timestamp ordering are preserved. No firmware update is needed for these fields.

## Clipped notification previews

The reported Discord preview was already ellipsis-ended in the accepted ESP
request, before classification or TTS. Request history redacts secrets/URLs, so
its byte count cannot establish the original BLE capture length. We have not
established whether the running firmware, iOS or Discord supplied the cutoff.

A trailing Unicode ellipsis or three dots now selects a **natural summary**
even when the preview would fit a short source quote. It reuses the existing
classification response, without speaking an incomplete-preview warning. An internal
incompleteness hint and attribution-aware character budget are supplied to single and batch
classification. Prompts forbid completing missing words or inventing the unseen
ending. Invalid, unfinished or oversized summaries use a check-your-phone cue.
Group-member digests preserve an internal marker, converted to metadata for group
summarization. The marker is omitted from the text sent for group summarization,
and both single and group prompts tell the model not to announce it.
Complete short messages still use redacted source quotes. Existing audio is
not regenerated, and no previously played notification is replayed.

The hint is deliberately uncertain: writers can use ellipses intentionally.
The ESP source requests 4096 bytes, but the running hardware must be flashed to
use it. Even then, an app-provided shortened preview may remain shortened.
[Apple's ANCS specification](https://developer.apple.com/library/archive/documentation/CoreBluetooth/Reference/AppleNotificationCenterServiceSpecification/Specification/Specification.html)
defines attribute byte limits and response reassembly; the server cannot fetch
unseen Discord content through this notification payload.

328 local tests passed, including the Discord-shaped regression, both ellipsis
forms, classification-call count, batch hints, bounded speech, hidden content,
and internal hint preservation without spoken warnings for groups. Production checks are read-only; no live
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
install device code. At the November 14 receipt release `94e5ea7c3360dff8`,
verification recorded no recent Pi contact and zero transfers. That historical
snapshot did not verify on-device download confirmation or audible speaker output.
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
Priority 3/4 playback and one-at-a-time delivery are unchanged. The implemented
`bridges/pi/client.py` already uses `led.py` and has no queue-count/connectivity
blink rule. Install/update that client on the Pi using its README; deploying the
server cannot modify an existing device's GPIO code.

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
firmware compiled successfully in the November 14 PlatformIO check. That check
verified compilation only; it did not establish which firmware is installed on
the physical ESP or verify hardware operation.

## Access and device handoff

The dashboard, audio and playback controls remain public by the owner's explicit choice. Manual/sample submission is disabled. The Pi adapter shares that public demo access and fixed logical Pi device; it is not authenticated device identity.

ESP ingress remains `POST /api/esp/notifications` with the existing bearer token, available through HTTPS and the explicitly approved temporary HTTP exception. The five JSON fields are app/title/subtitle/message/date; subtitle is optional for older firmware. Source timestamps use America/Los_Angeles. See [ESP setup](ESP.md); ignored `artifacts/esp-device.env` contains device-only connection details.

Pi routes are HTTPS `GET /status`, `GET /audio/<id>`, `POST /api/pi/downloaded` and `POST /ack`. At most one item is advertised and transferred; one button press handles one item. See [Pi handoff](PI_HANDOFF.md) for the implemented client, priority-5-only LED, download receipts, playback acknowledgments and timing limits. The dashboard distinguishes recent contact, sending, saved-file confirmation, playback acknowledgment, interruption and expiry. These states are software reports; see the verification snapshot above for the limits of recorded hardware evidence.

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

Historical LED-release verification — November 14, 2026, release `af0a6d1a3fb5b8a8`: 262 tests passed, including priority-5-only LED status, urgent arrivals behind active lower-priority audio, last-urgent acknowledgment, the GPIO helper and native C++ UTF-8 boundaries. That LED deployment was checked read-only: no notifications posted, claimed, played or ACKed. During the earlier history cleanup on November 14, the remaining identified synthetic queue item was removed by an exact event-ID allowlist; real items were preserved. Roadtrips, Mentro and UMami all returned 200, with their containers not restarted. Historical LED-release evidence: `artifacts/urgent-led-release-verification.json`. Prior evidence: `artifacts/history-deploy-verification.json`, `artifacts/pi-release-verification.json`, and `artifacts/live-pi-handoff.jpg`.

Historical integration note — November 14, 2026: when ESP32 commit `14b2bd2` was first integrated, only the supplied Pi spec was available. The implemented Pi client was subsequently committed in `97d1314`; the earlier absence of device code is not a current limitation. Historical sample smoke runs are recorded in VERIFICATION.md. Routine subsequent verification uses mocks and read-only checks, without live synthetic submissions or consumption of real queued messages.
