#include <Servo.h>
#include <math.h>
#include <stdlib.h>

// USB: 115200, newline terminated ASCII. Physical angles, no firmware inversion.
// CONFIG,eye_left|eye_right|neck|lift_left|lift_right,pin,min,center,max -> CONFIGURED,name
// POSE,eye_left,eye_right,neck,lift_left,lift_right -> no per-frame reply (avoids serial backpressure).
// Legacy servo_number,angle remains available before CONFIG (pins 10..4).
Servo servos[7];
const int legacyPins[7] = {10, 9, 8, 7, 6, 5, 4};
const int AXIS_COUNT = 5;
// Physical legacy slots: pin4=6, pin5=5, pin10=0, pin8=2, pin9=1.
// Slots 3/4 (pins 7/6) belong to Arduino eyelid control; gaze never touches them.
const int gazeSlots[AXIS_COUNT] = {6, 5, 0, 2, 1};
const char *names[AXIS_COUNT] = {"eye_left", "eye_right", "neck", "lift_left", "lift_right"};
float low[AXIS_COUNT], middle[AXIS_COUNT], high[AXIS_COUNT];
int pins[AXIS_COUNT] = {-1, -1, -1, -1, -1};
bool configured[AXIS_COUNT] = {};
bool gazeMode = false;
// Eighth physical servo, independent of the seven legacy slots and five-axis POSE.
Servo mouth;
int mouthPin = -1, mouthClosed = 90, mouthOpen = 90;
bool talking = false;
unsigned long talkHeartbeat = 0, talkPhaseAt = 0;
bool mouthIsOpen = false;

void closeMouth() {
  talking = false;
  mouthIsOpen = false;
  if (mouth.attached()) mouth.write(mouthClosed);
}

void tickMouth() {
  if (!talking) return;
  unsigned long now = millis();
  if (now - talkHeartbeat > 600) { closeMouth(); return; }
  if (now - talkPhaseAt >= (mouthIsOpen ? 130UL : 100UL)) {
    mouthIsOpen = !mouthIsOpen;
    mouth.write(mouthIsOpen ? mouthOpen : mouthClosed);
    talkPhaseAt = now;
  }
}
char input[128];
unsigned int used = 0;
bool overflowed = false;

bool number(const char *text, float &value) {
  if (!text || !*text) return false;
  char *end;
  value = strtod(text, &end);
  return *end == '\0' && isfinite(value);
}

