# Local verification — November 14, 2026

## Messages chat labels — grouping fix

Release `208b0dcc32963216` derives Messages conversation identity from named-chat
subtitles or the observed unnamed `To you & <other contact>` form plus its sender.
Tests verify cross-sender merging, DM/chat separation, unsupported-app isolation,
long names, ambiguous/clipped label isolation, shared classification batching,
preserved individual senders, maximum member priority and first-member timestamp.
All 338 tests passed. Existing wire fields are retained. Production verification is read-only and no
synthetic notifications are submitted to the live queue.

## Clipped previews — regression fix

Release `23424c7288bbe333` summarizes ellipsis-ended previews using the existing
classification response, even below the normal 350-character spoken threshold.
The actual reported Discord request already contained a shortened preview;
missing text cannot be recovered server-side. No raw user payload was added to
fixtures: tests use the supplied public message text and synthetic source labels.

All **328 tests passed**. Regression coverage includes Unicode/ASCII ellipses,
internal ellipses remaining verbatim, long sender labels, complete-summary fallback,
one single/batch classifier request, and incompleteness kept as internal metadata
while TTS receives a natural summary without a warning. Group-provider tests verify
the internal marker is separated from the spoken summary. Ruff passes on changed Python files.
The release preserves main's Pi download receipts and device-event rules.

## Priority-5-only LED — deployed

Release `af0a6d1a3fb5b8a8` adds `led_on` to Pi status without changing its single
transfer item. Tests cover empty/P3/P4 queues, multiple P5 items, failed/valid
acknowledgments, and an urgent arrival behind a lower-priority active lease.
The GPIO helper rejects malformed flags and turns off on failed polls; it has
no queue-count or network-error blink mode. All **262 tests passed**, plus Ruff
and diff checks. Device GPIO behavior requires installing the helper in the
teammate's actual Pi client; that client is not present here.

## Long-message summaries — deployed

Release `375315b179ac88f8` reuses classification summaries when a formatted single
preview exceeds 350 characters, retaining short source quotes. It labels summaries
and does not truncate them mid-sentence. Prompts preserve late corrections, deadlines,
negations and actionable details. There is no added model request. All 259 suite tests
passed; 59 targeted tests then passed, including a new C++ UTF-8 boundary regression.
Mocked tests verify exactly one classification, source-text thresholds, redaction,
summary fallback and the batch response reaching speech with the critical late fact.

Read-only production checks returned 200 for SAP and all three other applications;
other application containers were not restarted. Installed formatter/prompt SHA256
hashes match local files. Provider usage stayed 44/5000. No live notifications were
submitted, claimed, downloaded or ACKed. See `artifacts/long-message-release-verification.json`.
Firmware source raises capture from 200 to 4096 bytes with bounded reassembly and
static callback scratch. PlatformIO successfully built the Seeed XIAO ESP32-C3 target
with Arduino 3.3.12 and NimBLE 2.5.2. Reported static RAM was 74,108 bytes
(22.6%) and application flash 1,283,429 bytes (40.8%). Runtime BLE/Wi-Fi heap
usage and physical receipt remain unverified; hardware still requires flashing.

## Pi handoff, persistent history, retention and app labels — deployed

The first requested release `2460afb7dd171a9a` added persistent per-request history and the right-hand panel; 244 tests passed. The exact synthetic event `7f9540bb-4bd6-4fc9-99bc-95e0a1c77bb2` was removed and all real queue IDs were preserved. One existing real history record was imported; previously removed payloads/priorities were not invented.

The second release `68b2b04ddfeddbf5` includes Pi status/audio/ACK adaptation, one-item ordering and lease ownership, idempotent ACK, interrupted-download tracking, expiry/retry, the Pi delivery panel, two-hour history payload expiry, independent history scrolling, removal of four queue statistic tiles, 92 verified app labels and a 5,000 provider-call cap. SQLite writes are serialized within the process to avoid transient lock contention during admission bursts. **254 tests passed**, including the existing 50-message batching scenario, plus lint and JavaScript checks.

