# HackGT-26 — Ottis

Ottis combines webcam object/gaze tracking, spoken questions, and conversation.
The Arduino Uno camera test moves servo 1 for a correct answer and servo 3 for
successfully looking toward the requested object.

## Setup

Use Python 3.10+ and run commands from the repository root:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env  # First setup only; preserve your existing .env.
```

On Windows, activate with `.venv\Scripts\Activate.ps1`. On Linux, audio may need
`libportaudio2`. Allow microphone and camera access for your terminal or IDE.

Configure these values in `.env`:

- `ELEVENLABS_API_KEY` and `ELEVENLABS_VOICE_ID` for speech and transcription.
- `XAI_API_KEY` (alias `GROK_API_KEY`) for the default Grok conversation provider.
- Alternatively, `GROQ_API_KEY` (alias `GROQ_APIKEY`) and `--brain groq` for Groq.
- Optional `AUDIO_INPUT_DEVICE` and `AUDIO_OUTPUT_DEVICE` to select audio devices.

List audio devices with `python -m sounddevice`. The microphone must support
mono 16 kHz input; the speaker must support mono 24 kHz output. Existing shell
environment variables take precedence over `.env`.

## Wake-triggered shared-attention application

```sh
python -m app.main --mock-robot                  # Camera and speech, simulated eyes
python -m app.main --transport bluetooth        # LOOK-compatible robot firmware
python test_full.py --mock-robot                # Same application, compatibility launcher
python test_ottis.py --brain grok                # Same application, simulated eyes
```

The application stays silent until the transcribed speech contains Ottis (also
accepts Otis/ Ottish). It always begins “Hi I'm Ottis, what's your name?”, waits
for the name, asks “[Name], correct?”, and saves it only after confirmation in
`.ottis/name.json`. A new activation asks for the name again even if one is saved.
Say “Ottis forget my name” to delete it, or “skip” during name entry to play
without saving a name.

After confirmation, it asks “Can you look at me?” only when a detected face is
looking away from center. Missing faces do not trigger that request or count as
centered attention. After several centered frames, it chooses a visible familiar
object outside the center, asks “Do you know what a phone is?” (using the actual
object label), and waits for an answer. It acknowledges the answer, asks the child
to look at the object, and aims the robot eyes toward that same tracked object.
Five consecutive gaze frames within the angular tolerance earn “Hurray!”; speech playback, lost
objects, missing faces, and long frame gaps cannot count toward that streak.

The eyes then return toward the child's face. Ottis requests looking back only
if the child is still looking away, waits for centered attention, and selects a
different object category. “Skip”/“no thanks” skips a trial; “stop”/“goodbye” returns
to silent wake waiting. Looking timeouts are neutral. No answer or no more new
objects eventually returns to wake waiting. Object questions and acknowledgments call the selected AI provider (xAI/Grok by
default). Wake/name setup, gaze prompts, and success scoring remain scripted.
Requests run on the audio worker so the camera stays responsive. `[AI]` logs
show requests, completions, and any fallback after an API failure. The selected
object label, question, and child answer are sent to the provider; raw images
are not sent. Built-in wording is used if the service fails or returns an
overlong or incorrectly formatted response.

### Eye alignment

Mount the camera close to the robot's eyes and keep it fixed. Start with mock
movement, then set the physical centers, limits and inversion in your compatible
firmware. The Pico W firmware currently has `LED_TEST_MODE = True`: it receives
commands but does **not** drive servos until the wiring is identified and that
setting is disabled. The numbered-angle Uno and camera-reward sketches do not
support the application's LOOK commands.

`python tools/calibrate_robot.py --help` shows the existing hardware calibration
console. Its `look X Y` command checks normalized camera targets: center is
`0.5 0.5`, image right increases X, and image down increases Y. Start near center.

Copy `config/eye-calibration.example.json` to a local calibration JSON and run:

```sh
python -m app.main --transport bluetooth --eye-calibration config/eye-calibration.local.json
```

Each axis uses `0.5 + (camera_coordinate - 0.5) * gain + offset`, clamped to
0–1 before sending LOOK commands. Set a gain to -1 to reverse an axis, reduce its
magnitude to reduce movement, and adjust offsets to align the neutral direction.
Offsets are restricted to ±0.25 and gain magnitudes to (0, 2]. This mapping affects
actual commands, not just displayed angles. Firmware remains responsible for
physical servo travel limits. This is a manual 2D alignment; it does not estimate
object depth or calibrate precise eye fixation.

## Separate camera and servo reward demo


```sh
python test_camera_servos.py                         # Mock servos, real camera/audio
python test_camera_servos.py --brain groq --camera 1 # Alternate provider/camera
```

Answer “four” to the dog-legs question to trigger servo 1. Follow the spoken
object-looking prompt to trigger servo 3. For real hardware, upload the dedicated
Uno sketch and follow the [wiring and calibration guide](firmware/camera_servo_test/README.md).
That guide explains rest positions, small pulse-width steps, and USB options.
The camera test uses **servo 1 on pin 4 and servo 3 on pin 6**.

The main shared-attention application can also be launched without servo control:

```sh
python test_ottis.py --camera 0 --width 1280 --height 720 --imgsz 640
```

Both demos accept `--input-device INDEX`, `--brain grok|groq`, and `--yolo-model`.
Press **q** or close the camera window to stop.

In the separate camera-servo reward demo, say **“Hi Ottis”** (or “Hi Otis”) to enter conversation. Ottis asks for a first
name/nickname and confirms it before saving it in `.ottis/name.json`. Say **“skip”**
to skip saving a name, or **“Ottis forget my name”** to delete it. This is name
memory, not face recognition. Say **“let’s play”**, **“goodbye”**, or **“stop talking”**
to return to the game. Conversation also expires after 45 seconds of inactivity.

Wait until Ottis finishes speaking before answering. Microphone and speech
share one worker. The console shows the selected microphone and heard transcripts.
Audio is sent to ElevenLabs even while waiting for the wake phrase; activated
conversation turns and summarized vision context go to the selected AI provider.
API usage can consume credits. Audio and conversations are not saved locally.

## Vision

```sh
python test_vision.py
python test_gaze_interaction.py --silent
```

The first run downloads YOLO and Google's Face Landmarker into
`app/models/vision/`; later runs reuse them. Vision runs locally. Keep the cached
models if you want to avoid downloading them again.

Use `--camera` to select a webcam. The vision demo supports `--yolo-model`,
`--face-model`, `--imgsz`, and `--device` overrides; see each script's `--help`.
The default YOLO26x model prioritizes accuracy. Smaller weights, such as
`--yolo-model yolo26n.pt --imgsz 416`, can reduce processing time.
Keep the two OpenCV distributions at the same versions in `requirements.txt`;
MediaPipe and Ultralytics use the shared `cv2` module.

Directions refer to the **unmirrored camera image**: right is image right and
up is image up. Gaze scoring combines head and iris observations and requires
several fresh matching frames. Missing faces and lost objects cannot count as
success. Direction matching is a coarse heuristic: it cannot distinguish two
objects in the same image sector or prove fixation on a particular object.
Center objects cannot earn directional success until they move to a side.

## Other hardware and diagnostics

These are separate workflows with different firmware protocols and pin mappings:

| Script | Purpose |
| --- | --- |
| `test_servos.py --list-ports` | List Uno USB ports |
| `test_servos.py --port DEVICE` | Manual numbered-angle commands for the legacy Uno sketch (servo 1 = pin 10); boot centers all seven servos |
| `test_servos.py` | BLE angle commands for a compatible seven-servo controller |
| `test_pico.py` | Pico W BLE packet test; see the [Pico guide](firmware/robot_controller_pico_w/README.md) |
| `test_full.py` | Camera, conversation, and motion for LOOK-protocol firmware; incompatible with the numbered-angle Uno sketch |
| `test_arduino.py`, `tools/calibrate_robot.py` | Legacy LOOK-protocol diagnostics/calibration |
| `test_speech.py`, `test_listener.py` | Individual speech/transcription diagnostics |
| `test_conversation.py` | Conversation-only Groq demo |

Do not use the legacy numbered-angle or LOOK-protocol tools with the camera-servo
sketch. Its supported commands and calibration are documented in its own guide.

## Code and tests

- `app/vision/`: camera, object tracking, gaze, overlays, and game state.
- `app/conversation/`: conversation worker and Ottis dialogue.
- `app/speech/`, `app/ai/`: speech/transcription and AI provider adapters.
- `app/robot/`: servo rewards, hardware transports, and legacy motion controls.
- `firmware/`: separate sketches for each hardware/protocol combination.
- `tests/`: offline automated tests. Root `test_*.py` files are manual demos.

```sh
python -m unittest discover -s tests -v
python -m pip check
```

Offline tests do not verify servo travel, live camera accuracy, audio devices,
or authenticated API calls. Calibrate the physical assembly before use and
supervise the child-facing demo.

### Angular gaze diagnostics

During each requested object-looking trial, `[LOOK]` console messages appear
about twice per second, including while speech pauses scoring. They show the
requested object/track ID, estimated gaze yaw and pitch, head yaw and pitch,
object target angles, angular error, tolerance, the matching-frame count, and
why a frame does not count. Positive yaw means image right; positive pitch means
image down. Missing eye landmarks are explicitly reported as head-only tracking.

The main application's matcher uses continuous angular distance, not compass
sectors. Default tolerance is 12 degrees, with an 8-degree neutral zone. The
camera overlay also shows angles. The older standalone gaze-game diagnostic
continues to use its legacy sector matcher.

```sh
python test_full.py --mock-robot --gaze-tolerance 12 --camera-hfov 60
```

If the estimated gaze is biased while looking straight at the camera, use that
neutral reading as `--gaze-yaw-offset` and `--gaze-pitch-offset` (degrees).
`--camera-hfov` controls projection of the object's image position into camera
angles. These settings are separate from servo alignment. The eye-angle scale
is heuristic and the camera field of view defaults to an estimate: converting to
angles does not itself establish more accurate fixation detection. Object camera
bearings and a person's viewing direction are only approximately comparable;
the system does not measure person-to-object depth or reconstruct a 3D gaze ray.

### Test eyes independently

`python test_vision.py` now loads only face/iris tracking by default, without
YOLO, audio, or robot movement. Keep your head still and move your eyes to check
the `IRIS ONLY` yaw/pitch readings in the window and `[EYES]` console output.
Head angles are printed separately. Missing iris observations explicitly show
`EYES UNAVAILABLE`; head motion is never substituted for these readings.
Press **c** while looking at the camera to average 20 valid frames as the neutral
position. This calibration applies only to the diagnostic session, not the game.
Press **q** to quit. `--frames 60` runs a short capture; `--objects` restores the
full object/face preview. Iris angles remain heuristic estimates.

### Full interaction test without robot movement

```sh
python tests/test_full.py
```

This launcher always forces mock robot transport, including when hardware
endpoints are configured in `.env`. Camera, object detection, face/iris tracking,
microphone, speech, and the wake/name/question/game sequence remain live. Say
“Ottis” to begin and press **q** in the camera window to quit. The production
entry point supports the same mode with `python -m app.main --mock-robot`.

Object-looking success now accepts either an independently matching head pose
or the combined eye/head gaze estimate. A head turn is not canceled by iris
compensation, and eye-led looking still works with a neutral head. Both use the
same angular tolerance and require the sustained fresh-frame streak. A neutral
cue, missing target, missing face, and playback cannot produce success. Console
logs show `gaze_error`, `head_error`, and `cue=head`, `cue=gaze`, or both. This
recognizes approximate attention direction, not confirmed fixation.

Return-to-camera attention now accepts either centered head pose or centered gaze
within the configured gaze tolerance. `[ATTENTION]` logs show both readings,
which cue counts, and the hold-frame progress. While looking directly at the
camera, press **c** in the full application to save neutral head/gaze offsets for
this session. No face or invalid head pose cannot calibrate. Object detection is
skipped during name entry and return-attention steps to keep face tracking fast.

The full application starts microphone capture before connecting transcription,
buffering up to 10 seconds in memory. Its default end-of-speech silence wait is
now 0.6 seconds (`--vad-silence 1.0` allows longer pauses). `[MIC]` logs distinguish
recording from transcription readiness. Speech playback still finishes before
the microphone starts, and network latency still affects the final transcript.

### Guided five-point calibration (default)

`python tests/test_full.py` now starts with calibration before microphone/game
startup: **center → up → down → left → right**. Look toward the yellow marker in
the **unmirrored camera image**, press **Space**, and hold comfortably for 20
tracked frames. Move your eyes and/or head as you intend to during the game;
keep your face visible and your seat/camera fixed. **r** restarts; **q** exits.
Calibration retries if the directional readings are too similar or inconsistent.

The per-person map uses median head/gaze readings to map the five positions to
normalized image coordinates. A cue must have enough usable samples and distinct
horizontal and vertical ranges to be enabled. Either calibrated head pose or
calibrated gaze can count. During object trials, `[LOOK PIXELS]` shows the estimated
pixel positions and target bounding box. Matching allows a margin of 12% of image
width/height around that box and still requires consecutive fresh matching frames.
Missing targets/faces cannot succeed. Centered cues do not earn object success.

Calibration is held in memory and repeated on restart; it is not sent to Grok.
It approximates general direction rather than reconstructing a 3D gaze ray.
`--skip-gaze-calibration` retains the prior angular matcher and **c** neutral-offset
shortcut. With calibrated pixel matching, restart to redo all five points.
