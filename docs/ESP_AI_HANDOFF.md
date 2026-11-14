# Copy-and-paste ESP integration prompt

**Live on EC2:** the five-field payload and emoji handling are deployed and verified over both HTTP and HTTPS.

Paste the block below into the chat helping with the ESP firmware. Supply the
ingest token separately through a private local configuration; do not paste the
OpenAI key or server environment file.

```text
Help me integrate my existing ESP/iPhone ANCS notification bridge with an already
deployed SAP server. Inspect my firmware's framework (Arduino/PlatformIO or
ESP-IDF) and adapt its current HTTP client. Preserve the Bluetooth pairing and
notification capture code. Do not rebuild the server.

WORKING HTTPS CONFIGURATION
Method: POST
URL: https://sap.elischiffler.dev/api/esp/notifications
Content-Type: application/json; charset=utf-8
Authorization: Bearer <ESP_INGEST_TOKEN_FROM_PRIVATE_CONFIG>
X-Event-ID: <UUID_GENERATED_ONCE_FOR_THIS_NOTIFICATION>

Example JSON body (serialize as JSON, not manually concatenated strings):
{
  "app": "com.apple.MobileSMS",
  "title": "Matthew Cheese Ellis",
  "subtitle": "",
  "message": "T minus 10 min",
  "date": "20261114T130105"
}

Use actual ANCS values for real notifications. All five fields are strings;
subtitle may be empty or omitted for older firmware. Do not add extra JSON fields. app is the bundle identifier, title is
the ANCS title, subtitle is the ANCS subtitle, message is the notification text, and date is the original ANCS
timestamp in YYYYMMDDTHHMMSS format. The source iPhone uses Pacific time; the
server converts America/Los_Angeles to UTC. Do not replace date with upload time.
For Apple Messages the server treats title as the contact/group label.
Preserve UTF-8 emoji exactly; do not cast Unicode characters into single-byte
ASCII or replace them. JSON Unicode escapes are also accepted. The server expands
emoji to English names for speech.
Limits: app 100 chars, title 256 chars (Messages sender max 120), subtitle 256, message 4096
chars, total encoded HTTP body 32 KiB. Tell me if ANCS content exceeds a limit;
do not silently truncate urgent content or retry a rejected payload forever.

Configure Wi-Fi, synchronize the ESP's clock, and verify the server certificate
using a suitable trusted CA/certificate bundle. Use the DNS hostname, not the
bare EC2 IP. Do not disable TLS verification. Store the ESP token privately,
exclude it from git, and never print it or Authorization headers to serial logs.
No Basic username/password or OpenAI API key is needed on the ESP.

TEMPORARY WORKING HTTP CONFIGURATION
Method: POST
URL: http://sap.elischiffler.dev/api/esp/notifications
Use the same Content-Type, Authorization and X-Event-ID headers and the same
JSON body as the HTTPS version. Use the framework's ordinary non-TLS network
client for this version. Direct HTTP POST ingestion is enabled only on this
exact ESP route. It should return 202, not a redirect. Both the token and
notification text travel unencrypted in this temporary test mode; prefer HTTPS
for continued use. The dashboard and other HTTP routes redirect to HTTPS.

Provide a configuration switch between these two URLs/transports. Keep event
IDs unchanged if retrying the same notification via the other transport.

DELIVERY AND RETRIES
Send one notification per POST. Generate a UUID once and reuse it with the
identical payload on retries; keep it with the queued item. The server also
deduplicates matching packets without a UUID, but identical notifications in
the same second can then collapse together. Prefer the UUID header.
Queue network work outside the BLE callback. Use a bounded queue and one HTTP
request in flight. Report queue-full events explicitly. Retry connection errors,
timeouts, 429 and temporary 5xx responses with exponential backoff and jitter,
capped around 30 seconds, preserving the event ID and payload. Respect a
Retry-After header when present. Do not endlessly retry 401, 413, 415 or 422;
report an authentication, size, media-type or validation problem respectively.
HTTP 202 means durably accepted into the server queue; processing happens later.
Read the JSON event_id/status response. A successful duplicate retry is also 202.

The server classifies priorities, discards priorities 1–2, groups related
notifications and generates Alloy speech for priorities 3–5. This ESP task is
notification ingestion only. Do not implement audio delivery or use playback
ACKs as acknowledgments for notification POSTs.

TEST AND DEBUG
Start with one synthetic notification. Log only HTTP status, event ID and safe
error categories. The public message dashboard is https://sap.elischiffler.dev/.
Its Incoming requests section shows arrival time, route, HTTP status, app, event
ID and queue status. Expand Received payload to inspect the original accepted
JSON fields, including message and the unchanged local ANCS date. Omitted subtitle
fields stay omitted; emoji stay Unicode. Generated event IDs remain outside the
payload. Sensitive values are redacted and labeled when changed.
Tokens and headers are excluded. Rejected requests never expose their bodies.
Payloads expire two hours after server receipt. History survives restarts and
keeps the latest 1,000 request records with per-request priority and status. The dashboard has no username/password.

Show me the firmware changes, where to configure the private token, and a test
that demonstrates 202 admission plus retrying the same UUID without creating a
second notification. Do not claim hardware verification unless you ran it on
the actual ESP.
```
