#include <Servo.h>

// Matches puppet.ino numbering, NOT the legacy robot_controller sketch.
const int pins[] = {4, 6};
// Provisional reference pulses from puppet.ino. Calibrate with linkage removed.
const int low[] = {1150, 1600};
const int high[] = {1250, 1700};
Servo servos[2];
int current[2], target[2], rest[2];
bool armed[2] = {false, false};
unsigned long movedAt[2], lastStep = 0;
char input[48];
byte length = 0;
bool overflow = false;

void command(char* line) {
  char operation[8], extra;
  int number = 0, pulse = 0;
  int count = sscanf(line, "%7[^,],%d,%d%c", operation, &number, &pulse, &extra);
  int i = number == 1 ? 0 : number == 3 ? 1 : -1;
  if (count == 2 && i >= 0 && strcmp(operation, "OFF") == 0) {
    servos[i].detach();
    armed[i] = false;
  } else if (count == 3 && i >= 0 && pulse >= low[i] && pulse <= high[i]) {
    if (strcmp(operation, "ARM") == 0 && !armed[i]) {
      current[i] = target[i] = rest[i] = pulse;
      // Preload before attach to avoid the library's default 1500 us pulse.
      servos[i].writeMicroseconds(pulse);
      servos[i].attach(pins[i]);
      armed[i] = true;
    } else if (strcmp(operation, "PULSE") == 0 && armed[i] && abs(pulse - rest[i]) <= 25) {
      target[i] = pulse;
      movedAt[i] = millis();
    } else {
      Serial.println("ERROR command or arm state");
      return;
    }
  } else {
    Serial.println("ERROR range or syntax");
    return;
  }
  Serial.print("OK,");
  Serial.println(line);
}

void setup() {
  Serial.begin(115200);
  // No attach or movement on boot. Only servos 1 and 3 can be armed.
  Serial.println("CAMERA_SERVO_READY");
}

void loop() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') {
      input[length] = 0;
      if (!overflow) command(input);
      else Serial.println("ERROR line too long");
      length = 0;
      overflow = false;
    } else if (c != '\r') {
      if (length < sizeof(input) - 1) input[length++] = c;
      else overflow = true;
    }
  }
  unsigned long now = millis();
  if (now - lastStep < 20) return;
  lastStep = now;
  for (int i = 0; i < 2; ++i) {
    if (!armed[i]) continue;
    // Return even if the host freezes or USB is unplugged.
    if (target[i] != rest[i] && now - movedAt[i] >= 1000) target[i] = rest[i];
    int delta = constrain(target[i] - current[i], -2, 2);
    current[i] += delta;
    servos[i].writeMicroseconds(current[i]);
  }
}
