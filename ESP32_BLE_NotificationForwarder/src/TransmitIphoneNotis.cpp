// iPhone --BLE (ANCS)--> ESP32-C3 --Wi-Fi/HTTP POST--> SERVER_URL
#include <Arduino.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <WiFiClientSecure.h>
#include <NimBLEDevice.h>
#include "config.h"
#include "notification_limits.h"

static const NimBLEUUID ANCS_SVC("7905F431-B5CE-4E99-A40F-4B1E122D00D0");
static const NimBLEUUID NS_UUID("9FBF120D-6301-42D9-8C58-25E699A21DBD");  // Notification Source
static const NimBLEUUID CP_UUID("69D1D8F3-45E1-49A8-9821-9BBDFDAAD9D9");  // Control Point
static const NimBLEUUID DS_UUID("22EAC6E9-24D6-4BB5-BE44-B36ACE7C7BFB");  // Data Source

struct Noti { char app[64]; char title[64]; char subtitle[64]; char message[kMessageBytes + 1]; char date[20]; };

// BLE callbacks -> loop() handoff. Single producer / single consumer rings; full = drop.
static volatile uint32_t uidQ[8];
static volatile uint8_t uidHead = 0, uidTail = 0;
static Noti notiQ[4];
static volatile uint8_t notiHead = 0, notiTail = 0;

static NimBLEServer* server;
static NimBLERemoteCharacteristic* controlPoint = nullptr;
static volatile uint16_t connHandle = BLE_HS_CONN_HANDLE_NONE;
static volatile bool needSetup = false;  // link encrypted, ANCS not yet subscribed
static volatile bool ancsReady = false;
static uint32_t setupAt = 0;  // earliest millis() to run setupAncs()

// Data Source reassembly (one Get Notification Attributes request in flight at a time)
// Bounded reassembly includes five attribute headers and source labels.
static uint8_t dsBuf[kResponseBytes];
static volatile size_t dsLen = 0;
static volatile bool waiting = false;
static uint32_t requestedAt = 0, pendingUid = 0;

// ---------- ANCS ----------
static void onNotificationSource(NimBLERemoteCharacteristic*, uint8_t* d, size_t n, bool) {
  // EventID, EventFlags, CategoryID, CategoryCount, NotificationUID (LE)
  if (n < 8 || d[0] != 0 /* Added */ || (d[1] & 0x04) /* PreExisting */) return;
  uint8_t next = (uidHead + 1) % 8;
  if (next == uidTail) return;
  uidQ[uidHead] = d[4] | (d[5] << 8) | (d[6] << 16) | ((uint32_t)d[7] << 24);
  uidHead = next;
}

// Response: CommandID(0), UID(4), then 5x [AttrID(1), Len(2 LE), Data]. Returns once complete.
static void tryParse() {
  if (dsLen < 5) return;
  uint32_t uid = dsBuf[1] | (dsBuf[2] << 8) | (dsBuf[3] << 16) | ((uint32_t)dsBuf[4] << 24);
  if (dsBuf[0] != 0 || uid != pendingUid) { dsLen = 0; return; }  // stale/garbage
  // Keep the larger notification off the BLE task stack. Callback-owned scratch.
  static Noti nt;
  memset(&nt, 0, sizeof nt);
  size_t p = 5;
  for (int got = 0; got < 5; got++) {
    if (p + 3 > dsLen) return;  // wait for more packets
    uint8_t id = dsBuf[p];
    uint16_t len = dsBuf[p + 1] | (dsBuf[p + 2] << 8);
    p += 3;
    if (p + len > dsLen) return;
    char* dst = nullptr; size_t cap = 0;
    switch (id) {
      case 0: dst = nt.app; cap = sizeof nt.app; break;
      case 1: dst = nt.title; cap = sizeof nt.title; break;
      case 2: dst = nt.subtitle; cap = sizeof nt.subtitle; break;
      case 3: dst = nt.message; cap = sizeof nt.message; break;
      case 5: dst = nt.date; cap = sizeof nt.date; break;
    }
    if (dst) { size_t m = utf8PrefixLength(dsBuf + p, len, cap - 1); memcpy(dst, dsBuf + p, m); dst[m] = 0; }
    p += len;
  }
  dsLen = 0;
  waiting = false;
  uint8_t next = (notiHead + 1) % 4;
  if (next == notiTail) { Serial.println("[ANCS] pending list full, dropped"); return; }
  notiQ[notiHead] = nt;
  notiHead = next;
}