All deployment verification was read-only. Provider usage remained 44 while the cap changed from 300 to 5,000. No live synthetic messages were submitted or real items claimed/downloaded/ACKed. Installed Pi routes were verified through the server route table, while isolated fake-provider tests exercised the Pi flow. Browser verification confirmed the right-side history, Pi panel, removed stats and 44/5000 usage. Pi contact and physical audio remain unverified; the UI says Waiting for Pi. All three existing app health endpoints remained 200 and their containers were not restarted. `main` remained at teammate commit `14b2bd2`, integrated locally. Current evidence and release identity are in DEPLOYED.md.

## Deployed: original ESP request payloads

Release `822907784fd32ba4` is live. All **242 tests passed**, including original JSON key/value preservation, absent subtitle handling, UTF-8 and escaped JSON emoji, untouched local dates, secret redaction, and content removal after discard, playback, and completed-event retries for JSON and text ingestion. Internal normalization and speech emoji expansion remain unchanged. The frontend renders the received payload through textContent, without a canonical-field whitelist. Cache-control and a versioned script URL prevent stale rendering after updates.

Live HTTP/HTTPS submissions returned 202 for one event ID and created one ready item. The API and expanded browser disclosure showed exactly the sent five fields, including the emoji character and compact local date. Roadtrips, Mentro, and UMami health checks remained 200 and their containers were not restarted. Evidence: `artifacts/original-payload-release-verification.json` and `artifacts/live-original-payload.jpg`. Archive SHA256: `822907784fd32ba4737a9991605ed7ccbe9610c53bcf0eb141df0b5213bf765f`.

Two one-time synthetic “SAP wire payload check” events were sent during this correction, each posted over HTTP and HTTPS with a shared retry UUID. No recurring notification sender or automation was created. Dashboard polling only reads state/logs. No further test submissions are planned for this completed task.

## Deployed: device-only dashboard, emoji, and subtitle

All **235 tests passed**. Ruff, JavaScript syntax, dependency consistency, and diff checks passed. The local server was restarted after confirming no waiting or leased notifications, and browser inspection verified playback, queue, incoming logs, and the connected status without the header, hero copy, or submission controls. The production app no longer registers manual `/api/notifications` ingestion; authenticated ESP ingress remains available. The canonical test adapter is enabled only by an explicit Python argument in isolated local tests and cannot be enabled in production.

The optional ESP JSON `subtitle` is a strictly validated string up to 256 characters, preserved in classification and sanitized request logs and included in speech. Legacy packets without it remain valid and retain their deduplication identity. Tests cover invalid subtitle types/length, retry identity, raw UTF-8 and escaped JSON emoji through ESP ingestion to speech, compound emoji names, bounded speech, hidden-content handling, and disabled manual ingestion. English emoji names use the pinned `emoji` package without additional provider calls. No original emoji can be recovered from a literal `z` already sent by firmware; the live log had no retained payloads when inspected, so the reported occurrence could not be diagnosed.

Prepared archive: `artifacts/sap-release-device-only-emoji-subtitle.tar.gz`, SHA256 `63d5d3573e63898619be3219718c9d028d08256e6ca38c7f81a6619b72833ec6`. **Deployed to EC2** as `/srv/sap/releases/63d5d3573e638986`. Live HTTP and HTTPS POSTs returned 202 for one shared UUID, producing exactly one ready priority-3 notification with subtitle and emoji names in speech and logs. Missing tokens returned 401, invalid subtitles 422, and manual submission 405. Browser refresh confirmed the simplified layout. All three existing backend health endpoints remained 200, and their containers were not restarted. See `artifacts/device-only-release-verification.json`. Existing rendered audio keeps its previous wording.

## Validated request payloads and shared HTTP/HTTPS queue

