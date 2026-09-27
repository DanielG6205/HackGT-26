# Five-servo USB robot gaze

Use the Uno sketch `firmware/robot_controller/robot_controller.ino` for this workflow.
The ESP32/Pico paths and original calibration REPL are unchanged. Python's old
LOOK/SET protocol was not implemented by the Uno's numeric-only sketch; this
workflow uses CONFIG and POSE instead. Do not run two controllers on the port.

## 1. Servo limits

Copy `config/robot-servos.example.json` to `config/robot-servos.json`. Verify the
pins: eye_left=4, eye_right=5, neck=10, lift_left=8, lift_right=9.
Pins 6/7 are reserved for Arduino eyelids; pin 11 is the separate mouth servo. Left/right names refer to the robot’s own left/right. These are **not measured
limits**. The 85/90/95 degree defaults are deliberately narrow but cannot guarantee
mechanical safety. Check the linkage/neutral position before powering servos.
Upload the Uno sketch using the Arduino IDE with the Servo library installed.

```sh
.venv/bin/python tools/calibrate_robot.py limits --port /dev/cu.usbmodemYOUR_DEVICE
```

Terminal keys followed by Enter:

| Keys | Movement |
| --- | --- |
| a/d | Left eye left/right |
| f/h | Right eye left/right |
| z/x | Both eyes left/right |
| j/l | Neck pivot left/right |
| r/v | Left vertical servo individually |
| t/b | Right vertical servo individually |
| i/k | Paired vertical movement (head pitch) |
| u/o | Opposed vertical movement (head tilt) |

Lowercase jogs 1 degree; uppercase jogs 5 degrees. `c` centers
all five; `q` quits holding the last pose. Every command displays all five
commanded angles (there is no position feedback). `--mock` exercises this without
serial hardware. `--baud` defaults to 115200 and must match the sketch.

Edit min_deg/center_deg/max_deg in your JSON as you measure each axis. To explore
past a provisional endpoint, quit, widen its JSON limit cautiously, and restart;
the CLI never bypasses limits. Set invert=true if that axis's jog direction is
reversed. Never choose a center outside the safe interval. Save the measured JSON
before world calibration. For the vertical pair, set inversion so the same logical
jog sign raises/lowers both sides together, even if mirrored mounting requires
opposite physical shaft rotations. Pitch applies the same logical delta to both;
tilt applies opposite logical deltas. Paired jogs stop together if either servo
reaches its limit, avoiding unintended tilt from one-sided clamping. Individual
jogs are for measuring limits and aligning the linkage. Initial centering is immediate, so choose a known safe
center. Other servos are not attached on boot. Legacy numeric commands still work
before CONFIG, but are rejected after entering calibrated mode to protect bounds.

## 2. Five-point world calibration

```sh
.venv/bin/python tools/calibrate_robot.py world --port /dev/cu.usbmodemYOUR_DEVICE
```

Focus the OpenCV window; keys now work without terminal Enter. Move one blue
water bottle to each prompted position: center, top, bottom, left, then right. The existing YOLO
ObjectTracker detects bottles; a blue HSV pixel check filters candidates. Use
normal lighting and remove other blue bottles. Missing or ambiguous detections
cannot be saved. The preview is unmirrored; positions refer to camera-image
left/right, not the robot's anatomical left/right.

Use j/l and i/k (uppercase for 5 degrees) to aim the neck/head at the bottle.
Use u/o to level the head if needed; individual vertical jogs remain available.
The working mechanical model is that the two vertical servos together control
pitch and their difference controls tilt; confirm this using small jogs.
Eyes remain centered and eye jogs are disabled. Press Enter to capture the current
actual detected camera center and all three commanded neck/vertical angles:
`camera_x`, `camera_y`, `neck_angle`, `lift_left_angle`, `lift_right_angle`.
Both eye servos remain at their individual centers. Saving both vertical angles
preserves the manually aligned pitch/tilt without assuming identical linkages. Each capture
atomically checkpoints `config/robot-gaze.json`. All five points are required for
tracking. Starting world mode starts a new session; its first save replaces the
previous file. Quit leaves a partial checkpoint, which runtime rejects. Use
`--calibration PATH` to keep multiple setups. Keep camera and robot mounts fixed;
repeat calibration if either moves or any servo configuration changes. Five-servo
calibration uses JSON version 2; old three-axis calibration must be repeated.

## 3. Runtime tracking

```sh
.venv/bin/python tools/calibrate_robot.py track --port /dev/cu.usbmodemYOUR_DEVICE
```

This robot-only loop reuses Camera and ObjectTracker without loading speech,
games, or AI. `--camera`, `--model`, and `--device` select existing vision inputs.
The loop holds the last pose on detection loss. q exits holding the last pose.

For another existing detector consumer, construct GazeController with a connected
RobotController, load_axes(path), and GazeMap.load(path, axes); initialize once,
then call `gaze.look_at(*tracked_object.center_normalized)` each frame and
`gaze.hold()` on loss. The main app now wraps RobotController in GazeController and loads this saved
calibration. Run it with `--transport serial --port DEVICE` after calibration.

Inverse-distance interpolation uses actual measured positions, is exact at the
samples, and stays within sampled angles outside the workspace. It is an
approximation, not a camera geometry model. Targets have a 0.015 normalized
coordinate deadzone. Eyes lead large changes by 120 ms; residual neck error drives
both eyes’ deflection back toward their respective centers as the neck catches up. Exponential smoothing
and 100 deg/s eye / 30 deg/s neck/head limits use elapsed time capped at 100 ms.
Inversion affects jog direction and eye compensation; measured neck/vertical angles
are physical angles and must not be inverted again during interpolation.

Protocol: newline ASCII at 115200. Firmware announces GAZE_READY,2; Python waits
for boot, sends CONFIG,name,pin,min,center,max and waits for CONFIGURED,name for
each servo, then streams
`POSE,eye_left,eye_right,neck,lift_left,lift_right` in that fixed order.
Re-upload the updated sketch: the protocol version prevents an old three-servo
sketch from accepting a five-servo session. Firmware validates the whole pose
before moving, rejects nonfinite/out-of-range data, and attaches only configured
axes. Valid pose frames have no reply to avoid filling the serial receive buffer.
Servo pulse resolution and mechanical accuracy still require physical testing.


## Mouth animation during ElevenLabs playback

See [MOUTH.md](MOUTH.md) for the opt-in mouth setup. Speech playback uses the
mouth channel independently of gaze. Pins 6/7 remain under Arduino ownership.
The robot has seven existing servos plus the mouth; five participate in world
gaze calibration, two are eyelids, and the eighth is the mouth.

New world sessions capture five points. Existing complete nine-point files still load.
