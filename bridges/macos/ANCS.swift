import Foundation

struct ANCSNotice {
  let kind: UInt8
  let isPreexisting: Bool
  let uid: UInt32

  init?(_ data: Data) {
    let bytes = Array(data)
    guard bytes.count == 8, bytes[0] <= 2 else { return nil }
    kind = bytes[0]
    isPreexisting = bytes[1] & 0x04 != 0
    uid = decodeUID(bytes, at: 4)
  }
}

private func decodeUID(_ bytes: [UInt8], at offset: Int) -> UInt32 {
  UInt32(bytes[offset])
    | UInt32(bytes[offset + 1]) << 8
    | UInt32(bytes[offset + 2]) << 16
    | UInt32(bytes[offset + 3]) << 24
}

private struct Attribute {
  let id: UInt8
  let byteLimit: Int
  let specifiesLimit: Bool
}

private let attributes = [
  Attribute(id: 0, byteLimit: 255, specifiesLimit: false),
  Attribute(id: 1, byteLimit: 256, specifiesLimit: true),
  Attribute(id: 3, byteLimit: 1024, specifiesLimit: true),
]

func attributeRequest(for uid: UInt32) -> Data {
  var request = Data([0])  // Get Notification Attributes.
  for shift in [0, 8, 16, 24] {
    request.append(UInt8(truncatingIfNeeded: uid >> shift))
  }
  for attribute in attributes {
    request.append(attribute.id)
    if attribute.specifiesLimit {
      request.append(UInt8(truncatingIfNeeded: attribute.byteLimit))
      request.append(UInt8(attribute.byteLimit >> 8))
    }
  }
  return request
}

struct NotificationFields: Equatable {
  let app: String
  let title: String
  let body: String
}

struct AttributeResponse {
  enum Result: Equatable {
    case partial
    case invalid
    case complete(NotificationFields)
  }

  let uid: UInt32
  private var bytes: [UInt8] = []
  private static let maximumBytes = 5 + attributes.reduce(0) { $0 + 3 + $1.byteLimit }

  init(uid: UInt32) {
    self.uid = uid
  }

  mutating func append(_ data: Data) -> Result {
    guard data.count <= Self.maximumBytes - bytes.count else { return .invalid }
    bytes.append(contentsOf: data)
    guard bytes.count >= 5 else { return .partial }
    guard bytes[0] == 0, decodeUID(bytes, at: 1) == uid else { return .invalid }

    var offset = 5
    var fields: [String] = []
    for attribute in attributes {
      guard bytes.count >= offset + 3 else { return .partial }
      let size = Int(bytes[offset + 1]) | Int(bytes[offset + 2]) << 8
      guard bytes[offset] == attribute.id, size <= attribute.byteLimit else { return .invalid }
      let start = offset + 3
      offset = start + size
      guard bytes.count >= offset else { return .partial }
      fields.append(String(decoding: bytes[start..<offset], as: UTF8.self))
    }

    guard bytes.count == offset else { return .invalid }
    return .complete(NotificationFields(app: fields[0], title: fields[1], body: fields[2]))
  }
}

struct PagerNotification: Encodable {
  let eventID = UUID()
  let app: String
  let title: String
  let body: String
  let receivedAt: Date
  let contentHidden: Bool

  private enum CodingKeys: String, CodingKey {
    case eventID = "event_id"
    case app, title, body
    case receivedAt = "received_at"
    case contentHidden = "content_hidden"
  }

  init(_ fields: NotificationFields, receivedAt: Date) {
    let app = fields.app.trimmingCharacters(in: .whitespacesAndNewlines)
    self.app =
      app.isEmpty ? "iPhone" : String(String.UnicodeScalarView(app.unicodeScalars.prefix(100)))
    title = fields.title
    body = fields.body
    self.receivedAt = receivedAt
    contentHidden =
      fields.title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
      && fields.body.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
  }
}
