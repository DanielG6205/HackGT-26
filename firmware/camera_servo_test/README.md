# Camera + question + servo test (Arduino Uno USB)

Run from the repository root. This reuses `test_ottis.py`: camera, face/gaze
tracking, YOLO objects, microphone, speech, and wake-gated conversation.
Existing API keys/audio setup are required. No hardware is contacted without `--port`.

```sh
.venv/bin/python test_camera_servos.py --brain groq
```

The game asks “How many legs does a dog have?” Say “four” or “four legs.”
A correct answer triggers servo 1 once. Incorrect answers retry; silence or a
timeout never triggers servo 1. The existing game then asks you to look at a
detected object. A held gaze in its image sector triggers servo 3 once. This is
coarse direction matching, not proof of fixation on that particular object.
If you enter conversation with “Hi Ottis,” say “let’s play” to resume the game.

## Hardware and calibration

Upload `camera_servo_test.ino` from this directory to the Uno using Arduino IDE
and the Servo library. Close Serial Monitor before running Python. The original
`puppet.ino` reads potentiometers and cannot receive these commands. The legacy
`robot_controller.ino` uses different pins and centers every servo on boot;
it is not compatible with this test.

This sketch matches **puppet numbering: servo 1 = pin 4, servo 3 = pin 6**.
Other servos are never attached. Use an appropriate external servo supply with
common ground to the Uno; do not power the servo bank from the Uno USB supply.

The reference positions from puppet are **1200 µs for servo 1 and 1650 µs for
servo 3**. They are not measured safe angles. Pulse width avoids guessing a
degrees-to-pulse conversion, which differs between sketches and servos.

1. Disconnect the mechanical linkage/horn load before first positioning. The
   first ARM command sets an absolute position; software cannot know the actual
   initial shaft position, so even a small later step cannot prevent that jump.
2. Upload the sketch. Boot does not enable any servo. Find the USB port with
   `.venv/bin/python test_servos.py --list-ports`.
3. Run the command below with your actual port and check the unloaded positions.
   Explicit rest flags acknowledge the positions you intend to test.
4. Stop with `q`. Align the linkage at the checked rest positions before testing
   under load. If needed adjust the rest flags in small increments. The sketch
   enforces 1150–1250 µs for servo 1 and 1600–1700 µs for servo 3; these are
   provisional software bounds, not mechanically verified limits. If they do
   not suit your assembly, calibrate unloaded before editing `low`/`high` in
   the sketch and matching reference validation in `app/robot/camera_test.py`.

```sh
.venv/bin/python test_camera_servos.py --brain groq \
  --port /dev/cu.usbmodemYOUR_PORT \
  --servo1-rest-us 1200 --servo3-rest-us 1650 --step-us 10
```

Use `--brain grok` for the existing xAI setup instead. If movement is too large,
reduce `--step-us` to 5 or 2. Use a negative step to reverse direction. Maximum
step is 25 µs in either direction; it is always relative to rest, never cumulative.
Firmware ramps at 2 µs per 20 ms and returns to rest after one second even if
the camera or host stalls. `q` detaches PWM without another commanded position;
detaching removes holding torque. Disconnect servo power if motion binds.

Mock mode prints ARM/PULSE/OFF commands but still uses real camera/audio and
network speech services. It verifies event flow, not physical travel.
