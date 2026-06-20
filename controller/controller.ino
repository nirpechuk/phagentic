// Requires: ArduinoJson, Adafruit TCS34725, ESP32 BLE Arduino (install via Library Manager)
// Pins are assigned at runtime by the hub via the "configure" command — see hub/config.json.

#include <ArduinoJson.h>
#include <Wire.h>
#include <Adafruit_TCS34725.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLE2902.h>

// Nordic UART Service UUIDs
#define NUS_SERVICE_UUID "6E400001-B5A3-F393-E0A9-E50E24DCCA9E"
#define NUS_RX_UUID      "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"  // host → device
#define NUS_TX_UUID      "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"  // device → host

static Adafruit_TCS34725 tcs(TCS34725_INTEGRATIONTIME_2_4MS, TCS34725_GAIN_4X);
static bool tcsReady = false;

// ── Pin registry ─────────────────────────────────────────────────────
// Populated at runtime by the "configure" command; empty until the hub connects.
// isPwm=true  → LEDC PWM output (ledcWrite, 0-255)
// isPwm=false → plain digital output (digitalWrite)
#define MAX_PINS 16
struct PinDef { uint8_t pin; bool isPwm; };
static PinDef pins[MAX_PINS];
static int    pinCount = 0;

static BLECharacteristic* pTxChar  = nullptr;
static bool               bleCon   = false;
static String             rxBuf    = "";

// ── Protocol helpers ──────────────────────────────────────────────────

void sendJson(JsonDocument& doc) {
  if (!bleCon || !pTxChar) return;
  String out;
  serializeJson(doc, out);
  out += "\n";
  pTxChar->setValue(out.c_str());
  pTxChar->notify();
}

void sendError(const char* msg) {
  StaticJsonDocument<128> resp;
  resp["status"] = "error";
  resp["msg"]    = msg;
  sendJson(resp);
}

// ── Command dispatch ──────────────────────────────────────────────────

int pinIndex(uint8_t pin) {
  for (int i = 0; i < pinCount; i++)
    if (pins[i].pin == pin) return i;
  return -1;
}

// Register output pins from {"cmd":"configure","pins":[{"pin":18,"mode":"pwm"},...]},
// replacing any prior registry. Detaches previously-attached PWM pins first so the
// hub can safely re-send this on every reconnect.
void configurePins(JsonArrayConst spec) {
  for (int i = 0; i < pinCount; i++)
    if (pins[i].isPwm) ledcDetach(pins[i].pin);
  pinCount = 0;

  for (JsonObjectConst p : spec) {
    if (pinCount >= MAX_PINS) break;
    uint8_t pin = p["pin"];
    bool isPwm  = strcmp(p["mode"] | "pwm", "pwm") == 0;
    if (isPwm) ledcAttach(pin, 5000, 8);  // 5 kHz, 8-bit resolution (0-255)
    else       pinMode(pin, OUTPUT);
    pins[pinCount++] = { pin, isPwm };
  }
}

void handleCommand(JsonDocument& doc) {
  const char* cmd = doc["cmd"] | "";
  StaticJsonDocument<256> resp;
  resp["cmd"] = cmd;

  if (strcmp(cmd, "ping") == 0) {
    resp["status"] = "pong";
    sendJson(resp);

  } else if (strcmp(cmd, "configure") == 0) {
    configurePins(doc["pins"].as<JsonArrayConst>());
    resp["status"] = "ok"; resp["count"] = pinCount;
    sendJson(resp);

  } else if (strcmp(cmd, "set_pwm") == 0) {
    uint8_t pin   = doc["pin"];
    uint8_t value = doc["value"];
    int idx = pinIndex(pin);
    if (idx < 0)           { sendError("unknown_pin"); return; }
    if (!pins[idx].isPwm)  { sendError("not_pwm");     return; }
    ledcWrite(pin, value);
    resp["status"] = "ok"; resp["pin"] = pin; resp["value"] = value;
    sendJson(resp);

  } else if (strcmp(cmd, "set_digital") == 0) {
    uint8_t pin   = doc["pin"];
    uint8_t value = doc["value"];
    if (pinIndex(pin) < 0) { sendError("unknown_pin"); return; }
    digitalWrite(pin, value ? HIGH : LOW);
    resp["status"] = "ok"; resp["pin"] = pin; resp["value"] = value;
    sendJson(resp);

  } else if (strcmp(cmd, "get_analog") == 0) {
    uint8_t pin = doc["pin"];
    int val     = analogRead(pin);
    resp["status"] = "ok"; resp["pin"] = pin; resp["value"] = val;
    sendJson(resp);

  } else if (strcmp(cmd, "get_rgb") == 0) {
    if (!tcsReady) { sendError("sensor_not_found"); return; }
    uint16_t r, g, b, c;
    tcs.getRawData(&r, &g, &b, &c);
    resp["status"] = "ok";
    resp["r"] = r; resp["g"] = g; resp["b"] = b; resp["c"] = c;
    sendJson(resp);

  } else {
    sendError("unknown_cmd");
  }
}

// ── BLE callbacks ─────────────────────────────────────────────────────

class ServerCB : public BLEServerCallbacks {
  void onConnect(BLEServer*)       override { bleCon = true; }
  void onDisconnect(BLEServer* s)  override {
    bleCon = false;
    rxBuf  = "";
    s->startAdvertising();
  }
};

class RxCB : public BLECharacteristicCallbacks {
  void onWrite(BLECharacteristic* pC) override {
    String val = pC->getValue();
    for (char c : val) {
      if (c == '\n') {
        if (rxBuf.length() > 0) {
          StaticJsonDocument<256> doc;
          DeserializationError err = deserializeJson(doc, rxBuf);
          if (err) sendError("parse_error");
          else     handleCommand(doc);
          rxBuf = "";
        }
      } else {
        rxBuf += c;
      }
    }
  }
};

// ── Arduino entry points ──────────────────────────────────────────────

void setup() {
  // Output pins are registered at runtime by the hub's "configure" command.
  Wire.begin(21, 22);
  tcsReady = tcs.begin();

  BLEDevice::init("Bioreactor");
  BLEDevice::setMTU(512);

  BLEServer*  pServer = BLEDevice::createServer();
  pServer->setCallbacks(new ServerCB());

  BLEService* pSvc = pServer->createService(NUS_SERVICE_UUID);

  pTxChar = pSvc->createCharacteristic(NUS_TX_UUID, BLECharacteristic::PROPERTY_NOTIFY);
  pTxChar->addDescriptor(new BLE2902());

  BLECharacteristic* pRxChar = pSvc->createCharacteristic(NUS_RX_UUID,
    BLECharacteristic::PROPERTY_WRITE | BLECharacteristic::PROPERTY_WRITE_NR);
  pRxChar->setCallbacks(new RxCB());

  pSvc->start();
  pServer->getAdvertising()->start();
}

void loop() {
  delay(10);  // BLE stack runs on FreeRTOS tasks; nothing to do here
}
