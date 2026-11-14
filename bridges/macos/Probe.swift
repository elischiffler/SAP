import CoreBluetooth
import Foundation

enum ProbeMode {
  case scan(all: Bool)
  case device(UUID)
}

@MainActor private let serviceID = CBUUID(string: "7905F431-B5CE-4E99-A40F-4B1E122D00D0")
@MainActor private let notificationID = CBUUID(string: "9FBF120D-6301-42D9-8C58-25E699A21DBD")
@MainActor private let controlID = CBUUID(string: "69D1D8F3-45E1-49A8-9821-9BBDFDAAD9D9")
@MainActor private let dataID = CBUUID(string: "22EAC6E9-24D6-4BB5-BE44-B36ACE7C7BFB")

private final class NoRedirects: NSObject, URLSessionTaskDelegate {
  func urlSession(
    _ session: URLSession, task: URLSessionTask,
    willPerformHTTPRedirection response: HTTPURLResponse,
    newRequest request: URLRequest, completionHandler: @escaping @Sendable (URLRequest?) -> Void
  ) {
    completionHandler(nil)
  }
}

@MainActor
final class Probe: NSObject, @preconcurrency CBCentralManagerDelegate,
  @preconcurrency CBPeripheralDelegate
{
  private struct Pending {
    let uid: UInt32
    let receivedAt: Date
  }
  private struct Fetch {
    let notice: Pending
    var parser: AttributeResponse
    var acknowledged = false
    var fields: NotificationFields?
    var removed = false
  }

  private let mode: ProbeMode
  private let http: URLSession
  private var manager: CBCentralManager?
  private var peer: CBPeripheral?
  private var status: Int32?
  private var started = false
  private var deadline = Date.distantFuture
  private var found: Set<UUID> = []
  private var notificationSource: CBCharacteristic?
  private var controlPoint: CBCharacteristic?
  private var acceptingNotices = false
  private var subscribed = false
  private var pending: [Pending] = []
  private var fetch: Fetch?
  private var fetchDeadline = Date.distantFuture
  private var posting = false

  init(mode: ProbeMode) {
    self.mode = mode
    let configuration = URLSessionConfiguration.ephemeral
    configuration.urlCache = nil
    configuration.httpCookieStorage = nil
    configuration.urlCredentialStorage = nil
    configuration.connectionProxyDictionary = [:]
    configuration.timeoutIntervalForRequest = 5
    configuration.timeoutIntervalForResource = 8
    http = URLSession(configuration: configuration, delegate: NoRedirects(), delegateQueue: nil)
  }

  func run() -> Int32 {
    deadline = Date().addingTimeInterval(30)
    print("Waiting for macOS Bluetooth. Allow access if prompted.")
    manager = CBCentralManager(delegate: self, queue: nil)
    while status == nil {
      RunLoop.main.run(until: Date().addingTimeInterval(0.1))
      if Date() >= fetchDeadline {
        finish(
          1, "The iPhone did not finish its attribute response. Restart to try another session.")
      } else if Date() >= deadline {
        elapsed()
      }
    }
    return status ?? 1
  }

  private func elapsed() {
    switch mode {
    case .scan:
      if !started {
        finish(1, "Bluetooth did not become ready before the setup timeout.")
      } else if found.isEmpty {
        finish(
          2,
          "No matching peers appeared. This does not establish whether the iPhone can expose ANCS to this Mac."
        )
      } else {
        finish(0, "Scan finished. Choose only your own iPhone with --device <UUID>.")
      }
    case .device:
      if subscribed {
        finish(0, "The 10-minute notification session ended.")
      } else {
        if peer == nil {
          finish(2, "The selected UUID did not appear during discovery.")
        } else {
          finish(1, "The connection or ANCS subscription did not finish before the setup timeout.")
        }
      }
    }
  }

  private func finish(_ code: Int32, _ message: String) {
    guard status == nil else { return }
    status = code
    print(message)
    http.invalidateAndCancel()
    if manager?.state == .poweredOn {
      manager?.stopScan()
      if let peer { manager?.cancelPeripheralConnection(peer) }
    }
  }

  func centralManagerDidUpdateState(_ central: CBCentralManager) {
    guard status == nil else { return }
    switch central.state {
    case .poweredOn:
      guard !started else { return }
      started = true
      start(using: central)
    case .unauthorized:
      finish(
        1, "Bluetooth permission is required in System Settings → Privacy & Security → Bluetooth.")
    case .poweredOff:
      finish(1, "Bluetooth is off. Turn it on in System Settings and rerun the probe.")
    case .unsupported:
      finish(1, "Bluetooth LE is unavailable on this Mac.")
    case .unknown, .resetting:
      if started {
        finish(1, "The Bluetooth session was interrupted. Rerun the probe.")
      }
    @unknown default:
      finish(1, "The Bluetooth state is unavailable.")
    }
  }

  private func start(using central: CBCentralManager) {
    let connected = central.retrieveConnectedPeripherals(withServices: [serviceID])
    switch mode {
    case .scan(let all):
      print(
        all
          ? "Scanning for nearby BLE peers for 15 seconds."
          : "Scanning for advertised ANCS for 15 seconds.")
      for peripheral in connected {
        announce(peripheral, name: peripheral.name, observation: "Connected ANCS match")
      }
      deadline = Date().addingTimeInterval(15)
      central.scanForPeripherals(withServices: all ? nil : [serviceID])
    case .device(let id):
      if let selected = connected.first(where: { $0.identifier == id })
        ?? central.retrievePeripherals(withIdentifiers: [id]).first
      {
        connect(selected, using: central)
      } else {
        print("Looking for the selected peer for 15 seconds.")
        deadline = Date().addingTimeInterval(15)
        central.scanForPeripherals(withServices: nil)
      }
    }
  }

  func centralManager(
    _ central: CBCentralManager, didDiscover peripheral: CBPeripheral,
    advertisementData: [String: Any], rssi: NSNumber
  ) {
    guard status == nil else { return }
    switch mode {
    case .scan:
      let services = advertisementData[CBAdvertisementDataServiceUUIDsKey] as? [CBUUID] ?? []
      let observation = services.contains(serviceID) ? "Advertised ANCS" : "BLE discovery"
      let name = advertisementData[CBAdvertisementDataLocalNameKey] as? String ?? peripheral.name
      announce(peripheral, name: name, observation: observation)
    case .device(let id):
      if peripheral.identifier == id, peer == nil {
        connect(peripheral, using: central)
      }
    }
  }

  private func announce(_ peripheral: CBPeripheral, name: String?, observation: String) {
    guard found.count < 50, found.insert(peripheral.identifier).inserted else { return }
    let clean = (name ?? "").unicodeScalars.filter {
      switch $0.properties.generalCategory {
      case .control, .format, .lineSeparator, .paragraphSeparator: false
      default: true
      }
    }
    let label = String(String.UnicodeScalarView(clean.prefix(60)))
    print(
      "\(peripheral.identifier.uuidString)  \(label.isEmpty ? "Unnamed" : label)  [\(observation)]")
  }

  private func connect(_ peripheral: CBPeripheral, using central: CBCentralManager) {
    central.stopScan()
    peer = peripheral
    peripheral.delegate = self
    deadline = Date().addingTimeInterval(30)
    print("Connecting to the selected device. Unlock your iPhone and review any sharing prompt.")
    central.connect(peripheral)
  }

  func centralManager(_ central: CBCentralManager, didConnect peripheral: CBPeripheral) {
    guard status == nil, peer == peripheral else { return }
    print("Bluetooth connection established. Looking for the iPhone notification service.")
    peripheral.discoverServices([serviceID])
  }

  func centralManager(
    _ central: CBCentralManager, didFailToConnect peripheral: CBPeripheral, error: Error?
  ) {
    finish(1, "The selected Bluetooth device did not accept the connection.")
  }

  func centralManager(
    _ central: CBCentralManager, didDisconnectPeripheral peripheral: CBPeripheral, error: Error?
  ) {
    finish(1, "The selected Bluetooth device disconnected. Rerun the probe to reconnect.")
  }

  func peripheral(_ peripheral: CBPeripheral, didDiscoverServices error: Error?) {
    guard status == nil, peer == peripheral else { return }
    guard error == nil, let service = peripheral.services?.first(where: { $0.uuid == serviceID })
    else {
      finish(2, "The selected device connected but did not expose ANCS to this Mac.")
      return
    }
    peripheral.discoverCharacteristics([notificationID, controlID, dataID], for: service)
  }

  func peripheral(
    _ peripheral: CBPeripheral, didDiscoverCharacteristicsFor service: CBService, error: Error?
  ) {
    guard status == nil, peer == peripheral else { return }
    guard error == nil,
      let characteristics = service.characteristics,
      let data = characteristics.first(where: {
        $0.uuid == dataID && $0.properties.contains(.notify)
      }),
      let notification = characteristics.first(where: {
        $0.uuid == notificationID && $0.properties.contains(.notify)
      }),
      let control = characteristics.first(where: {
        $0.uuid == controlID && $0.properties.contains(.write)
      })
    else {
      finish(
        2, "ANCS was visible, but its notification attribute characteristics were unavailable.")
      return
    }
    notificationSource = notification
    controlPoint = control
    peripheral.setNotifyValue(true, for: data)
  }

  func peripheral(
    _ peripheral: CBPeripheral, didUpdateNotificationStateFor characteristic: CBCharacteristic,
    error: Error?
  ) {
    guard status == nil, peer == peripheral else { return }
    guard error == nil, characteristic.isNotifying else {
      finish(
        2,
        "ANCS subscription failed. Check iPhone notification-sharing authorization if it was offered."
      )
      return
    }
    if characteristic.uuid == dataID, let notificationSource {
      acceptingNotices = true
      peripheral.setNotifyValue(true, for: notificationSource)
    } else if characteristic.uuid == notificationID {
      subscribed = true
      deadline = Date().addingTimeInterval(600)
      print(
        "ANCS subscription active. Send one new test notification to your iPhone. Ctrl-C stops the bridge."
      )
    }
  }

  func peripheral(_ peripheral: CBPeripheral, didModifyServices invalidatedServices: [CBService]) {
    guard status == nil, peer == peripheral else { return }
    if invalidatedServices.contains(where: { $0.uuid == serviceID }) {
      finish(2, "The iPhone removed its notification service. Rerun the probe to check again.")
    }
  }

  func peripheral(
    _ peripheral: CBPeripheral, didUpdateValueFor characteristic: CBCharacteristic, error: Error?
  ) {
    guard status == nil, peer == peripheral else { return }
    guard error == nil, let data = characteristic.value else {
      finish(1, "The notification connection returned a Bluetooth read error.")
      return
    }
    if characteristic.uuid == notificationID, acceptingNotices, let notice = ANCSNotice(data) {
      receive(notice)
    } else if characteristic.uuid == dataID, let current = fetch {
      if current.fields != nil {
        finish(1, "Unexpected duplicate attribute data arrived. Restart the bridge to retry.")
        return
      }
      let result = fetch?.parser.append(data)
      switch result {
      case .partial, nil: break
      case .invalid:
        finish(1, "The notification attribute response was malformed. Restart the bridge to retry.")
      case .complete(let fields):
        fetch?.fields = fields
        finishFetch()
      }
    }
  }

  private func receive(_ notice: ANCSNotice) {
    if notice.kind == 2 {
      pending.removeAll { $0.uid == notice.uid }
      if fetch?.notice.uid == notice.uid { fetch?.removed = true }
      return
    }
    guard notice.kind == 0, !notice.isPreexisting,
      !pending.contains(where: { $0.uid == notice.uid }), fetch?.notice.uid != notice.uid
    else { return }
    guard pending.count < 10 else {
      print("Notification backlog is full. An incoming notification was skipped.")
      return
    }
    pending.append(Pending(uid: notice.uid, receivedAt: Date()))
    startFetch()
  }

  private func startFetch() {
    guard !posting, fetch == nil, !pending.isEmpty, let peer, let controlPoint else { return }
    let notice = pending.removeFirst()
    fetch = Fetch(notice: notice, parser: AttributeResponse(uid: notice.uid))
    fetchDeadline = Date().addingTimeInterval(5)
    peer.writeValue(attributeRequest(for: notice.uid), for: controlPoint, type: .withResponse)
  }

  func peripheral(
    _ peripheral: CBPeripheral, didWriteValueFor characteristic: CBCharacteristic, error: Error?
  ) {
    guard status == nil, peer == peripheral, characteristic.uuid == controlID, fetch != nil else {
      return
    }
    guard error == nil else {
      print("The iPhone did not grant access to one notification’s attributes.")
      fetch = nil
      fetchDeadline = .distantFuture
      startFetch()
      return
    }
    fetch?.acknowledged = true
    finishFetch()
  }

  private func finishFetch() {
    guard let current = fetch, current.acknowledged, let fields = current.fields else { return }
    fetch = nil
    fetchDeadline = .distantFuture
    if current.removed {
      startFetch()
    } else {
      post(PagerNotification(fields, receivedAt: current.notice.receivedAt))
    }
  }

  private func post(_ item: PagerNotification) {
    let encoder = JSONEncoder()
    encoder.dateEncodingStrategy = .iso8601
    guard let payload = try? encoder.encode(item),
      let endpoint = URL(string: "http://127.0.0.1:8000/api/notifications")
    else {
      finish(1, "The notification could not be encoded for the local pager.")
      return
    }
    var request = URLRequest(url: endpoint)
    request.httpMethod = "POST"
    request.setValue("application/json", forHTTPHeaderField: "Content-Type")
    request.httpBody = payload
    posting = true
    http.dataTask(with: request) { [weak self] _, response, _ in
      let code = (response as? HTTPURLResponse)?.statusCode
      Task { @MainActor [weak self] in
        guard let self, status == nil else { return }
        switch code {
        case 202: print("One iPhone notification reached the local pager.")
        case 429: print("The local pager queue is full. One notification was skipped.")
        default: print("The local pager did not accept a notification. Check that it is running.")
        }
        posting = false
        startFetch()
      }
    }.resume()
  }
}
