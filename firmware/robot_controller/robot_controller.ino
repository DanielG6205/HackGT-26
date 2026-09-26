/*
 * robot_controller.ino — host LOOK/CENTER/EXPR/MOVE/SET/PING commands with
 * XRobots-style exponential servo smoothing
 * (https://github.com/XRobots/ServoSmoothing).
 *
 * Smoothing (same idea as their simple/puppet/sequencer sketches):
 *   current = (target * alpha) + (current * (1 - alpha));
 *
 * Servos are driven with writeMicroseconds() like the XRobots demos.
 * Angles in the CONFIGURATION block are converted to pulse widths.
 *
 * Protocol (ASCII, newline-terminated) from host Python:
 *   LOOK,0.72,0.41
 *   LOOK,0.72,0.41,0.50,0.55
 *   CENTER
 *   EXPR,neutral
 *   MOVE,LEFT
 *   SET,eye_x,95.00
 *   PING
 *
 * Keep host app/robot/config.py in sync with the values below.
 */

#include <Servo.h>

// ========================= CONFIGURATION =========================
// Pins — set to your servo signal wires. Use -1 to disable an axis.
const int PIN_EYE_X = 9;
const int PIN_EYE_Y = 10;
const int PIN_HEAD_X = -1;  // e.g. 5 when head pan is wired
const int PIN_HEAD_Y = -1;  // e.g. 6 when head tilt is wired

// Centers and safe travel limits (degrees). Measure on your mechanism.
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

// Degree ↔ microseconds (XRobots drives servos in µs).
// Default maps 0°→1000µs, 180°→2000µs (typical hobby servo).
const float SERVO_US_AT_0_DEG = 1000.0;
const float SERVO_US_AT_180_DEG = 2000.0;

// XRobots exponential smoothing weights (target*alpha + prev*(1-alpha)).
// Their demos use ~0.01–0.05. Smaller = smoother/slower.
const float SMOOTH_ALPHA = 0.05f;

const float MOVE_STEP_NORM = 0.15;       // MOVE,LEFT/RIGHT/UP/DOWN nudge
const unsigned long LOOP_INTERVAL_MS = 5;  // match XRobots ~200 Hz loop
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
  float currentDeg;   // smoothed output (degrees)
  float targetDeg;    // commanded target (degrees)
};

Axis eyeX, eyeY, headX, headY;
float lookX = 0.5;
float lookY = 0.5;
String lineBuf;
unsigned long previousMillis = 0;

float clampf(float v, float lo, float hi) {
  if (v < lo) return lo;
  if (v > hi) return hi;
  return v;
}

float clamp01(float v) {
  return clampf(v, 0.0f, 1.0f);
}

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
    a.servo.attach(pin);
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

// XRobots exponential smoothing, then writeMicroseconds.
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

void handleExpression(const String &/*name*/) {
  // Placeholder: expression morph targets / LEDs can be added later.
}

void handleSet(const String &axisName, float angle) {
  Axis *a = axisByName(axisName);
  if (a == nullptr || !a->enabled) return;
  a->targetDeg = clampf(angle, a->minDeg, a->maxDeg);
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
    handleExpression(tok[1]);
  } else if (cmd == "MOVE" && n >= 2) {
    String d = tok[1];
    d.toUpperCase();
    handleMove(d);
  } else if (cmd == "SET" && n >= 3) {
    handleSet(tok[1], tok[2].toFloat());
  } else if (cmd == "PING") {
    Serial.println("PONG");
  } else {
    Serial.println("ERR");
  }
}

void readSerial() {
  while (Serial.available() > 0) {
    char c = (char)Serial.read();
    if (c == '\n' || c == '\r') {
      if (lineBuf.length() > 0) {
        processLine(lineBuf);
        lineBuf = "";
      }
    } else if (lineBuf.length() < 96) {
      lineBuf += c;
    }
  }
}

void setup() {
  Serial.begin(BAUD);
  setupAxis(eyeX, PIN_EYE_X, EYE_X_CENTER, EYE_X_MIN, EYE_X_MAX, EYE_X_INVERT);
  setupAxis(eyeY, PIN_EYE_Y, EYE_Y_CENTER, EYE_Y_MIN, EYE_Y_MAX, EYE_Y_INVERT);
  setupAxis(headX, PIN_HEAD_X, HEAD_X_CENTER, HEAD_X_MIN, HEAD_X_MAX, HEAD_X_INVERT);
  setupAxis(headY, PIN_HEAD_Y, HEAD_Y_CENTER, HEAD_Y_MIN, HEAD_Y_MAX, HEAD_Y_INVERT);
  centerAll();
  Serial.println("READY");
}

void loop() {
  // Always drain serial so commands are not delayed by the timed servo loop.
  readSerial();

  unsigned long now = millis();
  if (now - previousMillis < LOOP_INTERVAL_MS) return;
  previousMillis = now;

  stepAxis(eyeX);
  stepAxis(eyeY);
  stepAxis(headX);
  stepAxis(headY);
}
