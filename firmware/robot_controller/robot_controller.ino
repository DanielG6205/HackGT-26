#include <Servo.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>

/*
 * HackGT-26 Ottis Robot Controller
 *
 * USB serial protocol @ 115200 baud
 *
 * Startup:
 *   GAZE_READY,2
 *
 * Gaze configuration:
 *   CONFIG,eye_left,4,85.0000,90.0000,95.0000
 *   CONFIG,eye_right,5,85.0000,90.0000,95.0000
 *   CONFIG,neck,10,85.0000,90.0000,95.0000
 *   CONFIG,lift_left,8,85.0000,90.0000,95.0000
 *   CONFIG,lift_right,9,85.0000,90.0000,95.0000
 *
 * Firmware responds:
 *   CONFIGURED,eye_left
 *
 * Gaze:
 *   POSE,eye_left,eye_right,neck,lift_left,lift_right
 *
 * Example:
 *   POSE,90.0000,90.0000,92.5000,88.0000,91.0000
 *
 * Valid POSE commands receive NO response.
 *
 * Mouth:
 *   MOUTH_CONFIG,11,85,90,95,100
 *   TALK,1
 *   TALK,0
 *
 * Legacy:
 *   Before the first CONFIG command:
 *   1,90
 *   2,120
 *   etc.
 *
 * IMPORTANT:
 *   Pins 6 and 7 are reserved for eyelids.
 *   The configured mouth pin is reserved while mouth control is active.
 */


// -----------------------------------------------------------------------------
// Hardware
// -----------------------------------------------------------------------------

const uint8_t EYELID_LEFT_PIN  = 6;
const uint8_t EYELID_RIGHT_PIN = 7;
// Measured endpoints differ because the eyelids have opposite orientations.
const int EYELID_LEFT_OPEN_DEG = 130;   // pin 6
const int EYELID_LEFT_CLOSED_DEG = 180;
const int EYELID_RIGHT_OPEN_DEG = 50;   // pin 7
const int EYELID_RIGHT_CLOSED_DEG = 0;

// Mouth pin is supplied by MOUTH_CONFIG from robot-servos.json.

const uint8_t NUM_GAZE_AXES = 5;


// Legacy servo mapping:
//
// legacy servo 1 -> pin 10
// legacy servo 2 -> pin 9
// legacy servo 3 -> pin 8
// legacy servo 4 -> pin 7   RESERVED EYELID
// legacy servo 5 -> pin 6   RESERVED EYELID
// legacy servo 6 -> pin 5
// legacy servo 7 -> pin 4

const uint8_t legacyPins[7] = {
  10, 9, 8, 7, 6, 5, 4
};

// Legacy commands reuse the physical servo objects declared below.


// -----------------------------------------------------------------------------
// Calibrated gaze axes
// -----------------------------------------------------------------------------

struct GazeAxis {

  const char* name;

  Servo servo;

  bool configured;

  uint8_t pin;

  float minDeg;
  float centerDeg;
  float maxDeg;

  float currentDeg;
};


GazeAxis axes[NUM_GAZE_AXES] = {

  {
    "eye_left",
    Servo(),
    false,
    4,
    0,
    90,
    180,
    90
  },

  {
    "eye_right",
    Servo(),
    false,
    5,
    0,
    90,
    180,
    90
  },

  {
    "neck",
    Servo(),
    false,
    10,
    0,
    90,
    180,
    90
  },

  {
    "lift_left",
    Servo(),
    false,
    8,
    0,
    90,
    180,
    90
  },

  {
    "lift_right",
    Servo(),
    false,
    9,
    0,
    90,
    180,
    90
  }
};


// -----------------------------------------------------------------------------
// Eyelids
// -----------------------------------------------------------------------------

Servo eyelidLeft;
Servo eyelidRight;

