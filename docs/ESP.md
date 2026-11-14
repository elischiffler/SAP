# Send ESP32 notifications to SAP

**Live on EC2:** subtitle support, emoji names, and removal of manual submission are deployed.

The ESP32 receives a notification from the paired iPhone, then sends the app, title, subtitle, message, and ANCS date to SAP over HTTPS. The pager's queue shows the received time in the browser's local timezone.

Temporary HTTP testing is also enabled for **POST http://sap.elischiffler.dev/api/esp/notifications**. Use the same token, headers, body and event ID; this exact POST route accepts ingestion without a redirect. The token and notification text are unencrypted on HTTP. Other HTTP routes redirect to HTTPS. Prefer HTTPS for continued use. [Copy-and-paste AI firmware handoff](ESP_AI_HANDOFF.md).

## Device request

- Use `POST https://sap.elischiffler.dev/api/esp/notifications` with TLS certificate verification.
- Send `Authorization: Bearer <ESP_INGEST_TOKEN>` and `Content-Type: application/json`.
- Send a UTF-8 JSON object with the five string fields below. For Apple Messages (`com.apple.MobileSMS`), SAP uses `title` as the sender label. For other apps, SAP keeps it as the title.
- Generate a UUID for each notification and send it in `X-Event-ID`. Reuse that UUID and the same payload when retrying the delivery.

```json
{"app":"com.apple.MobileSMS","title":"Matthew Cheese Ellis","subtitle":"","message":"T minus 10 min","date":"20261114T130105"}
```

`subtitle` is a string up to 256 characters; use an empty string when ANCS has none. Older requests that omit it remain valid. It is preserved in the validated payload and classification input, and included in speech when present. It is not treated as a stable conversation ID.

The request body limit is 32 KiB. ESP firmware using `Content-Type: text/plain; charset=utf-8` can continue sending `app | title | message | date`. JSON preserves pipes in both the title and message. The text format preserves pipes in the message field.

The ANCS date string is `YYYYMMDDTHHMMSS` and carries no offset. The live server interprets it in `America/Los_Angeles`, so the sample is stored as `2026-11-14T21:01:05Z`. Send the date from the iPhone notification. If the source iPhone changes zones, update `ESP_TIMEZONE` on the server to match. Ambiguous and skipped local times around clock changes return a validation error. Manual dashboard submission and its `/api/notifications` endpoint are removed; use the authenticated ESP endpoint.

Successful ingestion returns HTTP 202 with `event_id` and `status`. This confirms queue admission. Classification and speech processing follow asynchronously, and playback begins when someone presses Play. When no UUID is supplied, SAP derives one from the normalized packet. Two identical packets stamped in the same second can then collapse into one event. Retry uncertain deliveries, HTTP 429, and temporary server errors with the same ID and bounded backoff. Review the token and payload before retrying authentication or validation errors.

## Arduino ESP32

This helper takes your existing TLS client, serialized JSON payload, and event UUID. Connect Wi-Fi, synchronize the board's clock, and configure the client with the trusted CA for the server before calling it. Supply `ESP_INGEST_TOKEN` from a private firmware configuration file and keep it out of Git and serial logs. [Espressif HTTPClient reference](https://github.com/espressif/arduino-esp32/blob/master/libraries/HTTPClient/src/HTTPClient.h)

```cpp
#include <HTTPClient.h>
#include <WiFiClientSecure.h>

int sendSapNotification(WiFiClientSecure& tlsClient, const String& payloadJson,
                        const String& eventUuid) {
  const char* url = "https://sap.elischiffler.dev/api/esp/notifications";
  HTTPClient http;
  if (!http.begin(tlsClient, url)) {
    return -1;
  }
  http.addHeader("Content-Type", "application/json");
  http.addHeader("Authorization", String("Bearer ") + ESP_INGEST_TOKEN);
  http.addHeader("X-Event-ID", eventUuid);
  const int status = http.POST(payloadJson);
  http.end();
  return status;
}
```

## Test on the demo hostname

Make `ESP_INGEST_TOKEN` available in the test shell through a private configuration. Keep the token out of source control and shell tracing. The request below sends the JSON example as a test notification.

```sh
event_id=$(uuidgen)
printf '%s' '{"app":"com.apple.MobileSMS","title":"Matthew Cheese Ellis","subtitle":"","message":"T minus 10 min","date":"20261114T130105"}' |
  curl --fail-with-body --silent --show-error \
    --header "Authorization: Bearer $ESP_INGEST_TOKEN" \
    --header 'Content-Type: application/json' \
    --header "X-Event-ID: $event_id" \
    --data-binary @- \
    "https://sap.elischiffler.dev/api/esp/notifications"
```

Use the same generated UUID if you need to retry a real event. Open the public dashboard to inspect the queue and play the resulting summary. This ESP ingestion route still requires its device token. The dashboard, queue, audio, and playback controls are public by the owner’s explicit choice. See the [EC2 runbook](EC2.md) for deployment settings.

## Inspect incoming requests

Open **Incoming requests** on the dashboard. A 202 entry confirms admission; its queue status shows the current processing or playback state. Expand **Received payload** to inspect the original accepted JSON keys and values: `app`, `title`, optional `subtitle`, `message`, and the original local ANCS `date`. Omitted fields stay omitted, emoji remain emoji, and the server does not add its internal fields to this payload. Generated event ID and queue status are separate metadata. Sensitive values are still redacted and labeled when changed. Legacy text requests display the original text packet. Both HTTP and HTTPS feed the same queue, and retries with the same event ID refer to one notification.

Request history is stored in SQLite and survives restarts. It retains the latest 1,000 request records and exposes 50 at a time in the dashboard, with Newer/Older navigation. Each row keeps the request's own priority even when playback groups merge. Payloads expire two hours after server receipt; timestamp, priority and status metadata remain until the 1,000-record bound. Cleanup runs in the background and on history reads. Discard/playback still removes queue content and audio, while its debugging payload remains only for that two-hour window. Rejected bodies, authorization headers and secrets are excluded/redacted.

## Unicode and emoji

Send the complete ANCS UTF-8 bytes through a JSON serializer. Valid Unicode emoji and JSON surrogate-pair escapes are accepted. The speech preview uses readable English emoji names (for example, 🙂 becomes “slightly smiling face”) without another model request. Classification and the received payload retain the original Unicode. If firmware replaces an emoji with `z` before upload, SAP cannot recover it; avoid ASCII conversion or byte-wise character casts in the firmware.


## Long messages

Firmware requests up to 4096 UTF-8 message bytes, with bounded 8192-byte ANCS
reassembly. Rebuild/flash the ESP to replace the old 200-byte limit. The server
already accepts 4096 Unicode characters per message (32 KiB HTTP body cap).
Short speech stays verbatim after secret redaction, whitespace cleanup and emoji
naming. If the complete spoken quote exceeds 350 characters including its source
introduction, the server uses the existing classifier summary, prefixed `Summary:`.
No extra summarization request is made for a single long notification. Missing or
oversized summaries produce a check-your-phone cue instead of a cut-off sentence.
