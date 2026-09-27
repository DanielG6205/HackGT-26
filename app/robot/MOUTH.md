# Mouth servo (eighth servo, Arduino pin 11)

The confirmed wiring is eye yaw on 4/5, eyelids on 6/7, vertical head movement
on 8/9, neck rotation on 10, mouth on 11. Left/right within each pair is assumed
in that order; swap the corresponding JSON pins if the sides are reversed.
Python gaze/mouth commands do not move eyelids. This change does not add an
Arduino blinking routine; retain your eyelid routine when incorporating the
updated sketch.

Upload `firmware/robot_controller/robot_controller.ino` with the mouth protocol
support. Copy `config/robot-mouth.example.json` to `config/robot-mouth.json` and
measure the mouth's safe closed/open angles. The 85..95 degree limits and
90-degree closed position are placeholders. Open may be below closed if the
linkage is reversed. Both must be inside the measured limits. Values are integer
degrees. The existing gaze config now uses the confirmed pins; recalibrate world
gaze after changing pins or geometry.

Enable mouth motion for any program using SpeechService with:

```sh
export ROBOT_MOUTH_CONFIG=config/robot-mouth.json
export ROBOT_MOUTH_PORT=/dev/cu.usbmodemYOUR_DEVICE
```

These can also be put in the existing .env. ROBOT_SERIAL_PORT is a fallback if
ROBOT_MOUTH_PORT is unset. Match the port used by the main application's --port
exactly to share its connection. Use USB at 115200 for this sketch. No mouth
hardware is opened and speech behaves as before when ROBOT_MOUTH_CONFIG is unset.
Setting it enables mouth motion even if a separate gaze controller is mocked.

The mouth starts just before the first complete audio sample is submitted, loops
an open/closed pattern, and closes after the output stream drains or on an error.
It does not animate during the initial ElevenLabs request or empty responses.
This follows playback start/end, not phonemes or silence inside speech. A stalled
stream after playback starts can therefore keep the pattern running until speech
ends or fails. Existing speech callbacks, audio format, text generation, and game
logic remain unchanged. A failed mouth connection logs a warning and audio
continues.

The mouth shares an already-open Python SerialTransport when available; serial
writes are locked so its heartbeat cannot interleave with gaze commands. If it
opens its own connection, it retains it between utterances to avoid resetting the
Arduino each time, and closes it on process exit. Do not open the same USB device
from two separate programs (for example, standalone calibration and speech).

Firmware accepts MOUTH_CONFIG,pin,min,closed,open,max and replies MOUTH_READY.
TALK,1 starts/renews animation; TALK,0 closes the mouth. The host renews every
200 ms; firmware closes after 600 ms without renewal if the process/link dies.
Mouth commands do not alter the five-angle POSE protocol or seven legacy slots.
Firmware rejects mouth configuration on any existing legacy servo pin (4..10).

## What gaze calibration currently guarantees

`tools/calibrate_robot.py track` loads the nine-point robot calibration and
interpolates neck and both vertical servo angles. Eyes briefly lead the neck and
then return toward their individually calibrated centers. With correctly aligned
eye centers, the final head pose aims the eyes at the target. This is approximate
and needs physical validation; independent eye target angles are not learned by
the nine-point calibration.

The main application (`app.main`) still constructs the legacy RobotController
and does **not** load robot-gaze.json. Its LOOK commands are not the calibrated
POSE protocol. Therefore completing calibration alone does not make the main
conversation/game use calibrated gaze. This mouth change deliberately leaves
that runtime routing unchanged; use the standalone track command to validate
gaze. The human gaze calibration and eye-calibration gain/offset JSON are separate
from robot world calibration.