// Nonblocking smooth blink: close 180ms, hold 70ms, reopen 240ms.
// Preserve individually measured endpoints; both lids move in phase.
unsigned long blinkStarted = 0;
unsigned long blinkLastWrite = 0;
unsigned long blinkCycle = 0;
// Broad but bounded rests; same average (3.85s) as before, much larger spread.
const unsigned long BLINK_RESTS_MS[] = {1200, 6500, 2400, 7100, 1600, 4300};
void updateEyelids() {
  unsigned long now = millis();
  if (now - blinkLastWrite < 20) return;
  blinkLastWrite = now;
  const unsigned long rest = BLINK_RESTS_MS[blinkCycle % 6];
  unsigned long elapsed = now - blinkStarted;
  float closed = 0;
  if (elapsed >= rest) {
    unsigned long phase = elapsed - rest;
    if (phase < 180) closed = phase / 180.0f;
    else if (phase < 250) closed = 1;
    else if (phase < 490) closed = 1 - (phase - 250) / 240.0f;
    else { blinkStarted = now; blinkCycle++; }
  }
  closed = closed * closed * (3 - 2 * closed); // Smooth acceleration/deceleration.
  eyelidLeft.write((int)round(EYELID_LEFT_OPEN_DEG + closed *
                            (EYELID_LEFT_CLOSED_DEG - EYELID_LEFT_OPEN_DEG)));
  eyelidRight.write((int)round(EYELID_RIGHT_OPEN_DEG + closed *
                             (EYELID_RIGHT_CLOSED_DEG - EYELID_RIGHT_OPEN_DEG)));
}



// -----------------------------------------------------------------------------
// Mouth
// -----------------------------------------------------------------------------

Servo mouth;

// Exactly eight Servo objects: five gaze axes, two eyelids, one mouth.
// AVR Servo assigns channels at construction, even before attach(). Keeping
// seven additional legacy objects exhausts the Uno's 12-channel capacity.
Servo* const legacyServos[7] = {
  &axes[2].servo, &axes[4].servo, &axes[3].servo,
  &eyelidRight, &eyelidLeft, &axes[1].servo, &axes[0].servo
};

bool mouthConfigured = false;
bool mouthTalking = false;

uint8_t mouthPin = 0;  // Unassigned until MOUTH_CONFIG succeeds.

float mouthMinDeg = 110;
float mouthClosedDeg = 110;
float mouthOpenDeg = 60;
float mouthMaxDeg = 60;

unsigned long lastTalkMillis = 0;
unsigned long lastMouthAnimationMillis = 0;

bool mouthIsOpen = false;

const unsigned long MOUTH_TIMEOUT_MS = 600;
const unsigned long MOUTH_ANIMATION_MS = 180;


// -----------------------------------------------------------------------------
// Serial
// -----------------------------------------------------------------------------

const size_t INPUT_BUFFER_SIZE = 180;

char inputBuffer[INPUT_BUFFER_SIZE];

size_t inputLength = 0;

bool discardUntilNewline = false;

bool calibratedMode = false;


// -----------------------------------------------------------------------------
// Utility
// -----------------------------------------------------------------------------

bool isFiniteFloat(float value) {

  return !isnan(value) && !isinf(value);
}


// strtof() is unavailable on some Arduino environments.
// strtod() is more portable.
//
// On AVR Arduino boards, double and float have the same precision.
bool parseFloatToken(char* token, float& value) {

  if (token == nullptr || *token == '\0') {
    return false;
  }


  char* endPtr = nullptr;


  double parsed = strtod(
    token,
    &endPtr
  );


  if (endPtr == token) {
    return false;
  }


  if (*endPtr != '\0') {
    return false;
  }


  value = (float)parsed;


  return isFiniteFloat(value);
}


bool parseIntToken(char* token, int& value) {

  if (token == nullptr || *token == '\0') {
    return false;
  }


  char* endPtr = nullptr;


  long parsed = strtol(
    token,
    &endPtr,
    10
  );


  if (endPtr == token ||
      *endPtr != '\0') {

    return false;
  }


  value = (int)parsed;

  return true;
}


int findAxis(const char* name) {

  if (name == nullptr) {
    return -1;
  }


  for (int i = 0; i < NUM_GAZE_AXES; i++) {

    if (strcmp(
          name,
          axes[i].name
        ) == 0) {

      return i;
    }
  }


  return -1;
}


bool pinIsUsedByGaze(
  uint8_t pin,
  int exceptAxis = -1
) {

  for (int i = 0; i < NUM_GAZE_AXES; i++) {

    if (i == exceptAxis) {
      continue;
    }


    if (axes[i].configured &&
        axes[i].pin == pin) {

      return true;
    }
  }


  return false;
}


bool allGazeAxesConfigured() {

  for (int i = 0; i < NUM_GAZE_AXES; i++) {

    if (!axes[i].configured) {
      return false;
    }
  }


  return true;
}