Deployed release `b2d82b4aff72557a`. All **223 tests passed**, including payload removal after discard/playback and duplicate request handling. The incoming request log now shows expandable, sanitized validated payloads and current queue status. Rejected requests do not retain bodies; discarded and played notification payloads are removed.

Live HTTP and HTTPS POSTs using the same synthetic event ID both returned 202 and produced exactly one priority-3 ready queue item. Both request entries displayed the validated payload and preserved source timestamp. Browser verification confirmed the live payload display. Roadtrips, Mentro, and UMami health endpoints remained 200. Evidence is saved in `artifacts/payload-log-verification.json` and `artifacts/live-payload-log.jpg`. This verifies server ingestion and processing, not physical ESP/Pi operation.

## Public dashboard, ingress log, and temporary HTTP ESP access

The owner approved public dashboard/control/submission access and HTTP ESP ingestion. Deployed release `ce643ea25c9573d2` removes Basic authentication, retains ESP token enforcement, and adds a bounded metadata-only request log. All 221 tests passed. Live HTTP and HTTPS submissions returned 202 for the same UUID without a second notification; missing tokens returned 401, invalid fields returned 422, and other HTTP routes still redirect to HTTPS. Browser verification confirmed public access and the request log. The existing three backend health endpoints remained 200. Earlier private-access checks below describe previous revisions.

## Live EC2 deployment — November 14, 2026

SAP is live at https://sap.elischiffler.dev. The paid HTTPS JSON ingestion → GPT → Alloy → delivery/audio smoke passed using two provider operations. Duplicate admission, timestamp preservation, authentication, stable lease, heartbeat, and retry-to-ready passed. Roadtrips, Mentro, and UMami health endpoints remained 200, with their containers untouched. Disk has 9.9 GiB free after authorized build-cache cleanup and deployment. See [the deployed runbook](DEPLOYED.md) for exact release identity, commands, and remaining hardware validation. Earlier pending-deployment notes below are historical.

## ESP JSON and shared EC2 host

All **218 tests passed** after adding JSON input to `POST /api/esp/notifications`. The adapter accepts both the JSON wire format and legacy text packets. The running local server returned 200 for health and 422 for authenticated malformed JSON. The invalid request made no provider calls.

Two independently generated release archives matched byte for byte. The archive contains the app, message frontend, pinned dependencies, and deployment configuration. The build from that archive produced a Linux AMD64 image that Docker reported as 68,403,721 bytes. An isolated local container verified non-root startup, read-only root filesystem, Pacific timezone data, health and frontend HTTP 200, missing ESP authentication HTTP 401, authenticated malformed JSON HTTP 422, and HTTP 404 for the environment file and showcase routes. The provider operation counter remained at zero.

`sap.elischiffler.dev` resolves to `52.9.192.172`. AWS Systems Manager confirmed the shared EC2 host is an AMD64 Ubuntu 24.04 instance with Docker 29.8.1, Compose 5.5.1, and an existing native Caddy installation on ports 80 and 443. The host had 2.1 GB free with 93% disk usage and 2.2 GB of unused Docker build cache. No cache was removed. The release transfer still awaits SSH access, and no live EC2 deployment has occurred.

## Current input: ESP packets and source timestamps

The general NotificationInput contract now has a validated raw ESP adapter at POST /api/esp/notifications. All **196 tests passed**. Coverage includes raw body pipes/Unicode/line endings, bounds, leap dates, DST gaps/folds, idempotent raw retries and explicit IDs, authenticated ingestion, malformed request errors, source timestamp ordering, and legacy timestamp migration. Priority remains the first sort; source timestamp is now second. Groups keep the source timestamp of their first-arriving member. Server arrival remains separately recorded.

