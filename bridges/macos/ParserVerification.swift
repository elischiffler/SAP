import Foundation

func verifyParser() -> Bool {
  let uid: UInt32 = 0x0403_0201
  let command = Data([0, 1, 2, 3, 4, 0, 1, 0, 1, 3, 0, 4])
  let notice = ANCSNotice(Data([0, 0x04, 0, 0, 1, 2, 3, 4]))
  let response = Data([0, 1, 2, 3, 4, 0, 1, 0, 65, 1, 0, 0, 3, 1, 0, 66])
  let expected = NotificationFields(app: "A", title: "", body: "B")
  var pieces = AttributeResponse(uid: uid)
  for piece in response.dropLast() {
    guard pieces.append(Data([piece])) == .partial else {
      print("Fragmented response test failed.")
      return false
    }
  }
  var wrongUID = AttributeResponse(uid: 0)
  var extraBytes = AttributeResponse(uid: uid)
  var badLength = AttributeResponse(uid: uid)
  let notification = PagerNotification(
    NotificationFields(app: "", title: "", body: ""), receivedAt: Date())
  guard attributeRequest(for: uid) == command,
    notice?.uid == uid, notice?.isPreexisting == true,
    ANCSNotice(Data([0])) == nil,
    pieces.append(Data(response.suffix(1))) == .complete(expected),
    wrongUID.append(response) == .invalid,
    extraBytes.append(response + Data([0])) == .invalid,
    badLength.append(Data([0, 1, 2, 3, 4, 0, 0, 1])) == .invalid,
    notification.app == "iPhone", notification.contentHidden
  else {
    print("ANCS parser self-test failed.")
    return false
  }
  print("ANCS parser self-test passed.")
  return true
}