void writeGazeAxis(
  GazeAxis& axis,
  float degrees
) {

  degrees = constrain(
    degrees,
    axis.minDeg,
    axis.maxDeg
  );


  int rounded =
    (int)round(degrees);


  rounded = constrain(
    rounded,
    0,
    180
  );


  axis.servo.write(rounded);

  axis.currentDeg = degrees;
}


// -----------------------------------------------------------------------------
// Legacy support
// -----------------------------------------------------------------------------

void detachLegacyPin(uint8_t pin) {

  for (int i = 0; i < 7; i++) {

    if (legacyPins[i] == pin) {

      if (legacyServos[i]->attached()) {

        legacyServos[i]->detach();
      }

      return;
    }
  }
}


bool processLegacyCommand(char* command) {

  /*
   * Legacy commands stop working once calibrated
   * gaze configuration begins.
   */
  if (calibratedMode) {
    return false;
  }


  if (!isdigit(command[0])) {
    return false;
  }


  char* comma = strchr(
    command,
    ','
  );


  if (comma == nullptr) {

    Serial.println("ERROR legacy");

    return true;
  }


  *comma = '\0';


  int servoNumber = 0;
  int angle = 0;


  if (!parseIntToken(
        command,
        servoNumber
      ) ||
      !parseIntToken(
        comma + 1,
        angle
      )) {

    Serial.println("ERROR legacy");

    return true;
  }


  if (servoNumber < 1 ||
      servoNumber > 7) {

    Serial.println("ERROR servo");

    return true;
  }


  if (angle < 0 ||
      angle > 180) {

    Serial.println("ERROR angle");

    return true;
  }


  uint8_t pin =
    legacyPins[servoNumber - 1];


  /*
   * Pins 6 and 7 belong exclusively to eyelids.
   */
  if (pin == EYELID_LEFT_PIN ||
      pin == EYELID_RIGHT_PIN) {

    Serial.println("ERROR reserved pin");

    return true;
  }


  /*
   * Prevent legacy mode from stealing a configured mouth pin.
   */
  if (mouthConfigured &&
      pin == mouthPin) {

    Serial.println("ERROR mouth pin");

    return true;
  }


  /*
   * Legacy servos are attached lazily.
   *
   * We intentionally DO NOT attach all seven in setup(),
   * because doing that caused multiple Servo objects to
   * control eyelid pins 6 and 7.
   */
  Servo& servo =
    *legacyServos[servoNumber - 1];


  if (!servo.attached()) {

    servo.attach(pin);
  }


  servo.write(angle);


  Serial.print("OK,");
  Serial.print(servoNumber);
  Serial.print(",");
  Serial.println(angle);


  return true;
}


// -----------------------------------------------------------------------------
// CONFIG
//
// Receives payload only:
//
// eye_left,4,85,90,95
// -----------------------------------------------------------------------------

