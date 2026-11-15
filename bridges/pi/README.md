# Raspberry Pi client

First setup on Raspberry Pi OS. The installer creates `sap-pager.service` and a
dedicated service user, enables boot startup, and restarts/verifies the service.
It refuses to overwrite an existing installation. It installs GPIO, HTTP and
ALSA playback dependencies without editing audio, boot or network configuration.
The service explicitly uses the lgpio driver and its writable state directory
as the working directory, allowing lgpio to create its notification FIFO.

For an existing installation, copy `client.py`, `led.py`, `download_only.py`,
and `update.sh` into one directory and run `sudo bash update.sh` there. This
backs up/replaces code and restarts the existing service without replacing its
GPIO/audio configuration or pending playback acknowledgment.

## Installation

Copy this directory to the Pi, then run there:

```sh
cd ~/sap-pager-install
sudo bash install.sh
```

Expected wiring uses **BCM** numbering:

- Button: GPIO17 (physical pin 11) to ground, internal pull-up, 50 ms debounce.
- LED: GPIO27 (physical pin 13) through a 220-ohm resistor, returning to ground.

Use `/etc/default/sap-pager` for pin overrides or `PAGER_ALSA_DEVICE`. Audio uses
real `aplay` playback, not a stub. The default is the system ALSA output; a
Pi Zero 2 W requires an attached/configured audio output (for example USB audio
or an I2S DAC). This client cannot make an unconfigured speaker functional.
List devices without playing anything using `aplay -l` and `aplay -L`.

## Behavior

HTTPS with certificate verification, no token, server
`https://sap.elischiffler.dev`, polling every 3 seconds after each poll completes.
Only literal `led_on: true` lights the LED. Failed polls turn it off and log the
error. Button presses do not independently clear the LED.

Startup and background polling never download, play or ACK anything. One press
fetches fresh status and handles only its first item. While busy, presses are
discarded. Audio requires HTTP 200, a complete validated PCM WAV, at most
5,000,000 bytes and 45 seconds. No ranges or redirects are used. There are
5-second network inactivity timeouts, an 8-second status/ACK deadline, a
20-second download deadline and a 50-second playback deadline. HTTP 409 refreshes
status and waits for another press.

Only a successful `aplay` exit creates the durable ACK-pending journal. ACK
failure retains it across restarts. The next press retries only that ACK, never
also plays a new item. Rejected/expired ACKs are explicitly logged and status is
refreshed; a subsequent press can request the offered item again. The client
does not report rejected ACKs as successful completion.

The journal uses atomic replacement and file/directory fsync. As with any
external audio device, power loss between actual playback and journal persistence
cannot guarantee exactly-once playback. A malformed journal stops startup for
inspection rather than silently replaying. Disk errors retain the pending ID in
memory and prevent another playback in that process.

One process lock and one button-operation lock prevent overlapping deliveries.
Only one temporary WAV is retained, removed after every attempt and on startup.
`/var/lib/sap-pager/pager.log` rotates at 1 MB with three backups. The pending
journal and lock also live in that directory. Startup/process errors and `aplay`
stderr can additionally be inspected in the system journal.

## Verification on the Pi

For an explicitly requested download-only test, install `download_only.py` beside
the client. Stop the service, run it as `sap-pager` with the client's venv, then
restart the service even if the test fails:

```sh
sudo bash -c 'set -e
trap "systemctl start sap-pager.service" EXIT
systemctl stop sap-pager.service
runuser -u sap-pager -- /opt/sap-pager/venv/bin/python /opt/sap-pager/download_only.py'
```

This downloads one real offered notification and validates/saves it as
`/var/lib/sap-pager/download-test/message.wav`. It does not play or ACK it. Each
test replaces the previous test file, and the process lock prevents overlap with
the service. An existing playback ACK journal blocks this test. The server
reserves the item for 90 seconds; without an ACK it becomes available again.
The normal button flow still fetches fresh status and downloads its offered item;
it does not consume this diagnostic file. The production Pi delivery panel shows
the speech text, message ID, server-side transfer state and a separate Pi download
receipt. After a complete WAV is validated and fsynced, the updated client posts
its transfer ID, byte count and SHA-256 to `/api/pi/downloaded`. The server validates
the active transfer and matching file before displaying “Downloaded on Pi”. This
is a report of a saved file at that time, not proof of audible playback or
indefinite local retention. Only `/ack` completes playback. Old clients remain
compatible but cannot confirm downloads. Receipt-network failures are logged;
the site does not falsely show confirmation. Rejected/expired receipts wait for
a later button press.

```sh
systemctl is-enabled sap-pager.service
systemctl is-active sap-pager.service
sudo tail -n 30 /var/lib/sap-pager/pager.log
sudo journalctl -u sap-pager.service -n 30 --no-pager
```

Expect `enabled`, `active`, and a startup log. Actual GPIO and speaker verification
requires the wired hardware and the owner's physical button press with a real
notification. Do not inject test notifications into production or download/ACK
queued notifications for installation testing.

Local automated tests use `httpx.MockTransport` and fake playback only:

```sh
python -m pytest tests/test_pi_client.py tests/test_pi_delivery.py -q
```