static void onDataSource(NimBLERemoteCharacteristic*, uint8_t* d, size_t n, bool) {
  if (!waiting) return;
  if (n > sizeof dsBuf - dsLen) {
    dsLen = 0; waiting = false;
    Serial.println("[ANCS] response too large, dropped");
    return;
  }
  memcpy(dsBuf + dsLen, d, n);
  dsLen += n;
  tryParse();
}

static void requestAttributes(uint32_t uid) {
  uint8_t cmd[] = {
    0,  // CommandIDGetNotificationAttributes
    (uint8_t)uid, (uint8_t)(uid >> 8), (uint8_t)(uid >> 16), (uint8_t)(uid >> 24),
    0,                                           // App Identifier
    1, sizeof(Noti::title) - 1, 0,               // Title, max len
    2, sizeof(Noti::subtitle) - 1, 0,            // Subtitle, max len
    3, (uint8_t)(kMessageBytes & 0xff), (uint8_t)(kMessageBytes >> 8), // 16-bit LE
    5,                                           // Date
  };
  dsLen = 0;
  pendingUid = uid;
  requestedAt = millis();
  waiting = true;  // set before the (blocking) write: the response can arrive before it returns
  if (!controlPoint->writeValue(cmd, sizeof cmd, true)) { waiting = false; Serial.println("[ANCS] control point write failed"); }
}

static bool setupAncs() {
  NimBLEClient* c = server->getClient(connHandle);
  NimBLERemoteService* svc = c ? c->getService(ANCS_SVC) : nullptr;
  if (!svc) { Serial.println("[ANCS] service not found (is 'Share System Notifications' on?)"); return false; }
  NimBLERemoteCharacteristic* ns = svc->getCharacteristic(NS_UUID);
  NimBLERemoteCharacteristic* cp = svc->getCharacteristic(CP_UUID);
  NimBLERemoteCharacteristic* ds = svc->getCharacteristic(DS_UUID);
  if (!ns || !cp || !ds) { Serial.println("[ANCS] characteristic missing"); return false; }
  controlPoint = cp;
  // Data Source first so no attribute response is missed.
  if (!ds->subscribe(true, onDataSource) || !ns->subscribe(true, onNotificationSource)) {
    Serial.println("[ANCS] subscribe failed");
    return false;
  }
  Serial.println("[ANCS] ready");
  return true;
}

class ServerCallbacks : public NimBLEServerCallbacks {
  void onConnect(NimBLEServer*, NimBLEConnInfo& ci) override {
    Serial.printf("[BLE] connected %s\n", ci.getAddress().toString().c_str());
    connHandle = ci.getConnHandle();
    NimBLEDevice::startSecurity(ci.getConnHandle());  // ANCS requires an encrypted link
  }
  void onAuthenticationComplete(NimBLEConnInfo& ci) override {
    if (!ci.isEncrypted()) {
      Serial.println("[BLE] pairing failed, disconnecting");
      server->disconnect(ci.getConnHandle());
      return;
    }
    Serial.println("[BLE] link encrypted");
    setupAt = millis() + 500;
    needSetup = true;
  }
  void onDisconnect(NimBLEServer*, NimBLEConnInfo&, int reason) override {
    Serial.printf("[BLE] disconnected (reason %d), advertising\n", reason);
    connHandle = BLE_HS_CONN_HANDLE_NONE;
    needSetup = false; ancsReady = false; waiting = false;
    NimBLEDevice::startAdvertising();
  }
};