void processConfig(char* command) {

  char* name =
    strtok(command, ",");

  char* pinToken =
    strtok(nullptr, ",");

  char* minToken =
    strtok(nullptr, ",");

  char* centerToken =
    strtok(nullptr, ",");

  char* maxToken =
    strtok(nullptr, ",");


  if (!name ||
      !pinToken ||
      !minToken ||
      !centerToken ||
      !maxToken) {

    Serial.println("ERROR CONFIG");

    return;
  }


  /*
   * Reject extra unexpected fields.
   */
  if (strtok(nullptr, ",") != nullptr) {

    Serial.println("ERROR CONFIG");

    return;
  }


  int axisIndex =
    findAxis(name);


  if (axisIndex < 0) {

    Serial.println("ERROR axis");

    return;
  }


  int pin = 0;

  float minDeg = 0;
  float centerDeg = 0;
  float maxDeg = 0;


  if (!parseIntToken(
        pinToken,
        pin
      ) ||

      !parseFloatToken(
        minToken,
        minDeg
      ) ||

      !parseFloatToken(
        centerToken,
        centerDeg
      ) ||

      !parseFloatToken(
        maxToken,
        maxDeg
      )) {

    Serial.println("ERROR CONFIG");

    return;
  }


  if (pin < 2 ||
      pin > 13) {

    Serial.println("ERROR pin");

    return;
  }


  /*
   * Pins 6 and 7 are permanently reserved
   * for the eyelids.
   */
  if (pin == EYELID_LEFT_PIN ||
      pin == EYELID_RIGHT_PIN) {

    Serial.println("ERROR reserved pin");

    return;
  }


  /*
   * Also protect the active mouth pin in case
   * MOUTH_CONFIG changed it.
   */
  if (mouthConfigured &&
      pin == mouthPin) {

    Serial.println("ERROR mouth pin");

    return;
  }


  if (pinIsUsedByGaze(
        (uint8_t)pin,
        axisIndex
      )) {

    Serial.println("ERROR duplicate pin");

    return;
  }


  if (!(0 <= minDeg &&
        minDeg <= centerDeg &&
        centerDeg <= maxDeg &&
        maxDeg <= 180)) {

    Serial.println("ERROR limits");

    return;
  }


  GazeAxis& axis =
    axes[axisIndex];


  /*
   * If this pin was previously being used by
   * legacy mode, release it first.
   */
  detachLegacyPin(
    (uint8_t)pin
  );


  /*
   * Reconfiguration may move an axis to
   * a different physical pin.
   */
  if (axis.servo.attached()) {

    axis.servo.detach();
  }


  axis.pin =
    (uint8_t)pin;

  axis.minDeg =
    minDeg;

  axis.centerDeg =
    centerDeg;

  axis.maxDeg =
    maxDeg;


  writeGazeAxis(axis, axis.centerDeg);
  axis.servo.attach(
    axis.pin
  );


  axis.configured = true;


  /*
   * Start newly configured axis at its
   * calibrated center.
   */
  writeGazeAxis(
    axis,
    axis.centerDeg
  );


  /*
   * Disable legacy mode as soon as calibrated
   * configuration starts.
   */
  calibratedMode = true;


  Serial.print("CONFIGURED,");
  Serial.println(axis.name);
}


// -----------------------------------------------------------------------------
// POSE
//
// Receives payload only:
//
// 90,90,92.5,88,91
// -----------------------------------------------------------------------------

void processPose(char* command) {

  if (!allGazeAxesConfigured()) {

    Serial.println(
      "ERROR not configured"
    );

    return;
  }


  float requested[NUM_GAZE_AXES];


  char* token =
    strtok(command, ",");


  for (int i = 0;
       i < NUM_GAZE_AXES;
       i++) {

    /*
     * First iteration uses the first token.
     * Later iterations request subsequent tokens.
     */
    if (i > 0) {

      token =
        strtok(nullptr, ",");
    }


    if (token == nullptr ||
        !parseFloatToken(
          token,
          requested[i]
        )) {

      Serial.println("ERROR POSE");

      return;
    }
  }


  /*
   * Reject additional values.
   */
  if (strtok(nullptr, ",") != nullptr) {

    Serial.println("ERROR POSE");

    return;
  }


  /*
   * Validate EVERY servo first.
   *
   * This prevents malformed frames from
   * partially moving the robot.
   */
  for (int i = 0;
       i < NUM_GAZE_AXES;
       i++) {


    if (!isFiniteFloat(
          requested[i]
        )) {

      Serial.println("ERROR finite");

      return;
    }


    if (requested[i] <
          axes[i].minDeg ||

        requested[i] >
          axes[i].maxDeg) {

      Serial.println("ERROR range");

      return;
    }
  }


  /*
   * Entire frame passed validation.
   */
  for (int i = 0;
       i < NUM_GAZE_AXES;
       i++) {

    writeGazeAxis(
      axes[i],
      requested[i]
    );
  }


  /*
   * Deliberately NO ACK here.
   *
   * Python can continuously stream POSE
   * frames without waiting for Arduino.
   */
}


// -----------------------------------------------------------------------------
// Mouth
//
// Receives payload:
//
// 11,85,90,95,100
// -----------------------------------------------------------------------------

