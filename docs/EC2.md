# SAP on EC2

This Compose stack runs a public hackathon demo. Caddy is the public HTTPS endpoint. The owner explicitly chose public dashboard access and controls, including notification submission. The ESP-specific ingestion endpoint still requires a bearer token. The app listens on port 8000 inside Docker and makes outbound requests to OpenAI. Use synthetic notifications and trusted participants. Everyone using this deployment shares the same SQLite queue and playback device.

## Prepare the host

1. Use a single Linux EC2 instance with Docker Engine and Docker Compose v2 installed. Start with at least 2 GiB RAM for the app, proxy, and operating system, then measure on the intended instance. Keep Docker storage on encrypted EBS. If Docker uses an attached EBS volume, mount it before creating the containers.
2. Point the demo hostname's DNS A record to the instance's stable public IPv4 address. Publish AAAA only if IPv6 is configured. Allow inbound TCP 80 and 443 for the site and certificate issuance. Use Systems Manager or restrict inbound SSH to your administrator's IP range. Keep port 8000 closed. Permit outbound DNS and HTTPS so Caddy can manage certificates and the app can reach OpenAI.
3. Check out the intended revision. Start with a fresh production volume. Keep the Mac test database, audio files, and local `.env` on the Mac.

See [EC2 security group rules](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/security-group-rules-reference.html) and [Caddy automatic HTTPS requirements](https://caddyserver.com/docs/automatic-https).

## Configure and start

On the EC2 host, create a private environment file:

```sh
umask 077
touch .env.production
chmod 600 .env.production
```

Set these values in that file. Use the bare DNS hostname, without a scheme or port. Use a dedicated OpenAI project key and set the appropriate spending controls on that project.

```dotenv
PUBLIC_HOST=sap.example.com
OPENAI_API_KEY='<paste the production project key>'
ESP_INGEST_TOKEN='<paste the bridge token>'
ESP_TIMEZONE=America/Los_Angeles
MAX_PROVIDER_CALLS=100
MAX_PENDING_NOTIFICATIONS=50
```

`ESP_TIMEZONE` must match the iPhone's IANA time zone. It defaults to `America/Los_Angeles`. Set it explicitly if the phone uses another zone. Provision the same high-entropy `ESP_INGEST_TOKEN` on the bridge through its private configuration. See the [ESP32 ingestion guide](ESP.md) for the endpoint and test request.

The last two settings are optional. The example keeps the demo's queue and request budget small. The provider-call counter includes classification batches, group summaries, and speech operations and persists across restarts. It counts requests independently of provider billing.

```sh
docker compose --env-file .env.production config --quiet
docker compose --env-file .env.production up -d --build --wait --wait-timeout 180
docker compose --env-file .env.production ps
```

The Compose configuration requires the hostname, OpenAI key, and ESP ingestion token. Use `config --quiet` so expanded secrets stay out of terminal output. Keep Docker access restricted to operators because it grants access to container settings and volumes.

## Verify the deployment

Run these checks from outside the instance after DNS and issuance settle:

```sh
demo_host=sap.example.com
curl --silent --show-error --output /dev/null --write-out '%{http_code}\n' "http://$demo_host/healthz"
curl --silent --show-error --output /dev/null --write-out '%{http_code}\n' "https://$demo_host/healthz"
curl --fail "https://$demo_host/healthz"
```

Expect an HTTP redirect to HTTPS and HTTP 200 over HTTPS without credentials. The final command should return `{"status":"ok"}`. An external connection to port 8000 should fail. Open the HTTPS page and verify a synthetic notification makes it through classification, queueing, and manual playback. This last check consumes provider calls. It also verifies HTTPS browser features such as Web Locks.

If using the bridge, send one synthetic ESP notification after the browser checks. Caddy forwards the device's bearer token only for `POST /api/esp/notifications`. The dashboard and its controls are public; the canonical JSON submission route can trigger provider calls without the ESP token. The device token is enforced specifically on the ESP route.

## Resource limits and monitoring

- The app gets up to 768 MiB of memory and one CPU, with one Uvicorn worker, a concurrency limit of 32, a socket backlog of 64, and a five-second idle keep-alive. Caddy gets 128 MiB and half a CPU. HTTP requests to `/api/*` are limited to 32 KiB at the proxy. Caddy applies header, body and response timeouts.
- Queue and audio limits bound the application's active work. Near capacity, ingestion can return HTTP 429 and Uvicorn can return HTTP 503. The durable provider-call limit can leave items failed until an operator adjusts the budget. These limits control resource use and can reject work during a burst. This single-instance public setup has no per-user quota or high availability.
- Docker rotates three logs of up to 10 MB per service. The named volumes retain SQLite and Caddy state across restarts. Opaque completed-event and ACK tables are each capped at their newest 10,000 records; lifetime counts are separate. Docker named volumes still have no disk quota in this stack. Monitor free EBS space, volume growth, CPU, memory and restart counts. Set EC2/EBS alarms for the host before a sustained demo.
- An out-of-memory kill can restart the container under the restart policy and interrupt playback. Docker's health check makes initial startup and an unhealthy state observable. A running unhealthy container may require operator intervention. Track sustained 429/503 responses, restarts and provider failures during a small rehearsal. The appropriate EC2 size depends on actual usage and external model latency.

```sh
docker compose --env-file .env.production ps
docker compose --env-file .env.production logs --tail=100 app caddy
docker stats --no-stream
df -h
```

## Update and recover

Before replacing an image or applying a database schema change, stop the app and take a protected backup or EBS snapshot on the host. Record the deployed revision. To update, build and start the intended revision again, keeping the volumes, then repeat the HTTPS checks. If an update fails, redeploy the previous revision and use its matching backup if the database schema changed. Restore a database only while the app is stopped.

Use `docker compose --env-file .env.production down` to stop the stack while preserving volumes. The Caddy certificate volumes should persist across rebuilds as well. The deployment mounts the app filesystem read-only with writable `/tmp` and `/data`. Keep the upstream Docker network exclusive to these containers because the app trusts the proxy's forwarded headers.

## Use an existing Caddy host

If the EC2 host already runs Caddy, let that instance continue handling public HTTPS and automatic certificates. Run SAP under its own Compose project. The shared-host override publishes only SAP's internal proxy on host loopback. The app port remains inside Docker.

1. Confirm existing sites are healthy and that the proposed SAP hostname is unused in the host Caddy configuration. Check that TCP 18080 is free on the host. If it is occupied, set `SAP_PROXY_PORT` in `.env.production` and use the same port in the host Caddy site block. Keep this port closed in the EC2 security group.
2. Use Docker Engine 28 or newer and Docker Compose 2.24.4 or newer. The override uses `!override` to replace the standalone port list. Docker Engine 28 fixes an older issue that could let hosts on the same layer-2 network reach loopback-published ports. [Docker port publishing](https://docs.docker.com/engine/network/port-publishing/) · [Compose override syntax](https://docs.docker.com/reference/compose-file/merge/#replace-value)
3. Use the existing secret settings above, including the real public DNS hostname. Use the same Compose project name and both files for subsequent lifecycle commands.

```sh
docker compose --env-file .env.production -p sap -f compose.yaml -f deploy/compose.shared-host.yaml config --quiet
docker compose --env-file .env.production -p sap -f compose.yaml -f deploy/compose.shared-host.yaml up -d --build --wait --wait-timeout 180
docker compose --env-file .env.production -p sap -f compose.yaml -f deploy/compose.shared-host.yaml ps
```

Add a separate site block to the existing host Caddy configuration. Substitute the actual hostname and port:

```caddyfile
sap.example.com {
    reverse_proxy 127.0.0.1:18080
}
```

The host Caddy must run on the host network for `127.0.0.1` to reach the published port. If it uses Docker bridge networking, inspect its network before adding the site. This upstream address assumes host-network access. Keep the existing `Host` header and forward the original `Authorization` header; the inner proxy preserves bearer authentication for the ESP route. Its HTTP listener is limited to the SAP hostname and deliberately sets the upstream scheme to HTTPS because public TLS terminates on the host. The inner proxy treats the host proxy as the client address. Use the outer proxy if per-client address information is needed.

Validate the full host Caddy configuration with its existing management procedure, then reload it without stopping existing sites. Repeat the public HTTPS and ESP checks above, confirm the existing site URLs still respond, and verify SAP's proxy port is unreachable externally. To roll back, remove the SAP site block, validate and reload the host Caddy configuration, and bring down only the `sap` project with both files. Keep its data volume for recovery.

## Temporary HTTP ESP route on the shared EC2 host

The owner explicitly enabled plain HTTP POST ingestion for ESP testing. [The host site snippet](../deploy/Caddyfile.ec2-site) accepts only POST `/api/esp/notifications` over HTTP and preserves token enforcement. All other HTTP requests redirect to HTTPS. The internal proxy normalizes the upstream scheme; this does not encrypt the external HTTP connection. Remove the explicit HTTP site block to restore HTTPS-only ingestion. This exception is host-specific; the standalone Compose configuration still redirects HTTP to HTTPS.