Local ARM64 Docker/Caddy checks confirmed exact POST ESP routing, missing/wrong bearer rejection, browser Basic protection, bearer-only denial of queue access, duplicate event ID handling, 32 KiB limits, and source-time preservation with zero provider calls. The UI displays received_at in browser-local time. The local server was restarted and returned health 200, missing ESP token 401, authenticated invalid packet 422 without submitting any notification. EC2 target is the existing shared-backends instance at 52.9.192.172 (us-west-1, i-0e5eaff1af2445aba). A local recovery SSH key was found, but port 22 currently times out before authentication. AWS console sign-in requires user MFA. No live EC2 deployment has occurred; the shared host already serves other backends and its existing proxy must be preserved. The user confirmed the source iPhone uses Pacific time, so ESP_TIMEZONE=America/Los_Angeles is confirmed.

## Current ordering: priority first, timestamp second

The latest user decision supersedes the FIFO-only revision below. Waiting items now sort by priority descending (5, 4, 3), then oldest server arrival within each tier. Groups retain the first member's timestamp even when promoted. The highest-ranked classified item holds its place while preparing audio; unclassified items do not yet have a tier. Active playback is unchanged by higher-priority arrivals. All **151 tests passed**, including priority-4 precedence, same-priority chronology, group promotion, pending-audio ordering, and active-lease stability. The local server was restarted with this revision.

## Follow-up: FIFO delivery with priority-5 exception

Current full suite: **149 passed**. Added ordering regressions for priority 3 before later priority 4, group first-arrival position across new members, earlier unclassified/rebuilding items holding their place, urgent items bypassing older ordinary work, and an active lease staying unchanged when priority 5 arrives. Failed items do not block the buffer. Source-supplied timestamps cannot reorder server arrival order. Ruff and JavaScript syntax checks passed. The local server was restarted with the updated ordering.

## Follow-up: Alloy, groups, batching, and EC2

Current full suite: **143 passed**. Ruff lint/format, JavaScript syntax, and diff checks passed. Added group matching, frozen leases, membership/count deletion, batch index validation, 50-message batching, digest fidelity at the end of long inputs, provider reservation/fairness, bounded history migration, production configuration/Host/HTTPS checks, background database access, and worker health/recovery tests.

The fifty-message injected-provider integration produced five classification batches of ten, one summary, and one WAV (seven operations). This is a simulated burst, not a live model-quality evaluation. In the actual browser/server test, three iMessage samples became one group using exactly three hosted operations: one batch classification, one summary, one Alloy TTS. The generated brief preserved dinner tomorrow at 7, the seat-confirmation request, and the Pine Street entrance instead of the lobby. Browser playback completed, and one ACK raised played notifications from 13 to 16 and removed the group. No automatic next playback occurred.

`python -m scripts.check_load` ran an isolated 64-request HTTP burst with queue limit eight and Uvicorn concurrency 32. Observed: eight accepted (202), thirteen queue-limit rejections (429), forty-three concurrency rejections (503), eight retained, and healthy after the burst in 0.14 seconds. No provider requests were made. This measures local admission/backpressure, not sustained EC2 throughput or inference latency.

Docker verification used Linux ARM64 locally: built from the lockfile, production startup/health with zero provider budget, nonroot user, read-only app and writable data, HTTPS redirect/auth, origin checks, 32 KiB proxy body rejection, no public app port, and outbound OpenAI connectivity. The final image was rebuilt and fresh startup/health retested after integration. Real EC2 sizing, public DNS/ACME certificate issuance, Internet load, and physical hardware remain unverified. All temporary deployment test containers and volumes were removed; no EC2 resources were created.

## Earlier follow-up: speech format, voice selection, Bluetooth probe

The suite now passes 77 tests. Added source-based quotation/hidden-preview/redaction checks, per-item voice validation and restart recovery, old-database migration, and SDK wire checks for voice isolation. Ruff, JavaScript syntax, and diff checks passed. Browser verification against the running server selected Sage and submitted a synthetic iMessage from Sam; real GPT classification and hosted TTS completed, and the queue displayed `New message on iMessage from Sam: 'Want dinner tonight?'`. It remains ready for button playback. Voice switching and retry-payload behavior were also tested in Chrome against a mock server.

