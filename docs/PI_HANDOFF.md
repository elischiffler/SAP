# Raspberry Pi handoff

Server URL: **https://sap.elischiffler.dev**. The Pi initiates HTTPS requests with certificate verification; EC2 needs no Pi IP address, and the devices need not share Wi-Fi. Pi routes use the owner's public demo access. The ESP ingestion token is only for notification ingestion.

## Install or update the implemented client

Follow [`bridges/pi/README.md`](../bridges/pi/README.md). The directory contains the real `client.py`, GPIO helper `led.py`, installer, updater, systemd unit, configuration template and `download_only.py` diagnostic.

- First installation on Raspberry Pi OS: copy that directory to the Pi and run `sudo bash install.sh` there. It refuses to overwrite an existing installation.
- Existing `sap-pager.service`: follow the documented `update.sh` procedure. It preserves GPIO/audio settings and the pending playback acknowledgment.
- Configuration lives in `/etc/default/sap-pager`; state and rotating logs live in `/var/lib/sap-pager`.
- Expected wiring uses BCM GPIO17 for the button (pull-up, 50 ms debounce) and GPIO27 for the LED through a 220-ohm resistor. Preserve the actual device's configured wiring.

The implemented client already imports the LED helper; no separate `main.py` integration is needed. A custom older client must adopt the contract below or be replaced deliberately. Deploying EC2 does not install or update Pi software.

Playback uses ALSA `aplay` and the configured/default ALSA device. A Pi Zero 2 W needs an attached, configured audio output. Installing the client does not configure an absent speaker or prove sound was heard.

## API contract

| Request | Result |
| --- | --- |
| `GET /status` | `{"items":[{"id":"<UUID>","priority":5}],"led_on":true}` or an empty items list. At most one item; polling neither reserves nor deletes it. |
| `GET /audio/<id>` | Complete `audio/wav` plus `X-Pi-Transfer-ID`. Claims a 90-second lease. Repeated downloads of that same item are allowed; a different item waits until ACK or lease expiry. Range requests are rejected. |
| `POST /api/pi/downloaded` | JSON `{"id":"<UUID>","transfer_id":"<lease UUID>","size":12345,"sha256":"<hex digest>"}` after complete validation and fsync. The server validates the active transfer and file, then returns `{"status":"download_confirmed","id":"<UUID>"}`. It does not play, ACK, delete or renew the lease. |
| `POST /ack` | JSON `{"ids":["<same UUID>"]}` after successful playback. Returns `{"status":"acknowledged","ids":["<same UUID>"]}`. Retrying that ACK is idempotent, including across server restarts. |

POSTs use `Content-Type: application/json`. The server continues supporting older clients that omit the saved-file receipt, but their transfers cannot be labeled confirmed on-device.

## One press, one item

Startup and background polling do not download, play or acknowledge messages. Each press gets fresh status, downloads one complete WAV, validates it, reports the saved-file receipt, invokes `aplay`, and then persists/retries its playback ACK. Presses while busy are ignored. The client never drains the queue or sends a batch ACK.

Only a successful `aplay` exit creates the ACK-pending journal. A network failure during ACK retains the journal across restarts. The next button press retries only that ACK; it does not also play another item. Rejected/expired ACKs are logged and refresh status rather than being reported as success. Audio is cleaned up after an attempt; no permanent local playlist is maintained.

Waiting items are ordered P5, P4, P3, then first-member source timestamp. A leased item is not interrupted by a newer urgent one. Polling leaves a group open; claiming audio seals it permanently. A status item can appear before its WAV is ready. HTTP 409 refreshes status and waits for another press; failed downloads/playback are never acknowledged.

## LED and timing

Only literal `led_on: true` lights the LED. The flag covers pending, preparing, ready and leased P5 items, including one waiting behind lower-priority audio. P3/P4 counts never light it. Failed polls turn it off and log the error; button presses do not independently clear it. There is no queue-count threshold or connection-error blink mode, and the LED never triggers speech.

The implemented client polls three seconds after each completed poll. Limits in the code are:

| Operation | Limit |
| --- | --- |
| HTTP inactivity/connect timeout | 5 seconds |
| Status or ACK operation | 8 seconds |
| Audio download | 20 seconds |
| Saved-file receipt | 5 seconds |
| `aplay` process | 50 seconds |
| WAV | 5,000,000 bytes; 45 seconds |
| Server lease | 90 seconds |

These bounds allow a normal button operation within the lease; they do not guarantee completion under stalls or failures. An expired transfer is handled through the existing retry/status flow. The Pi adapter does not heartbeat its lease; the separate `/api/delivery/*` protocol supports heartbeats for other clients.

## What the dashboard proves

- **Recent contact:** a client called a Pi route; this does not verify wiring.
- **Audio sent / awaiting acknowledgment:** the server finished its response; this alone does not prove the file was saved on the Pi.
- **Downloaded on Pi:** the client reported a fully saved/validated WAV and the server accepted its size/hash receipt. It does not establish that the file remains indefinitely or that sound played.
- **Acknowledged:** with this client, `aplay` returned success and the playback ACK succeeded. That is a software report, not independent confirmation that someone heard the physical speaker.

Physical GPIO and speaker verification requires the wired Pi and the owner's button press. Routine installation checks should inspect service state/logs and use polling only. The download-only diagnostic consumes a real offered transfer lease and must be explicitly requested; it saves/validates and reports a receipt, but never plays or ACKs. Follow its cleanup/service instructions in the Pi README.

## Historical supplied-spec context — November 14, 2026

The original `Pi Device MVP Tech Spec.md` described a one-second playback stub, a queue-count LED threshold and draining all waiting messages per press. Early integration reviews correctly recorded that no Pi implementation was then present. Those statements describe that earlier stage only.

The current repository includes the implemented `aplay` client, one-message-per-press behavior, priority-5-only LED, bounded downloads, saved-file receipts and durable ACK recovery. Local mocked tests verify software behavior. They do not prove which version is installed on a particular Pi, that ESP firmware was flashed, or that GPIO/speaker hardware works. See [the deployment record](DEPLOYED.md) for dated evidence; no new hardware verification was performed during this documentation reconciliation.
