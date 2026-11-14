# ESP32-C3 ANCS notification forwarder

Seeed XIAO ESP32-C3 reads iPhone notifications over BLE (Apple Notification Center Service) and
POSTs each one as JSON to an HTTP server over Wi-Fi.

```
iPhone --BLE/ANCS--> ESP32-C3 --Wi-Fi/HTTP POST--> SERVER_URL/notifications
```

## Layout

| Path | Purpose |
|---|---|
| `src/TransmitIphoneNotis.cpp` | all firmware |
| `include/config.h` | Wi-Fi, server URL, ANCS options |
| `tools/mock_server.py` | prints received JSON, for testing |
| `platformio.ini` | board `seeed_xiao_esp32c3`, NimBLE-Arduino 2.x on the pioarduino (Arduino core 3) platform |

## Setup

1. Edit `include/config.h`: `WIFI_SSID`, `WIFI_PASS`, `SERVER_URL`, `ATTR_MAX_LEN`, `INCLUDE_PREEXISTING`.
   Wi-Fi must be 2.4 GHz.
2. Run the mock server on your computer (same network as the ESP32) and point `SERVER_URL` at its LAN IP:
   ```
   python3 tools/mock_server.py            # port 8080
   python3 tools/mock_server.py --fail 2   # answers the first 2 POSTs with 503 to test retries
   ```
3. Build, flash, monitor:
   ```
   pio run -t upload
   pio device monitor        # 115200 baud
   ```
   The first build downloads the pioarduino platform and NimBLE (a few minutes).

## Pairing with the iPhone (first time only)

1. Flash the board. The serial log shows `[BLE] advertising`.
2. On the iPhone open a BLE app such as **nRF Connect** or **LightBlue** and connect to **`ANCS-Forwarder`**.
   (Depending on iOS version the device may also show up in *Settings > Bluetooth*; either works.)
3. The ESP32 requests pairing; accept the **Bluetooth Pairing Request** dialog on the iPhone.
4. **Share System Notifications:** iOS shows *"Allow "ANCS-Forwarder" to receive your system notifications?"* —
   tap **Allow**. If you missed it or tapped *Don't Allow*, go to
   *Settings > Bluetooth > (i) next to ANCS-Forwarder > Share System Notifications* and switch it **on**.
   Without this, ANCS setup fails and the log says `[ANCS] service not found` /
   `Is 'Share System Notifications' enabled?`.
5. The log shows `[BLE] link encrypted` and `[ANCS] ready`. Send yourself a message.

The bond is stored in NVS on both sides, so after a power cycle or the phone leaving range the iPhone
reconnects on its own (the ESP32 advertises an ANCS service solicitation, which is what makes iOS reconnect
to a bonded device).

**If pairing breaks** (e.g. you re-flashed with erased flash, or "Forget This Device" was done on only one side):
forget the device on the iPhone *and* set `#define CLEAR_BONDS_ON_BOOT 1` in `config.h` for one boot
(or run `pio run -t erase`), then pair again.

## JSON format

```json
{"uid":123,"event":"added","app":"com.tinyspeck.chatlyio","category":"social",
 "title":"...","subtitle":"...","message":"...","flags":["silent"],"ts":"2026-11-14T11:32:05"}
```

* `event`: `added` | `modified` | `removed`
* `category`: `other, incoming_call, missed_call, voicemail, social, schedule, email, news, health, business, location, entertainment`
* `flags`: any of `silent`, `important`, `pre_existing`, `positive_action`, `negative_action`, plus `incoming_call`
  when the category is Incoming Call.
* `ts`: the notification's date from the iPhone, **phone-local time, no timezone suffix**.
  `removed` events carry no date, so their `ts` is derived from the phone clock learned from earlier live
  notifications (empty string if none has been seen since boot).
* `removed` events can't query ANCS any more, so `app`/`title` come from a 16-entry cache of recent
  notifications (empty if it was evicted); `subtitle`/`message` are empty.

## Behaviour notes

* Attributes are requested for `added` and `modified` events (App Identifier, Title, Subtitle, Message up to
  `ATTR_MAX_LEN` bytes, Date). Multi-packet Data Source responses are reassembled; one request is in flight at a time;
  a request with no answer is retried once after 3 s and then forwarded without attributes.
* **Pre-existing** notifications (delivered when the phone connects) are ignored unless `INCLUDE_PREEXISTING` is 1.
* **Duplicates:** the same `uid`+`event` is posted once (for `modified`, once per distinct content). The table holds
  48 entries and entries expire after 1 hour.
* **Offline queue:** events wait in RAM (max 16 events / ~20 KB, oldest dropped first) while Wi-Fi or the server is
  down, retried with 0.5 s → 8 s backoff. 4xx responses (except 408/429) are treated as permanent and dropped.
  The queue is lost on reboot.
* Wi-Fi reconnects automatically (retry every 5 s). The phone disconnecting makes the ESP32 advertise again immediately.
* `https://` server URLs work but the certificate is **not verified**.
* Status LED was dropped from the spec; a `[STATUS]` line (BLE state, Wi-Fi state, queue depth) prints every 15 s instead.
* Out of scope and not implemented: call actions, replies, audio.

## Troubleshooting

| Log | Meaning |
|---|---|
| `[ANCS] service not found on phone` | pairing finished but "Share System Notifications" is off |
| `[BLE] pairing failed` | stale bond on one side; forget device on iPhone and clear bonds (see above) |
| `[HTTP] POST failed (-1)` | server unreachable; check `SERVER_URL`, same network, firewall |
| nothing after `advertising` | iPhone hasn't connected; use nRF Connect/LightBlue |