void processCommand(char *line) {
  char *parts[8];
  int count = 0;
  // Reject empty fields rather than allowing strtok to collapse them.
  if (!*line || line[0] == ',' || line[strlen(line)-1] == ',' || strstr(line, ",,")) {
    Serial.println("ERROR format"); return;
  }
  char *token = strtok(line, ",");
  while (token && count < 8) { parts[count++] = token; token = strtok(NULL, ","); }
  if (token) { Serial.println("ERROR length"); return; }
  if (count == 1 && !strcmp(parts[0], "PING")) { Serial.println("GAZE_READY,2"); return; }
  if (count == 6 && !strcmp(parts[0], "MOUTH_CONFIG")) {
    float pin, lo, closed, opened, hi;
    if (!number(parts[1], pin) || !number(parts[2], lo) || !number(parts[3], closed) ||
        !number(parts[4], opened) || !number(parts[5], hi) ||
        pin != floor(pin) || pin < 2 || pin > 13 ||
        lo != floor(lo) || closed != floor(closed) || opened != floor(opened) || hi != floor(hi) ||
        lo < 0 || hi > 180 || lo > closed || closed > hi || opened < lo || opened > hi) {
      Serial.println("ERROR mouth config"); return;
    }
    // Reserve all seven legacy pins even when those servos are not attached.
    for (int i=0; i<7; i++) if (legacyPins[i] == (int)pin) {
      Serial.println("ERROR mouth pin reserved"); return;
    }
    for (int i=0; i<AXIS_COUNT; i++) if (configured[i] && pins[i] == (int)pin) {
      Serial.println("ERROR mouth pin conflict"); return;
    }
    closeMouth();
    mouth.detach();
    mouthPin = (int)pin; mouthClosed = (int)closed; mouthOpen = (int)opened;
    mouth.write(mouthClosed);
    mouth.attach(mouthPin);
    Serial.println("MOUTH_READY"); return;
  }
  if (count == 2 && !strcmp(parts[0], "TALK")) {
    if (!strcmp(parts[1], "0")) { closeMouth(); return; }
    if (strcmp(parts[1], "1") || !mouth.attached()) {
      Serial.println("ERROR mouth not configured"); return;
    }
    talkHeartbeat = millis();
    if (!talking) {
      talking = true; mouthIsOpen = true; talkPhaseAt = talkHeartbeat;
      mouth.write(mouthOpen);
    }
    return;
  }
  if (count == 6 && !strcmp(parts[0], "CONFIG")) {
    int axis = -1;
    for (int i=0; i<AXIS_COUNT; i++) if (!strcmp(parts[1], names[i])) axis=i;
    float pin, lo, center, hi;
    if (axis < 0 || !number(parts[2], pin) || !number(parts[3], lo) ||
        !number(parts[4], center) || !number(parts[5], hi) ||
        pin != floor(pin) || pin < 2 || pin > 13 || lo < 0 || hi > 180 ||
        lo > center || center > hi) { Serial.println("ERROR config"); return; }
    if ((int)pin == 6 || (int)pin == 7) { Serial.println("ERROR eyelid pin reserved"); return; }
    if ((int)pin == mouthPin) { Serial.println("ERROR mouth pin conflict"); return; }
    for (int i=0; i<AXIS_COUNT; i++) if (i != axis && configured[i] && pins[i] == (int)pin) {
      Serial.println("ERROR duplicate pin"); return;
    }
    if (!gazeMode) {
      for (int i=0; i<AXIS_COUNT; i++) servos[gazeSlots[i]].detach();
      gazeMode = true;
    }
    servos[gazeSlots[axis]].detach();
    low[axis]=lo; middle[axis]=center; high[axis]=hi; pins[axis]=(int)pin;
    configured[axis]=true;
    // Delay attachment until the entire pose has passed validation.
    Serial.print("CONFIGURED,"); Serial.println(names[axis]); return;
  }
  if (count == AXIS_COUNT + 1 && !strcmp(parts[0], "POSE")) {
    float values[AXIS_COUNT];
    for (int i=0; i<AXIS_COUNT; i++) {
      if (!configured[i] || !number(parts[i+1], values[i]) || values[i]<low[i] || values[i]>high[i]) {
        Serial.println("ERROR pose"); return;
      }
    }
    for (int i=0; i<AXIS_COUNT; i++) {
      // Servo.write truncates degrees. Use pulse conversion to retain fractions.
      int pulse = (int)round(544.0 + values[i]*(2400.0-544.0)/180.0);
      servos[gazeSlots[i]].writeMicroseconds(pulse);
      if (!servos[gazeSlots[i]].attached()) servos[gazeSlots[i]].attach(pins[i]);
    }
    return;
  }
  float servoNumber, angle;
  if (!gazeMode && count == 2 && number(parts[0], servoNumber) && number(parts[1], angle) &&
      servoNumber == floor(servoNumber) && servoNumber >= 1 && servoNumber <= 7 && angle >= 0 && angle <= 180) {
    int i = (int)servoNumber-1;
    servos[i].write((int)angle);
    if (!servos[i].attached()) servos[i].attach(legacyPins[i]);
    Serial.print("OK,"); Serial.print((int)servoNumber); Serial.print(','); Serial.println((int)angle);
    return;
  }
  Serial.println("ERROR command");
}

void setup() {
  Serial.begin(115200);
  // Do not move unknown hardware on boot. CONFIG + POSE arms calibrated axes.
  Serial.println("READY");
  Serial.println("GAZE_READY,2");
}

void loop() {
  tickMouth();
  while (Serial.available()) {
    tickMouth();
    char c = Serial.read();
    if (c == '\n') {
      input[used] = '\0';
      if (overflowed) Serial.println("ERROR length"); else processCommand(input);
      used = 0; overflowed = false;
    } else if (c != '\r') {
      if (used < sizeof(input)-1) input[used++] = c; else overflowed = true;
    }
  }
}