void processMouthConfig(char* command) {

  char* pinToken =
    strtok(command, ",");

  char* minToken =
    strtok(nullptr, ",");

  char* closedToken =
    strtok(nullptr, ",");

  char* openToken =
    strtok(nullptr, ",");

  char* maxToken =
    strtok(nullptr, ",");


  if (!pinToken ||
      !minToken ||
      !closedToken ||
      !openToken ||
      !maxToken) {

    Serial.println(
      "ERROR MOUTH_CONFIG"
    );

    return;
  }


  if (strtok(nullptr, ",") != nullptr) {

    Serial.println(
      "ERROR MOUTH_CONFIG"
    );

    return;
  }


  int pin = 0;

  float minDeg = 0;
  float closedDeg = 0;
  float openDeg = 0;
  float maxDeg = 0;


  if (!parseIntToken(
        pinToken,
        pin
      ) ||

      !parseFloatToken(
        minToken,
        minDeg
      ) ||

      !parseFloatToken(
        closedToken,
        closedDeg
      ) ||

      !parseFloatToken(
        openToken,
        openDeg
      ) ||

      !parseFloatToken(
        maxToken,
        maxDeg
      )) {

    Serial.println(
      "ERROR MOUTH_CONFIG"
    );

    return;
  }


  if (pin < 2 ||
      pin > 13) {

    Serial.println(
      "ERROR mouth pin"
    );

    return;
  }


  /*
   * Mouth cannot steal an eyelid or gaze pin.
   */
  if (pin == EYELID_LEFT_PIN ||
      pin == EYELID_RIGHT_PIN ||
      pinIsUsedByGaze(
        (uint8_t)pin
      )) {

    Serial.println(
      "ERROR mouth pin"
    );

    return;
  }


  if (!(0 <= minDeg &&
        minDeg <= closedDeg &&
        closedDeg <= maxDeg &&

        minDeg <= openDeg &&
        openDeg <= maxDeg &&

        maxDeg <= 180)) {

    Serial.println(
      "ERROR mouth limits"
    );

    return;
  }


  /*
   * Release legacy control of this physical pin
   * if it was previously being used.
   */
  detachLegacyPin(
    (uint8_t)pin
  );


  if (mouth.attached()) {

    mouth.detach();
  }


  mouthPin =
    (uint8_t)pin;

  mouthMinDeg =
    minDeg;

  mouthClosedDeg =
    closedDeg;

  mouthOpenDeg =
    openDeg;

  mouthMaxDeg =
    maxDeg;


  mouth.write((int)round(mouthClosedDeg));
  mouth.attach(
    mouthPin
  );


  mouth.write(
    (int)round(
      mouthClosedDeg
    )
  );


  mouthConfigured = true;

  mouthTalking = false;
  mouthIsOpen = false;


  Serial.println(
    "MOUTH_READY"
  );
}


void closeMouth() {

  if (!mouthConfigured) {
    return;
  }


  float position =
    constrain(
      mouthClosedDeg,
      mouthMinDeg,
      mouthMaxDeg
    );


  mouth.write(
    (int)round(position)
  );


  mouthIsOpen = false;
}


void updateMouth() {

  if (!mouthConfigured) {
    return;
  }


  /*
   * Watchdog:
   *
   * Python should renew TALK,1 approximately
   * every 200 ms.
   *
   * If communication stops for 600 ms,
   * automatically stop and close the mouth.
   */
  if (mouthTalking &&
      millis() - lastTalkMillis >
        MOUTH_TIMEOUT_MS) {

    mouthTalking = false;

    closeMouth();
  }


  if (!mouthTalking) {
    return;
  }


  if (millis() -
        lastMouthAnimationMillis <
      MOUTH_ANIMATION_MS) {

    return;
  }


  lastMouthAnimationMillis =
    millis();


  if (mouthIsOpen) {

    mouth.write(
      (int)round(
        constrain(
          mouthClosedDeg,
          mouthMinDeg,
          mouthMaxDeg
        )
      )
    );


    mouthIsOpen = false;

  } else {

    mouth.write(
      (int)round(
        constrain(
          mouthOpenDeg,
          mouthMinDeg,
          mouthMaxDeg
        )
      )
    );


    mouthIsOpen = true;
  }
}


// -----------------------------------------------------------------------------
// TALK
//
// Receives payload:
//
// 1
// or
// 0
// -----------------------------------------------------------------------------

void processTalk(char* command) {

  int enabled = 0;


  if (!parseIntToken(
        command,
        enabled
      )) {

    Serial.println("ERROR TALK");

    return;
  }


  if (!mouthConfigured) {

    Serial.println("ERROR mouth");

    return;
  }


  if (enabled == 1) {

    if (!mouthTalking) {
      lastMouthAnimationMillis = millis();
    }
    mouthTalking = true;

    lastTalkMillis =
      millis();


  } else if (enabled == 0) {

    mouthTalking = false;

    closeMouth();


  } else {

    Serial.println("ERROR TALK");

    return;
  }
}


// -----------------------------------------------------------------------------
// Command dispatcher
// -----------------------------------------------------------------------------