The native Bluetooth diagnostic compiled with Swift 6 and passed offline fragmented/malformed ANCS parser tests. An actual 15-second ANCS scan found no matching advertised or connected service. Real iPhone capture remains unverified; see MAC_BLUETOOTH.md for the public-API limitation and experimental commands.

## Automated checks

48 tests passed with `.venv/bin/python -m pytest -q`. Ruff lint and formatting checks passed for contracts, server, intelligence, and tests. `node --check web/app.js`, `git diff --check`, and `pip check` also passed.

Coverage includes:

- Strict priority and input validation, required timezone information, unexpected fields, body-size limits, and local Host/Origin rules.
- OpenAI SDK wire-format tests for schema-constrained classification, separation of untrusted notification content, refusal/timeout/invalid responses, and no automatic provider retry.
- Hidden-content behavior, the five explicitly labeled offline fixtures, common speech-secret redaction, complete/bounded WAV validation, and real macOS `say` synthesis.
- Deletion of priorities 1–2 from SQLite and absence of speech calls for them; priority-5 alert metadata before audio is ready.
- Simultaneous claims, one active item per device, wrong-device access, lost/duplicate/contradictory acknowledgments, expired leases, heartbeat renewal, and retry exhaustion.
- Restart recovery, durable operation accounting, queue capacity, invalid audio/manual retry, missing leased audio, interrupted speech-directory cleanup, and retryable audio deletion after an ACK.

The interface worker separately tested Chrome and WebKit against a contract-matching temporary server: submit payloads without priority overrides, priority-5 alert without speech, cross-tab locking, cancellation, WAV completion, and lost ACK response recovery after reload. Chrome regression checks also covered final-attempt failures and missing audio.

## Live integration

Used the configured key without logging or exposing it. Model availability was confirmed through the API. A direct synthetic personal-message check returned priority 3 in 4.26 seconds and produced a 5.1-second, mono, 24 kHz WAV in 1.29 seconds. These are single observed samples, not latency guarantees.

The actual local browser → FastAPI → GPT → hosted speech flow processed all five UI samples. Results were priorities 1, 2, 3, 4, and 5 respectively. The two discarded samples left only opaque completed-event records and a count; their content was absent from stored message rows. Only three WAVs were generated.

The browser showed the priority-5 alert while waiting for the user. One Play press played P5; the browser reached the audio-ended path and acknowledged it. The server removed its audio/content and left P4/P3 queued. Another Play then Stop released P4 for retry. The server was gracefully stopped and restarted with the final implementation: the remaining queue and eight-operation count survived. After reloading the browser, a Play press completed P4 using its existing WAV. P3 remained ready afterward; there was no automatic next playback.

At handoff, the local queue contains one synthetic P3 example ready for the user. Two examples have completed playback, two have been discarded, and no item is leased or failed. The app's durable operation counter is eight. The separate direct provider smoke test used two additional API operations outside this app counter. No dollar billing estimate or balance check is claimed.

Static route checks: `/healthz`, `/`, and `/showcase/` returned 200; `/.env` returned 404. Showcase visual/content QA belongs to its separate chat. The Mac demo screenshot is in ignored `artifacts/mac-pager.jpg`.

## Boundaries

This verifies sample/manual input and software playback on the Mac. It does not prove real iPhone capture, physical Pi output, Bluetooth stability, EC2 readiness, or emergency-detection reliability. Twelve held-out classification cases were added under `evals/`; they have been schema-checked but not scored against the live model. General classification quality needs broader evaluation.

The implementation is local and single-process. Device IDs/lease IDs support delivery isolation but are not production authentication. Completed IDs/ACK receipts persist for deduplication; bounded retention/compaction remains a follow-up. Real notification updates/removals and revision handling await hardware integration. Audio delivery is at-least-once: a crash at the playback/ack boundary can still produce a repeat.
