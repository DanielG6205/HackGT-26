#include <Servo.h>
#include <math.h>
#include <stdlib.h>

// USB: 115200, newline terminated ASCII. Physical angles, no firmware inversion.
// CONFIG,eyes|neck|head,pin,min,center,max -> CONFIGURED,name
// POSE,eyes,neck,head -> no per-frame reply (avoids serial backpressure).
// Legacy servo_number,angle remains available before CONFIG (pins 10..4).
Servo servos[7];
const int legacyPins[7] = {10, 9, 8, 7, 6, 5, 4};
const char *names[3] = {"eyes", "neck", "head"};
float low[3], middle[3], high[3];
int pins[3] = {-1, -1, -1};
bool configured[3] = {false, false, false};
bool gazeMode = false;
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
  if (count == 1 && !strcmp(parts[0], "PING")) { Serial.println("GAZE_READY,1"); return; }
  if (count == 6 && !strcmp(parts[0], "CONFIG")) {
    int axis = -1;
    for (int i=0; i<3; i++) if (!strcmp(parts[1], names[i])) axis=i;
    float pin, lo, center, hi;
    if (axis < 0 || !number(parts[2], pin) || !number(parts[3], lo) ||
        !number(parts[4], center) || !number(parts[5], hi) ||
        pin != floor(pin) || pin < 2 || pin > 13 || lo < 0 || hi > 180 ||
        lo > center || center > hi) { Serial.println("ERROR config"); return; }
    for (int i=0; i<3; i++) if (i != axis && configured[i] && pins[i] == (int)pin) {
      Serial.println("ERROR duplicate pin"); return;
    }
    if (!gazeMode) {
      for (int i=0; i<7; i++) servos[i].detach();
      gazeMode = true;
    }
    servos[axis].detach();
    low[axis]=lo; middle[axis]=center; high[axis]=hi; pins[axis]=(int)pin;
    configured[axis]=true;
    // Delay attachment until the entire pose has passed validation.
    Serial.print("CONFIGURED,"); Serial.println(names[axis]); return;
  }
  if (count == 4 && !strcmp(parts[0], "POSE")) {
    float values[3];
    for (int i=0; i<3; i++) {
      if (!configured[i] || !number(parts[i+1], values[i]) || values[i]<low[i] || values[i]>high[i]) {
        Serial.println("ERROR pose"); return;
      }
    }
    for (int i=0; i<3; i++) {
      // Servo.write truncates degrees. Use pulse conversion to retain fractions.
      int pulse = (int)round(544.0 + values[i]*(2400.0-544.0)/180.0);
      servos[i].writeMicroseconds(pulse);
      if (!servos[i].attached()) servos[i].attach(pins[i]);
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
  Serial.println("GAZE_READY,1");
}

void loop() {
  while (Serial.available()) {
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