static void startBle() {
  NimBLEDevice::init("ANCS-Forwarder");
  NimBLEDevice::setSecurityAuth(true, false, true);  // bonding, no MITM, secure connections
  server = NimBLEDevice::createServer();
  server->setCallbacks(new ServerCallbacks());

  NimBLEAdvertisementData adv;
  adv.setFlags(BLE_HS_ADV_F_DISC_GEN | BLE_HS_ADV_F_BREDR_UNSUP);
  // 128-bit service solicitation (AD type 0x15) for ANCS, UUID little-endian
  const uint8_t solicit[] = {17, 0x15, 0xD0, 0x00, 0x2D, 0x12, 0x1E, 0x4B, 0x0F, 0xA4,
                             0x99, 0x4E, 0xCE, 0xB5, 0x31, 0xF4, 0x05, 0x79};
  adv.addData(solicit, sizeof solicit);
  NimBLEAdvertisementData scan;
  scan.setName("ANCS-Forwarder");

  NimBLEAdvertising* a = NimBLEDevice::getAdvertising();
  a->enableScanResponse(true);
  a->setAdvertisementData(adv);
  a->setScanResponseData(scan);
  a->start();
  Serial.println("[BLE] advertising");
}

// ---------- HTTP ----------
static void addField(String& out, const char* key, const char* val) {
  out += out.length() > 1 ? ",\"" : "\"";
  out += key;
  out += "\":\"";
  for (const char* s = val; *s; s++) {
    if (*s == '"' || *s == '\\') { out += '\\'; out += *s; }
    else if ((uint8_t)*s < 0x20) { char b[7]; snprintf(b, sizeof b, "\\u%04x", *s); out += b; }
    else out += *s;
  }
  out += '"';
}

static void postNoti(const Noti& n) {
  if (WiFi.status() != WL_CONNECTED) { Serial.println("[HTTP] no Wi-Fi, dropped"); return; }
  String body = "{";
  addField(body, "app", n.app);
  addField(body, "title", n.title);
  addField(body, "subtitle", n.subtitle);
  addField(body, "message", n.message);
  addField(body, "date", n.date);
  body += "}";
  WiFiClientSecure tls;
  tls.setInsecure();  // MVP: no certificate check
  HTTPClient http;
  http.setTimeout(5000);
  http.begin(tls, SERVER_URL);
  http.addHeader("Content-Type", "application/json");
  http.addHeader("Authorization", "Bearer " INGEST_TOKEN);
  int code = http.POST(body);
  Serial.printf("[HTTP] POST -> %d\n", code);
  if (code >= 400) Serial.println(http.getString());  // server's error detail
  http.end();
}

// ---------- main ----------
void setup() {
  Serial.begin(115200);
  delay(1000);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  startBle();
}

void loop() {
  static uint32_t lastWifiTry = 0;
  static bool wifiUp = false;
  if (WiFi.status() == WL_CONNECTED) {
    if (!wifiUp) Serial.printf("[WiFi] connected %s\n", WiFi.localIP().toString().c_str());
    wifiUp = true;
  } else {
    if (wifiUp) Serial.println("[WiFi] lost");
    wifiUp = false;
    if (millis() - lastWifiTry > 10000) { lastWifiTry = millis(); WiFi.disconnect(); WiFi.begin(WIFI_SSID, WIFI_PASS); }
  }

  // GATT discovery/subscribe blocks, so it runs here rather than in a BLE callback.
  if (needSetup && (int32_t)(millis() - setupAt) >= 0) {
    ancsReady = setupAncs();
    needSetup = !ancsReady && connHandle != BLE_HS_CONN_HANDLE_NONE;  // retry every 2 s while connected
    setupAt = millis() + 2000;
  }

  if (waiting && millis() - requestedAt > 10000) { Serial.println("[ANCS] attribute request timed out"); waiting = false; }
  if (ancsReady && !waiting && uidTail != uidHead) {
    uint32_t uid = uidQ[uidTail];
    uidTail = (uidTail + 1) % 8;
    requestAttributes(uid);
  }

  if (notiTail != notiHead) {
    const Noti& n = notiQ[notiTail];
    Serial.printf("[ANCS] %s | %s | %s | %s | %s\n", n.app, n.title, n.subtitle, n.message, n.date);
    postNoti(n);
    notiTail = (notiTail + 1) % 4;
  }
  delay(10);
}
