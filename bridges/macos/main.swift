import Darwin
import Foundation

let usage = """
  SAP Bluetooth Probe
    --scan            Scan 15 seconds for ANCS and list connected ANCS matches.
    --scan-all        Scan 15 seconds for all discoverable BLE peers.
    --device UUID     Connect to one selected peer and try forwarding new notifications.
    --self-test       Verify ANCS parser without Bluetooth.
  """

switch Array(CommandLine.arguments.dropFirst()) {
case [], ["--help"], ["-h"]:
  print(usage)
case ["--scan"]:
  exit(Probe(mode: .scan(all: false)).run())
case ["--scan-all"]:
  exit(Probe(mode: .scan(all: true)).run())
case ["--self-test"]:
  exit(verifyParser() ? 0 : 1)
case let arguments where arguments.count == 2 && arguments[0] == "--device":
  guard let id = UUID(uuidString: arguments[1]) else {
    print("Provide the UUID printed for your iPhone.")
    exit(64)
  }
  exit(Probe(mode: .device(id)).run())
default:
  print(usage)
  exit(64)
}
