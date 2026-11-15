# SAP — Simplified Abstraction of a Phone

A button-operated audio pager that lets important iPhone notifications reach you without opening your phone.

The dashboard and FastAPI server are deployed at [sap.elischiffler.dev](https://sap.elischiffler.dev) on EC2. The flow is iPhone → ESP32 ANCS Bluetooth bridge → server classification and Alloy TTS → browser or Raspberry Pi playback. The Pi client in this repository uses real ALSA `aplay`; running software and validated downloads do not establish that the physical speaker or GPIO hardware has been tested.

- [Deployed release, verification evidence and operations](docs/DEPLOYED.md)
- [Pi installation and updates](bridges/pi/README.md) · [Pi API handoff](docs/PI_HANDOFF.md)
- [ESP input and connection guide](docs/ESP.md)
- [Conversation grouping and limits](docs/GROUPING.md)
- [One-message delivery protocol](docs/DELIVERY.md)
- [EC2 deployment runbook](docs/EC2.md)
- [Classifier prompt](prompts/classify-notification.md) · [Verification history](docs/VERIFICATION.md)
- [Mac Bluetooth experiment](docs/MAC_BLUETOOTH.md)

## Run locally

Requires Python 3.11+; developed on this Mac with Python 3.14. To create the environment:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
```

Configure `OPENAI_API_KEY` in the ignored `.env`; `.env.example` lists settings without credentials. Then run:

```sh
./scripts/run_local.sh
```

Open [the local dashboard](http://127.0.0.1:8000). The script binds to loopback and uses one server worker. The product showcase is separate from the deployed notification dashboard.

1. Notifications arrive through authenticated ESP ingestion. Manual/sample submission is disabled in the dashboard and normal server configuration; isolated tests have an explicit test-only adapter.
2. Priority 1–2 notifications are discarded from delivery. Priorities 3–5 become eligible for speech.
3. Press **Play next** or Space outside a form field to play one message/group. Delivery order is priority 5, 4, 3, then the first member's source timestamp within each tier. The next classified item holds its place while its audio is prepared.
4. **Stop playback** releases the item for a later attempt. Playback never advances automatically to another message.

Priority 5 raises the dashboard alert; browser chimes require the browser's audio permission/gesture. Speech still requires a button press. Multiple browser tabs coordinate with a playback lock and retain opaque pending acknowledgment receipts for retry.

## ESP input

The current wire payload is JSON sent to `POST /api/esp/notifications` with the ESP bearer token:

```json
{
  "app": "com.apple.MobileSMS",
  "title": "Sam",
  "subtitle": "Hackathon Team",
  "message": "Please bring the pager",
  "date": "20261114T130105"
}
```

`subtitle` is optional for older firmware. The pipe-delimited `app | title | message | date` form remains a legacy input option. A general validated notification model supports all apps. The phone's ANCS date becomes UTC `received_at` using `ESP_TIMEZONE` (Pacific for this deployment); server arrival is recorded separately.

Use HTTPS. The owner also enabled a temporary plain-HTTP exception specifically for the token-protected ESP ingestion endpoint. See [ESP setup](docs/ESP.md) for headers, retry identity and limits. Firmware source requests up to 4,096 UTF-8 bytes, but the device must be flashed to activate that limit; an app-provided shortened preview cannot be reconstructed by the server.

## Speech and grouping

Alloy is the fixed hosted voice. Short complete P3/P4 previews use a redacted source quote, for example:

> New message on Messages from Sam: 'Want dinner tonight?'

Long or ellipsis-ended previews reuse the existing classification summary. They are paraphrased, not quoted as original speech. The model is instructed to summarize only received information, without inventing the missing ending or announcing an incomplete-preview warning. Hidden/insufficient content gets an unavailable-content cue. Credential redaction, whitespace cleanup and emoji names apply before speech. Friendly app labels cover 92 apps; history shows Messages as “Text message / SMS” while preserving raw identifiers in payloads.

P5 speech uses an urgent introduction. Groups announce their count and summarize their members; mixed-priority groups cover urgent updates first, then lower-priority updates with “Also,”. Individual speakers remain available to the summarizer. Existing generated or downloaded audio is not retroactively rewritten just because wording policy changes.

Matching uses app plus conversation ID, otherwise sender ID or sender label. Messages subtitles provide named-chat identity; the observed unnamed `To you & <other contact>` form combines the title's sender with that recipient. Ambiguous or truncated recipient lists stay separate. Direct messages remain separate from group chats.

Up to ten matching inputs share a classification call, with a decision per notification. Up to fifty retained messages can combine while unclaimed, regardless of elapsed time. The 60-second setting limits raw classification batching, not unclaimed group lifetime; a two-second quiet delay reduces repeated synthesis, and P5 bypasses that delay. Claiming audio permanently seals membership. See [grouping details](docs/GROUPING.md) for identity limitations, priority ordering and provider-budget behavior.

## Providers, retention and capacity

Defaults in `contracts/settings.py`: classifier `gpt-6-luna`, TTS `gpt-4o-mini-tts`, voice `alloy`, with both providers set to `openai`. Provider errors are surfaced for retry; there is no silent fallback to fake classification.

```sh
# Real classification with local Mac speech:
TTS_PROVIDER=macos ./scripts/run_local.sh
# Local demo classification and speech, without hosted provider calls:
CLASSIFIER_PROVIDER=demo TTS_PROVIDER=macos ./scripts/run_local.sh
```

Demo mode recognizes scripted fixtures; other content receives a generic priority-3 cue. It does not enable manual submission on the dashboard.

The default durable cap is **5,000 provider operations**, including classification batches, group summaries and speech invocations, including local/demo adapters. It survives restarts and is not an account credit balance or dollar budget. `MAX_PROVIDER_CALLS` changes the cap; SDK automatic retries are disabled.

Outstanding work is limited to 100 original notifications. WAVs are limited to 45 seconds and 5 MB. Priority 1–2 content is removed from delivery; successful playback removes queued content/audio. Debug history separately retains original accepted payloads for two hours, with sensitive values redacted, then keeps metadata within a 1,000-record bound. The newest 10,000 opaque completion IDs and ACK receipts support retries. These deletions do not alter the original phone notification.

## Pi delivery and deployment

The Pi initiates HTTPS requests over the internet and needs no shared Wi-Fi with EC2. Each button press handles one offered item. The server advertises at most one item and permits one active Pi lease, normally 90 seconds. The Pi's LED uses only `led_on`, reflecting P5 work. A saved-file receipt and a successful-playback ACK are distinct; see [the handoff](docs/PI_HANDOFF.md).

The EC2 dashboard and playback controls are public by the owner's explicit choice. The Pi adapter shares that demo access; ESP ingestion still requires its token. This is one shared queue. The frontend is served by the existing app behind Caddy, alongside the API.

## Verification

```sh
.venv/bin/python -m pytest -q
node --check web/app.js
```

Use Ruff on changed Python files. Automated provider tests use mocks and temporary databases. The latest recorded release on November 14, 2026 has **387 passing tests** and read-only deployment verification; see [release evidence](docs/DEPLOYED.md). Earlier live sample smoke tests are historical and documented in [verification notes](docs/VERIFICATION.md). Do not send live synthetic notifications or consume real queued audio for routine verification.

The pager cannot reply, answer calls, or dismiss phone notifications. Hardware wiring, the running ESP firmware and physically audible Pi output require device-side verification; code availability and server health alone do not establish them.

Submission deadline: Sunday, November 15, 2026, noon Pacific.
