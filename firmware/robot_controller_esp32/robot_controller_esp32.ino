/*
 * robot_controller_esp32.ino — Wi-Fi TCP robot eyes/head with servos.
 *
 * Board: ESP32 (Arduino core). Host Python connects as TCP client:
 *   ROBOT_WIFI_HOST=<board-ip>  ROBOT_WIFI_PORT=9000
 *
 * Same ASCII protocol as USB firmware:
 *   LOOK,0.72,0.41
 *   CENTER / MOVE,LEFT / EXPR,neutral / SET,eye_x,95.00 / PING
 *
 * Fill WIFI_SSID / WIFI_PASSWORD (or enable SoftAP). Fill servo pins/limits.
 * Uses XRobots-style exponential smoothing + writeMicroseconds.
 *
 * Arduino IDE: Boards → ESP32 Dev Module. Library: ESP32Servo (if prompted).
 */

#include <WiFi.h>
#include <ESP32Servo.h>

// ========================= CONFIGURATION =========================
// Wi-Fi — STA joins your router; SoftAP makes the ESP its own hotspot.
#define USE_SOFTAP 0
const char *WIFI_SSID = "YOUR_WIFI_SSID";
const char *WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";
const char *SOFTAP_SSID = "RobotEyes";
const char *SOFTAP_PASSWORD = "robot1234";  // >= 8 chars
const uint16_t TCP_PORT = 9000;

// Servo signal pins (change to match your wiring).
const int PIN_EYE_X = 18;
const int PIN_EYE_Y = 19;
const int PIN_HEAD_X = -1;  // e.g. 21
const int PIN_HEAD_Y = -1;  // e.g. 22
const int PIN_LED = 2;      // many ESP32 boards use GPIO2 for onboard LED

const float EYE_X_CENTER = 90.0;
const float EYE_X_MIN = 60.0;
const float EYE_X_MAX = 120.0;
const bool EYE_X_INVERT = false;

const float EYE_Y_CENTER = 90.0;
const float EYE_Y_MIN = 60.0;
const float EYE_Y_MAX = 120.0;
const bool EYE_Y_INVERT = false;

const float HEAD_X_CENTER = 90.0;
const float HEAD_X_MIN = 60.0;
const float HEAD_X_MAX = 120.0;
const bool HEAD_X_INVERT = false;

const float HEAD_Y_CENTER = 90.0;
const float HEAD_Y_MIN = 60.0;
const float HEAD_Y_MAX = 120.0;
const bool HEAD_Y_INVERT = false;

const float SERVO_US_AT_0_DEG = 1000.0;
const float SERVO_US_AT_180_DEG = 2000.0;
const float SMOOTH_ALPHA = 0.05f;
const float MOVE_STEP_NORM = 0.15f;
const unsigned long LOOP_INTERVAL_MS = 5;
const unsigned long BAUD = 115200;
// =================================================================

struct Axis {
  Servo servo;
  int pin;
  float center;
  float minDeg;
  float maxDeg;
  bool invert;
  bool enabled;
  float currentDeg;
  float targetDeg;
};

Axis eyeX, eyeY, headX, headY;
float lookX = 0.5f;
float lookY = 0.5f;
String lineBuf;
unsigned long previousMillis = 0;

WiFiServer server(TCP_PORT);
WiFiClient client;

float clampf(float v, float lo, float hi) {
  if (v < lo) return lo;
  if (v > hi) return hi;
  return v;
}

float clamp01(float v) { return clampf(v, 0.0f, 1.0f); }

float degreesToMicros(float deg) {
  float us = SERVO_US_AT_0_DEG +
             (deg / 180.0f) * (SERVO_US_AT_180_DEG - SERVO_US_AT_0_DEG);
  return clampf(us, 500.0f, 2500.0f);
}

void setupAxis(Axis &a, int pin, float center, float minDeg, float maxDeg, bool invert) {
  a.pin = pin;
  a.center = center;
  a.minDeg = minDeg;
  a.maxDeg = maxDeg;
  a.invert = invert;
  a.enabled = pin >= 0;
  a.currentDeg = center;
  a.targetDeg = center;
  if (a.enabled) {
    a.servo.setPeriodHertz(50);
    a.servo.attach(pin, (int)SERVO_US_AT_0_DEG, (int)SERVO_US_AT_180_DEG);
    a.servo.writeMicroseconds((int)(degreesToMicros(center) + 0.5f));
  }
}

float normToAngle(float norm, const Axis &a) {
  float n = clamp01(norm);
  if (a.invert) n = 1.0f - n;
  if (n <= 0.5f) {
    float t = n / 0.5f;
    return a.minDeg + t * (a.center - a.minDeg);
  }
  float t = (n - 0.5f) / 0.5f;
  return a.center + t * (a.maxDeg - a.center);
}

void setLook(float x, float y) {
  lookX = clamp01(x);
  lookY = clamp01(y);
  if (eyeX.enabled) eyeX.targetDeg = normToAngle(lookX, eyeX);
  if (eyeY.enabled) eyeY.targetDeg = normToAngle(lookY, eyeY);
}

void setLookWithHead(float x, float y, float hx, float hy) {
  setLook(x, y);
  if (headX.enabled) headX.targetDeg = normToAngle(clamp01(hx), headX);
  if (headY.enabled) headY.targetDeg = normToAngle(clamp01(hy), headY);
}

void centerAll() {
  lookX = 0.5f;
  lookY = 0.5f;
  if (eyeX.enabled) eyeX.targetDeg = eyeX.center;
  if (eyeY.enabled) eyeY.targetDeg = eyeY.center;
  if (headX.enabled) headX.targetDeg = headX.center;
  if (headY.enabled) headY.targetDeg = headY.center;
}

