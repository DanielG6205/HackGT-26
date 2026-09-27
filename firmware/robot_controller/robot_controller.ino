#include <Servo.h>

const int NUM_SERVOS = 7;

const int servoPins[NUM_SERVOS] = {
  10, 9, 8, 7, 6, 5, 4
};

Servo servos[NUM_SERVOS];

String input = "";

void setup() {
  Serial.begin(115200);

  for (int i = 0; i < NUM_SERVOS; i++) {
    servos[i].attach(servoPins[i]);

    // Start centered
    servos[i].write(90);
  }

  Serial.println("READY");
}

void loop() {
  while (Serial.available() > 0) {

    char c = Serial.read();

    if (c == '\n') {
      processCommand(input);
      input = "";
    }
    else if (c != '\r') {
      input += c;
    }
  }
}

void processCommand(String command) {

  command.trim();

  int comma = command.indexOf(',');

  if (comma == -1) {
    Serial.println("ERROR");
    return;
  }

  int servoNumber = command.substring(0, comma).toInt();
  int angle = command.substring(comma + 1).toInt();

  if (servoNumber < 1 || servoNumber > 7) {
    Serial.println("ERROR servo");
    return;
  }

  if (angle < 0 || angle > 180) {
    Serial.println("ERROR angle");
    return;
  }

  servos[servoNumber - 1].write(angle);

  Serial.print("OK,");
  Serial.print(servoNumber);
  Serial.print(",");
  Serial.println(angle);
}