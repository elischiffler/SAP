# Mac Bluetooth capture experiment

The native probe tests whether a selected iPhone exposes an authorized ANCS connection to this Mac. It is not a proven replacement for the ESP32. The web page simulates the audio pager; this utility tests the separate phone-to-server input path.

## Result and limitation

The initial 15-second ANCS scan ran successfully on this Mac and found no matching advertised or connected service. No iPhone connection or notification capture was verified.

Public macOS Core Bluetooth does not expose the standard ESP accessory flow: peripheral advertising supports a local name and service UUIDs, not an ANCS service solicitation, and a remote `CBCentral` does not offer GATT discovery/subscription methods. The installed macOS SDK marks `CBConnectPeripheralOptionRequiresANCS` unavailable. This probe acts as a BLE central; success requires the selected iPhone to be connectable in that role, publish ANCS, and authorize access. Ordinary pairing alone does not establish those conditions.

The practical next integration is **iPhone → ESP32 → Mac server → Mac speakers**. The Pi and EC2 can follow after real input is working.

References: [Apple ANCS specification](https://developer.apple.com/library/archive/documentation/CoreBluetooth/Reference/AppleNotificationCenterServiceSpecification/Specification/Specification.html), [supported peripheral advertising](https://developer.apple.com/documentation/corebluetooth/cbperipheralmanager/startadvertising(_:)), [ANCS authorization explanation](https://developer.apple.com/videos/play/wwdc2019/901/?time=556).

## Optional diagnostic commands

Run from the project folder with the local server running separately:

```sh
./scripts/run_bluetooth.sh --scan
./scripts/run_bluetooth.sh --scan-all
./scripts/run_bluetooth.sh --device YOUR_IPHONE_UUID
```

The first command scans ANCS for 15 seconds; the optional second command lists other discoverable BLE peers. Device names are unauthenticated labels. Select only a UUID you know belongs to your own iPhone. Keep Bluetooth enabled, unlock the iPhone, and review any macOS/iPhone permission prompts offered. Connection alone is not success: wait for `ANCS subscription active`, generate a new test notification, and verify `One iPhone notification reached the local pager` plus the actual item on the testing page. The session stops after ten minutes; Ctrl-C stops it earlier.

## Implemented boundaries

- Attribute reads only: no notification action commands, replies, call handling, or dismissals.
- Bounded fragmented-response parser, one attribute request at a time, five-second attribute timeout, and ten waiting notifications maximum.
- App identifier, title, and preview are forwarded. ANCS has no universal contact field, so the bridge does not invent a contact from a title or label all Messages traffic as iMessage.
- Preexisting notifications and modified events are skipped. Removals cancel pending attribute work when possible; already forwarded items are not withdrawn from the server. This is not a complete lifecycle synchronizer.
- Posts go only to `127.0.0.1:8000`, with redirects, proxies, cookies, and caching disabled. No notification contents or keys are logged by the bridge. The server uses its configured GPT and TTS providers.
- No durable ingress retries: a failed post or full backlog is reported and skipped. The separate server-to-pager queue retains durable one-message lease/ACK delivery.

The launcher builds a locally signed app in `~/Library/Caches/local.sap.bluetooth-probe/`. Swift 6 compilation and offline parser tests passed. To check parsing without Bluetooth:

```sh
./scripts/run_bluetooth.sh --self-test
```
