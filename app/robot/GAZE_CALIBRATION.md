# Three-axis USB robot gaze

Use the Uno sketch `firmware/robot_controller/robot_controller.ino` for this workflow.
The ESP32/Pico paths and original calibration REPL are unchanged. Python's old
LOOK/SET protocol was not implemented by the Uno's numeric-only sketch; this
workflow uses CONFIG and POSE instead. Do not run two controllers on the port.

## 1. Servo limits

Copy `config/robot-servos.example.json` to `config/robot-servos.json`. Verify the
pins: placeholders are eyes=10, neck=9, head pitch=8. These are **not measured
limits**. The 85/90/95 degree defaults are deliberately narrow but cannot guarantee
mechanical safety. Check the linkage/neutral position before powering servos.
Upload the Uno sketch using the Arduino IDE with the Servo library installed.

```sh
.venv/bin/python tools/calibrate_robot.py limits --port /dev/cu.usbmodemYOUR_DEVICE
```

Terminal keys followed by Enter: `a/d` eyes left/right, `j/l` neck left/right,
`i/k` head up/down. Lowercase jogs 1 degree; uppercase jogs 5 degrees. `c` centers
all three; `q` quits holding the last pose. Every command displays all three
commanded angles (there is no position feedback). `--mock` exercises this without
serial hardware. `--baud` defaults to 115200 and must match the sketch.

Edit min_deg/center_deg/max_deg in your JSON as you measure each axis. To explore
past a provisional endpoint, quit, widen its JSON limit cautiously, and restart;
the CLI never bypasses limits. Set invert=true if that axis's jog direction is
reversed. Never choose a center outside the safe interval. Save the measured JSON
before world calibration. Initial centering is immediate, so choose a known safe
center. Other servos are not attached on boot. Legacy numeric commands still work
before CONFIG, but are rejected after entering calibrated mode to protect bounds.

## 2. Nine-point world calibration

```sh
.venv/bin/python tools/calibrate_robot.py world --port /dev/cu.usbmodemYOUR_DEVICE
```

Focus the OpenCV window; keys now work without terminal Enter. Move one blue
water bottle to each prompted position of the 3x3 workspace. The existing YOLO
ObjectTracker detects bottles; a blue HSV pixel check filters candidates. Use
normal lighting and remove other blue bottles. Missing or ambiguous detections
cannot be saved. The preview is unmirrored; positions refer to camera-image
left/right, not the robot's anatomical left/right.

Use j/l and i/k (uppercase for 5 degrees) to aim the neck/head at the bottle.
Eyes remain centered and eye jogs are disabled. Press Enter to capture the current
actual detected camera center and commanded physical angles. Each capture
atomically checkpoints `config/robot-gaze.json`. All nine points are required for
tracking. Starting world mode starts a new session; its first save replaces the
previous file. Quit leaves a partial checkpoint, which runtime rejects. Use
`--calibration PATH` to keep multiple setups. Keep camera and robot mounts fixed;
repeat calibration if either moves or any servo configuration changes.

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
`gaze.hold()` on loss. The old RobotController.look_at path is not automatically
switched to calibrated tracking.

Inverse-distance interpolation uses actual measured positions, is exact at the
samples, and stays within sampled angles outside the workspace. It is an
approximation, not a camera geometry model. Targets have a 0.015 normalized
coordinate deadzone. Eyes lead large changes by 120 ms; residual neck error drives
eye deflection back toward center as the neck catches up. Exponential smoothing
and 100 deg/s eye / 30 deg/s neck/head limits use elapsed time capped at 100 ms.
Inversion affects jog direction and eye compensation; measured neck/head angles
are physical angles and must not be inverted again during interpolation.

Protocol: newline ASCII at 115200. Firmware announces GAZE_READY,1; Python waits
for boot, sends CONFIG,name,pin,min,center,max and waits for CONFIGURED,name for
each axis, then streams POSE,eyes,neck,head. Firmware validates the whole pose
before moving, rejects nonfinite/out-of-range data, and attaches only configured
axes. Valid pose frames have no reply to avoid filling the serial receive buffer.
Servo pulse resolution and mechanical accuracy still require physical testing.