void processCommand(char* command) {

  if (command == nullptr ||
      command[0] == '\0') {

    return;
  }


  /*
   * Legacy:
   *
   * 1,90
   * 2,120
   */
  if (processLegacyCommand(command)) {
    return;
  }


  /*
   * IMPORTANT:
   *
   * Do NOT strtok() the command name here.
   *
   * strtok() modifies the original buffer and
   * caused the previous CONFIG parser bug.
   */


  // CONFIG,<payload>
  if (strncmp(
        command,
        "CONFIG,",
        7
      ) == 0) {

    processConfig(
      command + 7
    );

    return;
  }


  // POSE,<payload>
  if (strncmp(
        command,
        "POSE,",
        5
      ) == 0) {

    processPose(
      command + 5
    );

    return;
  }


  // MOUTH_CONFIG,<payload>
  if (strncmp(
        command,
        "MOUTH_CONFIG,",
        13
      ) == 0) {

    processMouthConfig(
      command + 13
    );

    return;
  }


  // Explicit acknowledged close, independent of speech heartbeat timing.
  if (strcmp(command, "MOUTH_CLOSE") == 0) {
    if (!mouthConfigured) { Serial.println("ERROR mouth"); return; }
    mouthTalking = false;
    closeMouth();
    Serial.print("MOUTH_CLOSED,");
    Serial.println((int)round(mouthClosedDeg));
    return;
  }

  // TALK,<payload>
  if (strncmp(
        command,
        "TALK,",
        5
      ) == 0) {

    processTalk(
      command + 5
    );

    return;
  }


  if (strcmp(
        command,
        "PING"
      ) == 0) {

    Serial.println("PONG");

    return;
  }


  if (strcmp(
        command,
        "CENTER"
      ) == 0) {

    if (!allGazeAxesConfigured()) {

      Serial.println(
        "ERROR not configured"
      );

      return;
    }


    for (int i = 0;
         i < NUM_GAZE_AXES;
         i++) {

      writeGazeAxis(
        axes[i],
        axes[i].centerDeg
      );
    }


    return;
  }


  /*
   * Unknown commands intentionally ignored.
   *
   * This allows other software to share the
   * serial connection without generating
   * unnecessary errors.
   */
}


// -----------------------------------------------------------------------------
// Setup
// -----------------------------------------------------------------------------

void setup() {

  Serial.begin(115200);


  /*
   * Eyelids permanently own pins 6 and 7.
   */
  // Set the initial pulse before attachment; do not briefly command 90 degrees.
  eyelidLeft.write(EYELID_LEFT_OPEN_DEG);
  eyelidRight.write(EYELID_RIGHT_OPEN_DEG);

  eyelidLeft.attach(
    EYELID_LEFT_PIN
  );

  eyelidRight.attach(
    EYELID_RIGHT_PIN
  );


  blinkStarted = millis();


  /*
   * IMPORTANT:
   *
   * We DO NOT attach legacyServos[] here.
   *
   * The previous version attached legacy servo
   * objects to pins 6 and 7 while the eyelid
   * Servo objects were also attached to those
   * exact pins.
   *
   * Legacy servos are now attached only when
   * a legacy command is actually received.
   */


  /*
   * Protocol version expected by Python.
   */
  Serial.println(
    "GAZE_READY,2"
  );
}


// -----------------------------------------------------------------------------
// Main loop
// -----------------------------------------------------------------------------

void loop() {

  updateEyelids();
  while (Serial.available() > 0) {
    updateEyelids();
    updateMouth();

    char c =
      Serial.read();


    /*
     * If the previous command exceeded the
     * input buffer, ignore everything until
     * its newline.
     */
    if (discardUntilNewline) {

      if (c == '\n') {

        discardUntilNewline = false;

        inputLength = 0;
      }

      continue;
    }


    if (c == '\n') {

      inputBuffer[inputLength] =
        '\0';


      processCommand(
        inputBuffer
      );


      inputLength = 0;


    } else if (c != '\r') {


      if (inputLength <
          INPUT_BUFFER_SIZE - 1) {

        inputBuffer[inputLength++] =
          c;


      } else {

        /*
         * Command exceeded buffer.
         *
         * Ignore the remainder of this entire
         * line instead of accidentally treating
         * its tail as another command.
         */
        inputLength = 0;

        discardUntilNewline = true;
      }
    }
  }


  updateMouth();
}