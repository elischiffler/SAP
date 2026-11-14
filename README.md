# SAP — Simplified Abstraction of a Phone

A button-operated audio pager that lets important iPhone notifications reach you without opening your phone.

The local version runs a validated FastAPI server, GPT notification classification, hosted or macOS text-to-speech, and a browser interface that plays through your Mac. Input can be sample/manual notification data or validated ESP32 packets. Physical Pi playback and live EC2 deployment still require hardware/host integration.

- [One-message delivery protocol](docs/DELIVERY.md)
- [Mac Bluetooth capture experiment](docs/MAC_BLUETOOTH.md)
- [ESP32 packet and connection guide](docs/ESP.md)
- [Grouped notifications and usage](docs/GROUPING.md)
- [EC2 deployment runbook](docs/EC2.md)
- [Implemented local API contract](docs/LOCAL_CONTRACT.md)
- [Architecture and delivery plan](docs/PLAN.md)
- [Notification classification prompt](prompts/classify-notification.md)
- [Subagent work packages and demo page](docs/WORKSTREAMS.md)

## Run locally

Requires Python 3.11+; developed and tested on this Mac with Python 3.14. The setup has already been installed in `.venv` for this workspace. To recreate it:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
```

Put `OPENAI_API_KEY` in `.env` (already configured in this workspace). `.env` is ignored by Git; `.env.example` lists optional settings and contains no secret.

```sh
./scripts/run_local.sh
```

Open [the Mac pager](http://127.0.0.1:8000). Keep one server worker. The server binds only to the local machine. The separate product showcase is at [/showcase/](http://127.0.0.1:8000/showcase/).

1. Send a notification through the authenticated ESP endpoint. The dashboard only monitors the queue and controls playback; manual/sample submission is removed.
2. Wait for classification and audio generation. Priorities 1–2 disappear, increasing only the discarded count.
3. Press **Play next** or Space outside a form field. Waiting messages/groups are ordered by priority (5, then 4, then 3), then oldest notification source timestamp within each priority. A group uses the source timestamp of its first-arriving member. Server arrival order breaks ties. If the highest-ranked item is still preparing audio, it holds its place.
4. Press **Stop playback** to release that item for a later attempt. Nothing plays automatically after a message ends.

Priority 5 displays an alert before audio is ready. Enable the alert chime when prompted; browser audio policies require a gesture. Speech always requires Play. Multiple tabs share a playback lock; supported Chrome/Safari browsers provide Web Locks. Pending playback acknowledgments are kept as opaque lease receipts in local browser storage so a lost response does not automatically replay the message.

## Spoken notification format

Newly processed messages use a server-enforced format:

> New message on iMessage from Sam: 'Want dinner tonight?'

Other app notifications begin with “New notification”. GPT determines priority; the server builds the spoken text from the supplied app, sender, and original message preview. It does not present a model paraphrase as a direct quote. Common credential patterns are redacted, whitespace is normalized, and previews exceeding the 350-character speech limit include an explicit shortening notice. Hidden or insufficient content gets an unavailable-content cue. Missing contacts are never invented. Apple’s Messages app is labeled “Messages” unless the input explicitly identifies iMessage; the app can also carry SMS.

Already queued audio keeps its original wording. Send a new ESP notification to hear the new format.

New hosted audio uses **Alloy**. The voice picker and per-notification overrides have been removed. Previously rendered audio stays unchanged until played; no active delivery is rewritten.

## Grouped conversations

Send related messages from the ESP to exercise grouping. A short collection window batches up to ten messages into one classification request. Each still gets its own importance decision; priorities 1–2 are deleted. Up to fifty retained messages can share one count-prefixed summary, for example “3 notifications on iMessage from Dinner plans: Sam asks you to confirm dinner at 7 and use the Pine Street entrance.”

Grouping matches app plus conversation ID when provided, otherwise sender ID or sender label. Unknown contacts are kept separate. Expand **Conversation details** to test a group chat with different senders but the same conversation ID. Groups use a sixty-second admission window and a two-second quiet delay; priority 5 skips the quiet delay. Claimed groups are permanently frozen, so new messages never alter audio in use. See [grouping details and limitations](docs/GROUPING.md).

## ESP32 input

Use one general `NotificationInput` for all apps. The ESP adapter accepts `app bundle ID | title/contact | message | yyyyMMddTHHmmss` over authenticated `POST /api/esp/notifications`. For Apple Messages, the second field supplies the contact; other apps preserve it as a title. The packet timestamp becomes `received_at`, normalized to UTC using configured `ESP_TIMEZONE`; `created_at` separately records server arrival. Delivery sorts priority first, then `received_at`. Set the timezone to match the phone, not the EC2 host. See [the ESP guide](docs/ESP.md) for headers, examples, retry IDs, and limits.

For the demo, serve the existing frontend from the same app container on EC2 behind Caddy. A separate Vercel deployment is unnecessary for this interface and would introduce cross-origin authentication/API setup.

## Providers and limits

Defaults: `CLASSIFIER_PROVIDER=openai`, `CLASSIFIER_MODEL=gpt-6-luna`, `TTS_PROVIDER=openai`, `TTS_MODEL=gpt-4o-mini-tts`, voice `alloy`. The speech model is available for this hackathon but deprecated; review its replacement before maintaining this app beyond the demo. API errors are shown as failed work with an explicit Retry action. There is no silent switch to fake classification.

To use real GPT with built-in Mac speech and no hosted TTS charges:

```sh
TTS_PROVIDER=macos ./scripts/run_local.sh
```

For no API calls at all:

```sh
CLASSIFIER_PROVIDER=demo TTS_PROVIDER=macos ./scripts/run_local.sh
```

Demo classification recognizes only the five scripted samples; custom content gets a generic priority-3 cue. The interface labels this mode. macOS speech uses the installed `say` command and still creates a WAV for the same delivery protocol.

The default durable limit is **300 provider operations**, counting classification batches, group summaries, and speech invocations (including local/demo providers). It survives server restarts. This is not a $300 allowance, a dollar spending limit, or a display of your OpenAI balance. Change `MAX_PROVIDER_CALLS` in `.env` deliberately and restart to raise it. SDK automatic retries are disabled. Only priorities 3–5 invoke speech.

Outstanding work is capped at 100 original notifications, including members of grouped, failed, and leased items. Audio is capped at 45 seconds and 5 MB per item. Runtime SQLite and WAVs are stored in ignored `data/`. Successful playback removes the content and audio; priority 1–2 content is deleted after classification. The newest 10,000 opaque completed-event IDs and 10,000 ACK receipts remain for deduplication; lifetime aggregate counters remain visible. Older retried events can be treated as new once their IDs have been pruned. This does not delete the original phone notification or provider-side records.

## One message at a time

The Mac client uses the same pull/lease/ACK protocol intended for the Pi. Each device can hold one active lease. Retrying a claim returns that lease; it never pulls a second message. Heartbeats renew the default 90-second lease. Expiry requeues abandoned work, up to five attempts before manual retry is required. An acknowledgment is accepted only for the current device/lease, and duplicate completion ACKs are idempotent. No audio batches or automatic next-message playback are used.

The EC2 demo runs at https://sap.elischiffler.dev using the HTTPS Docker setup in [the EC2 runbook](docs/EC2.md). The owner chose public dashboard access and controls; the ESP-specific endpoint retains its bearer token. This is one shared queue. See [the deployed runbook](docs/DEPLOYED.md) for live verification and remaining hardware integration work.

## Checks

```sh
.venv/bin/python -m pytest -q
.venv/bin/ruff check contracts server intelligence tests
.venv/bin/ruff format --check contracts server intelligence tests
node --check web/app.js
.venv/bin/python -m scripts.check_load
```

Automated tests use mocked OpenAI responses and isolated temporary databases; macOS synthesis is exercised when `say` is available. A live smoke run separately verified all five sample priority decisions, deletion of 1–2, hosted WAV generation, browser playback, and stop/retry. See [verification notes](docs/VERIFICATION.md) for the tested scope and remaining limits.

Confirmed behavior: priorities 1–2 are removed from the delivery queue after classification; no audio or Pi delivery. Debugging history retains original payloads for two hours, then only metadata, bounded to 1,000 requests. Priorities 3–5 enter the playback queue. Priority 5 alerts immediately. Speech always waits for a button press. Deletion applies to SAP's copy, not the original phone notification. The pager cannot reply, answer calls, or dismiss notifications on the phone.

Target: Mac development server first, then EC2; iPhone → XIAO ESP32-C3 Bluetooth bridge → server → Raspberry Pi Zero 2 W audio pager.

Submission deadline: Sunday, November 15, 2026, noon Pacific.

Pi integration uses the three MVP routes described in [the Pi handoff](docs/PI_HANDOFF.md). Friendly speech labels cover 92 apps; see [app-name sources](docs/APP_NAMES.md). The provider-operation cap is 5,000 and does not reset usage on restart.