void stepAxis(Axis &a) {
  if (!a.enabled) return;
  float alpha = SMOOTH_ALPHA;
  if (alpha < 0.0f) alpha = 0.0f;
  if (alpha > 1.0f) alpha = 1.0f;
  a.currentDeg = (a.targetDeg * alpha) + (a.currentDeg * (1.0f - alpha));
  a.currentDeg = clampf(a.currentDeg, a.minDeg, a.maxDeg);
  a.servo.writeMicroseconds((int)(degreesToMicros(a.currentDeg) + 0.5f));
}

Axis *axisByName(const String &name) {
  if (name == "eye_x") return &eyeX;
  if (name == "eye_y") return &eyeY;
  if (name == "head_x") return &headX;
  if (name == "head_y") return &headY;
  return nullptr;
}

void handleMove(const String &dir) {
  if (dir == "CENTER") {
    centerAll();
    return;
  }
  if (dir == "LEFT") lookX -= MOVE_STEP_NORM;
  else if (dir == "RIGHT") lookX += MOVE_STEP_NORM;
  else if (dir == "UP") lookY -= MOVE_STEP_NORM;
  else if (dir == "DOWN") lookY += MOVE_STEP_NORM;
  else return;
  setLook(lookX, lookY);
}

void handleSet(const String &axisName, float angle) {
  Axis *a = axisByName(axisName);
  if (a == nullptr || !a->enabled) return;
  a->targetDeg = clampf(angle, a->minDeg, a->maxDeg);
}

void reply(const String &line) {
  if (client && client.connected()) {
    client.println(line);
  }
  Serial.println(line);
}

void processLine(String line) {
  line.trim();
  if (line.length() == 0) return;

  String tok[5];
  int n = 0;
  int start = 0;
  while (n < 5) {
    int comma = line.indexOf(',', start);
    if (comma < 0) {
      tok[n++] = line.substring(start);
      break;
    }
    tok[n++] = line.substring(start, comma);
    start = comma + 1;
  }
  for (int i = 0; i < n; i++) tok[i].trim();

  String cmd = tok[0];
  cmd.toUpperCase();

  if (cmd == "LOOK" && n >= 3) {
    float x = tok[1].toFloat();
    float y = tok[2].toFloat();
    if (n >= 5) setLookWithHead(x, y, tok[3].toFloat(), tok[4].toFloat());
    else setLook(x, y);
  } else if (cmd == "CENTER") {
    centerAll();
  } else if (cmd == "EXPR" && n >= 2) {
    // Expression morph placeholder.
  } else if (cmd == "MOVE" && n >= 2) {
    String d = tok[1];
    d.toUpperCase();
    handleMove(d);
  } else if (cmd == "SET" && n >= 3) {
    handleSet(tok[1], tok[2].toFloat());
  } else if (cmd == "PING") {
    reply("PONG");
  } else {
    reply("ERR");
  }
}

void feedChar(char c) {
  if (c == '\n' || c == '\r') {
    if (lineBuf.length() > 0) {
      processLine(lineBuf);
      lineBuf = "";
    }
  } else if (lineBuf.length() < 96) {
    lineBuf += c;
  }
}

void readClient() {
  if (!client || !client.connected()) {
    client = server.available();
    if (client) {
      lineBuf = "";
      reply("READY");
      reply("MODE,WIFI_SERVO");
      Serial.println("Client connected");
    }
    return;
  }
  while (client.available() > 0) {
    feedChar((char)client.read());
  }
}

void connectWifi() {
#if USE_SOFTAP
  WiFi.mode(WIFI_AP);
  WiFi.softAP(SOFTAP_SSID, SOFTAP_PASSWORD);
  Serial.print("SoftAP ");
  Serial.print(SOFTAP_SSID);
  Serial.print(" IP ");
  Serial.println(WiFi.softAPIP());
#else
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("Connecting to Wi-Fi");
  unsigned long start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < 30000) {
    delay(400);
    Serial.print(".");
  }
  Serial.println();
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("Wi-Fi failed — check SSID/password");
  } else {
    Serial.print("Wi-Fi OK  IP ");
    Serial.println(WiFi.localIP());
  }
#endif
}

void setup() {
  Serial.begin(BAUD);
  pinMode(PIN_LED, OUTPUT);
  digitalWrite(PIN_LED, LOW);

  ESP32PWM::allocateTimer(0);
  ESP32PWM::allocateTimer(1);
  ESP32PWM::allocateTimer(2);
  ESP32PWM::allocateTimer(3);

  setupAxis(eyeX, PIN_EYE_X, EYE_X_CENTER, EYE_X_MIN, EYE_X_MAX, EYE_X_INVERT);
  setupAxis(eyeY, PIN_EYE_Y, EYE_Y_CENTER, EYE_Y_MIN, EYE_Y_MAX, EYE_Y_INVERT);
  setupAxis(headX, PIN_HEAD_X, HEAD_X_CENTER, HEAD_X_MIN, HEAD_X_MAX, HEAD_X_INVERT);
  setupAxis(headY, PIN_HEAD_Y, HEAD_Y_CENTER, HEAD_Y_MIN, HEAD_Y_MAX, HEAD_Y_INVERT);
  centerAll();

  connectWifi();
  server.begin();
  server.setNoDelay(true);
  Serial.print("TCP server on port ");
  Serial.println(TCP_PORT);
  Serial.println("MODE,WIFI_SERVO");
}

void loop() {
  readClient();

  unsigned long now = millis();
  if (now - previousMillis < LOOP_INTERVAL_MS) return;
  previousMillis = now;
  stepAxis(eyeX);
  stepAxis(eyeY);
  stepAxis(headX);
  stepAxis(headY);
}
