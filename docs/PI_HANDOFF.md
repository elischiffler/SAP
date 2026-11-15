# Raspberry Pi handoff

Server URL: **https://sap.elischiffler.dev**. The Pi pulls audio; the server does not need the Pi's IP address. Use HTTPS with normal certificate verification. This uses the same public demo access as the dashboard; the ESP ingestion token remains required only for notification ingestion.

## API matching the MVP spec

| Request | Result |
| --- | --- |
| `GET /status` | `{"items":[{"id":"<notification UUID>","priority":5}],"led_on":true}` or `{"items":[],"led_on":false}`. At most one item. Polling does not reserve or delete it. |
| `GET /audio/<id>` | Complete `audio/wav` bytes. Reserves a 90-second lease for the single Pi device. Repeated downloads of that same item are safe. A different item cannot be downloaded until it is acknowledged or the lease expires. |
| `POST /ack` | JSON `{"ids":["<same id>"]}` with Content-Type application/json. Returns 200 after the downloaded item is acknowledged. Retrying the same ACK is idempotent, including across server restarts. |

The updated client is in [`bridges/pi/`](../bridges/pi/README.md). It uses real
ALSA `aplay` playback and durable ACK recovery. For download confirmation, the
server also returns `X-Pi-Transfer-ID` with the WAV. Once the Pi has saved,
fsynced and validated the complete file, it posts `id`, `transfer_id`, `size`
and `sha256` to `/api/pi/downloaded`. This receipt only confirms the saved file;
it never replaces the successful-playback `/ack`. The dashboard shows the audio
message text and confirmation time. Older clients remain compatible but their
downloads are labeled sent, not confirmed on-device. The earlier stub discussion
below describes the original supplied spec, not the implemented client.

**LED policy: priority 5 only.** Use the top-level boolean `led_on` from every
successful status response. It is true while any priority-5 item is pending,
preparing audio, ready, or awaiting acknowledgment. It includes an urgent item
waiting behind an active lower-priority lease. Priorities 3 and 4 remain playable
but never light the LED, regardless of their count. The LED turns off once the
last eligible priority-5 item is acknowledged or removed.

Remove the old `LED_THRESHOLD`, seen-ID blink logic, button-triggered LED clearing,
and connection-error blink logic. On a failed poll, turn the LED off; report
connectivity errors through logs. No automatic speech is triggered by the LED.

Copy `bridges/pi/led.py` beside the Pi's `main.py` and integrate it in the polling loop:

```python
from led import update_led

# After a successful GET /status with validated JSON:
update_led(led, response.json())
# On request/JSON failure:
update_led(led, None)
```

The server change alone cannot change an existing Pi script's GPIO behavior;
install this helper and replace the old LED rules on the device, then restart its service.

**One button press processes one item.** Eli selected this behavior after reviewing the spec. Do not drain the queue or send batch acknowledgments. The server enforces a single ID in each ACK. Waiting items are ordered priority 5, 4, 3, then oldest source timestamp. A currently reserved item is not interrupted by a newer urgent one. Priorities 1 and 2 are excluded from delivery.

A status item may appear while its speech is being prepared so the Pi can indicate priority 5 promptly. If audio returns 409, preserve the item, refresh status, and try on the next press; never ACK a failed download. Priority **5**, not 1, is the urgent-LED condition (the last checklist in the supplied spec has a typo).

Download the complete WAV; range requests are rejected. WAVs are capped at 5 MB and 45 seconds. With the spec's five-second network timeout and one-second playback stub, the normal flow fits within the 90-second lease. Expired deliveries can be downloaded again. Persist an ACK-pending ID locally after successful playback and retry that same ACK before starting another item, so a lost HTTP response does not cause duplicate playback. For lengthy real playback or stronger identity/authentication requirements, use the existing `/api/delivery/*` lease API with heartbeat instead of this single-device adapter.

The dashboard's **Pi delivery** panel reports recent contact, audio sending, audio sent/waiting for acknowledgment, acknowledged completion, interrupted transfers, and expired acknowledgments. An acknowledgment confirms the Pi's report; with the supplied play stub it confirms save/stub completion, **not audible speaker output**. A blocking device loop can pause polling during playback; “No recent contact” is not proof of a disconnected Pi.

## Firmware alignment

The supplied `Pi Device MVP Tech Spec.md` is design input. No actual Raspberry Pi implementation was present in the repository at review time. The `main` update `14b2bd2` contains the separate ESP32 ANCS forwarder, which already sends app/title/subtitle/message/date and is compatible with current ingress.

Keep the spec's Pi 4/Zero 2W hardware choices: GPIO17 button (pull-up, debounce), GPIO27 LED with resistor, and reserve GPIO18/19/21 for future audio. Keep priority-5 tracking stable through failed downloads; keep the LED driven by the server flag rather than clearing it on button press. Bound saved audio as well as rotating request logs, and keep credentials out of logs if authentication is later added.

No synthetic requests are being sent to the deployed queue. Adapter verification uses isolated temporary databases and fake local providers. A teammate still needs to run the actual Pi against these endpoints; hardware and speaker output are unverified.
