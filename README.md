# Robot voice conversation

The conversation demo currently uses `DefaultBrain`, which replies “Got it! Tell me more.” without an xAI key or API call. ElevenLabs is still required for speech and transcription. To restore Grok, uncomment its import and `brain = GrokClient(settings)` in `test_conversation.py`, and configure `XAI_API_KEY` in `.env`. The Grok-specific setup below applies when you re-enable it.

Host-side Python conversation: streaming ElevenLabs speech → microphone/Scribe VAD → Grok → speech. Camera vision is available as an independent demo (see Camera vision below). Arduino firmware and servos are untouched.

## Project layout and changed files

`app/config.py` was the only existing file modified (it was empty). All other files shown with `+` were created. Existing empty directories are retained.

```text
.env.example                         + environment template
.gitignore                           + excludes secrets and local artifacts
requirements.txt                     + four direct dependencies
README.md                            + this guide
test_speech.py                       + manual paid TTS test
test_listener.py                     + manual paid STT test
test_conversation.py                 + manual paid conversation test
tests/test_voice.py                  + offline unit tests
app/
    __init__.py                      +
    config.py                        modified: settings and robot system prompt
    errors.py                        + safe service errors
    speech/
        __init__.py                  +
        speech.py                    + SpeechService
        listener.py                  + ListenerService
    ai/
        __init__.py                  +
        grok_client.py               + GrokClient and session history
    conversation/
        __init__.py                  +
        manager.py                   + state machine and worker thread
    behavior/                        existing
    models/                          existing
    vision/                          existing
    robot/                           existing
firmware/robot_controller/            existing
tools/                               existing
```

## Install

Run commands from the project root. Verified dependency installation and offline tests with Python **3.14.1 on macOS**. Python 3.10+ is required by this code; other Python/platform combinations have not been tested.

macOS/Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Windows PowerShell:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

If PowerShell activation is restricted, use `.\.venv\Scripts\python.exe` in place of `python` without activating.

Audio requires a microphone, speaker, and PortAudio. The pip wheels for macOS and Windows bundle PortAudio. Debian/Ubuntu/Raspberry Pi OS need:

```bash
sudo apt-get update
sudo apt-get install -y python3-venv libportaudio2
```

On macOS, if a source installation cannot locate PortAudio, install it with `brew install portaudio`. No FFmpeg, mpv, PyAudio, or NumPy is needed: both directions use raw PCM. See the [sounddevice installation documentation](https://github.com/spatialaudio/python-sounddevice/blob/master/doc/installation.rst).

Permissions and devices:

- macOS: System Settings → Privacy & Security → Microphone; allow the terminal or IDE running Python. Restart it after changing permission.
- Windows: Settings → Privacy & security → Microphone; enable microphone access and access for desktop apps. Select the intended input/output in Sound settings.
- Linux/Pi: select working input/output in your desktop sound settings (PipeWire/PulseAudio/ALSA). Run as your normal logged-in user, not root. For a headless service, configure access to the audio devices/session separately. A Pi needs a microphone such as a USB audio device.

List device names and indices:

```bash
python -m sounddevice
```

Use those indices or a unique name substring in `AUDIO_INPUT_DEVICE` and `AUDIO_OUTPUT_DEVICE`. Blank values use system defaults. Input must support mono 16 kHz and output mono 24 kHz; choose another device if PortAudio reports an unsupported format.

## API accounts and environment

1. Sign in to [ElevenLabs](https://elevenlabs.io/app). Open Developers → API Keys and create a key with Text to Speech and Speech to Text permissions and sufficient credits. See the [official quickstart](https://elevenlabs.io/docs/eleven-api/quickstart).
2. Open Voices / My Voices, choose or add a voice, then copy its Voice ID from its details/menu. Use the ID, not the display name. Your account must have access to that voice.
3. Sign in to the [xAI console](https://console.x.ai/), create an API key, and configure billing/credits and model access. `grok-4.7` is the configurable default; see its [official model page](https://docs.x.ai/developers/models/grok-4.7).
4. Edit the root `.env` locally. Never commit it. Existing shell environment variables take precedence.

```dotenv
ELEVENLABS_API_KEY=your_elevenlabs_key
ELEVENLABS_VOICE_ID=your_voice_id
XAI_API_KEY=your_xai_key
XAI_MODEL=grok-4.7
ELEVENLABS_TTS_MODEL=eleven_flash_v2_5
LISTEN_TIMEOUT_SECONDS=10
VAD_SILENCE_SECONDS=1.3
MAX_UTTERANCE_SECONDS=30
API_TIMEOUT_SECONDS=30
AUDIO_INPUT_DEVICE=
AUDIO_OUTPUT_DEVICE=
```

Only the two ElevenLabs values are required for TTS; STT needs only its API key. The full conversation also requires the xAI key. VAD silence must be 0.3–3 seconds. The listener gives up after `LISTEN_TIMEOUT_SECONDS` without a nonempty partial transcript, or after `MAX_UTTERANCE_SECONDS` following the first partial. At the utterance limit, uncommitted text is discarded; speak a shorter sentence. Connection setup has a separate API timeout.

## Run the three manual tests

With the virtual environment active:

```bash
python test_speech.py
python test_listener.py
python test_conversation.py
```

TTS says “Hi Ottis! Nice to meet you.” STT prints your committed transcript after silence. The conversation greets you, automatically listens, asks Grok, speaks, and repeats. Say exactly “goodbye”, “bye”, or “stop talking” (case/punctuation ignored), or press Ctrl+C. A phrase like “don't say goodbye” does not end the session.

After a silent timeout, the microphone closes, pauses briefly, and opens a new listening session. Service failures log a safe error and retry after two seconds. Fix credentials, credits, or device permissions if errors persist, or stop with Ctrl+C. Transcripts are printed for development; keys and raw SDK error bodies are not printed.

Run automated tests without keys, audio devices, or API calls:

```bash
python -m unittest discover -s tests -v
python -m pip check
```

## Independent APIs and vision integration

```python
from app.speech.speech import SpeechService
from app.speech.listener import ListenerService
from app.ai.grok_client import GrokClient
from app.conversation import ConversationManager

speech = SpeechService()
listener = ListenerService()
brain = GrokClient()

speech.speak("Hello!")             # Returns after playback drains
text = listener.listen()            # Returns final transcript or empty on timeout
response = brain.respond(text)

conversation = ConversationManager(speech, listener, brain)
worker = conversation.start(greeting="Hi Ottis! How are you?", background=True)
# Run your existing camera/vision loop on the main thread here.
# When that loop ends:
conversation.stop()
worker.join()                       # Wait for current operation and cleanup
```

The independent calls above demonstrate separate usage; omit them when only running the manager. The manager owns the audio services for the session: do not call `speak()` or `listen()` concurrently from vision code. Use the background mode so network/audio waits do not block your camera loop. The foreground `start()` is intentionally blocking for CLI use. Async applications can await `listener.listen_async()` and run blocking speech/brain operations with `asyncio.to_thread`.

The state machine is `IDLE → SPEAKING → LISTENING → THINKING → SPEAKING`, with timeouts/errors returning to IDLE before retrying. The input stream is closed before `listen()` returns. Playback drains before the manager starts another microphone session. No microphone recordings are saved locally.

`SpeechService(on_speech_start=callback, on_speech_end=callback)` exposes lifecycle hooks and `speech.is_speaking`. Start runs before the first PCM write; end runs after cleanup, including failure cleanup. Hooks run on the conversation thread and should return quickly. They are lifecycle signals, not phoneme timing. No servo behavior is implemented.

The system prompt is `SYSTEM_PROMPT` in `app/config.py`. Grok remembers successful user/assistant turns and the greeting in memory. A new `GrokClient` starts a fresh session. Sensor context is already supported:

```python
response = brain.respond(
    "Where is my bottle?",
    sensor_context={"objects": [{"name": "bottle", "position": "right"}]},
)
```

Sensor snapshots apply only to that request, avoiding stale readings in future requests. The manager currently calls `respond(text)`; a future sensor provider can be added there. A future structured response can be introduced at this adapter boundary, passing its speech field to `_speak()` and actions to a separate hardware module.

## Verification and limitations

- Dependencies import successfully and offline tests pass on Python 3.14.1/macOS. Live microphone/speaker behavior and authenticated calls have **not** been tested; complete the three manual scripts on your robot host.
- Half-duplex means you cannot interrupt the robot by speaking. Close microphone placement, speaker reverberation, and background voices can still produce false detections after playback ends.
- Each listening turn opens a fresh STT socket, so setup adds latency. The first committed nonempty VAD segment ends the turn; pauses within a sentence can split a thought. See [Scribe VAD documentation](https://elevenlabs.io/docs/eleven-api/guides/how-to/speech-to-text/realtime/transcripts-and-commit-strategies).
- TTS uses the official SDK's [streaming endpoint](https://elevenlabs.io/docs/eleven-api/guides/how-to/text-to-speech/streaming) with Flash v2.5 and raw PCM. Grok's full response is generated before TTS begins.
- `stop()` is cooperative. Microphone polling stops promptly, but connection setup, a blocked send, Grok, or TTS may need to finish or hit a network timeout. TTS streaming uses per-network-operation timeouts, not a total playback deadline. The background thread is daemonized; stop and join it before normal application shutdown.
- Failed API calls do not commit Grok history. A successful response remains in history if subsequent playback fails, so memory may include speech that was not fully heard.
- History is unbounded for this prototype. Restart the client for long sessions to avoid context limits and growing token costs. There is no database or persistence.
- Audio goes to ElevenLabs and text to xAI; no local audio files are created. Provider retention settings are separate from local storage. Repeated listening and API requests consume credits.
- Missing keys fail early. Runtime API/audio errors recover with backoff, but invalid credentials or missing devices require manual correction. Linux/Pi and Windows are documented but not hardware-tested.

## Camera vision

The independent `app/vision/` package provides `camera.py`, `object_tracker.py`,
`gaze_tracker.py`, `models.py`, `pipeline.py`, and `visualizer.py`.
`test_vision.py` is the manual webcam demo; `tests/test_vision.py` has offline tests.

```bash
python -m pip install -r requirements.txt
python test_vision.py
```

Allow camera access for your terminal/IDE. Press **q** or close the window to exit.
The first run downloads YOLO26 nano and Google's Face Landmarker bundle into
`app/models/vision/` (ignored by Git); later runs use the cached files. No images
are uploaded. Override paths with `--yolo-model` and `--face-model` for offline use.
Use `--camera 1` for another camera. Defaults are 640×480 capture, YOLO at 416,
one face, five-frame gaze smoothing, and CPU inference. Try `--imgsz 320` for
lower cost, or `--device mps` / `--device 0` for supported Apple/CUDA acceleration.
The overlay reports achieved loop FPS; real-time performance depends on hardware.
OpenCV's requested capture size/FPS/buffer size are best-effort backend settings.
MediaPipe and Ultralytics currently declare different OpenCV distributions;
the requirements keep both at the same release because they share `cv2`.
Do not independently upgrade/uninstall one of those distributions.

```python
from app.vision.camera import Camera
from app.vision.pipeline import VisionPipeline

with VisionPipeline() as vision, Camera() as camera:
    frame, timestamp_ms = camera.read()
    snapshot = vision.process(frame, timestamp_ms)
    bottle = vision.objects.find_best('bottle')  # TrackedObject or None
    tracked = vision.objects.get_by_id(4)       # Latest frame only
    sensor_context = snapshot.to_dict()         # JSON-serializable
    maybe_followed = snapshot.is_user_looking_at(object_id=4)  # bool or None
```

Keep the same pipeline alive across frames to preserve tracker state. For audio
integration, run the existing conversation manager in background mode and this
camera loop on the main thread. This demo does not automatically send vision
snapshots to the conversation manager. Processing is synchronous and bounded to
one frame at a time, without an inference queue or recording history.

The shared `VisionFrame` contains a monotonic capture timestamp in milliseconds,
actual `(width, height)`, `coordinate_frame='camera_image'`, objects, and an optional
face. Objects carry `track_id`, label, confidence, pixel bounding box and center,
and normalized center. IDs can be `None` before tracking assigns one; they are
session-local and may change after occlusion. Missing detections disappear from
lookups immediately. The face contains a normalized center/bounding box, eye and
face landmarks, anatomical left/right iris centers, approximate head yaw/pitch
in degrees, and smoothed gaze categories/scores. Raw landmark locations are
unclipped and can fall outside the image when a face is partly outside the frame.

All positions use the **unmirrored camera image**: x increases rightward and y
downward. Normalized 0/0.5/1 means left/center/right or top/center/bottom.
Head yaw is positive toward image right; pitch is positive down. Gaze LEFT/RIGHT
also means image directions, not the person's anatomical left/right. The overlay
says LOOKING AT CAMERA because the robot's location relative to the camera is
unknown. `looking_at_camera` is a heuristic, not measured eye contact.

No face returns `face=None`. Blinks, very small eyes, implausible iris fits or
unreliable pose return UNKNOWN gaze and `looking_at_camera=None`; smoothing resets
on invalid observations, face loss, a large face jump, or a >500 ms frame gap.
The single-face track has no identity recognition and may switch people. Head
pose uses a generic face and estimated focal length; gaze combines head pose
and eye-relative iris displacement and needs live tuning for lighting, glasses,
individual eyes, off-axis faces and cameras. It is not accurate 3D gaze or depth.
The joint-attention helper only compares gaze categories against coarse object
image sectors. It cannot distinguish objects in the same sector or establish
that someone actually looked at an object, especially at different depths.

Future calibration can consume `snapshot.coordinate_frame`, `image_size`, a
normalized target, and the timestamp, pairing them with the current camera/head
pose. No mounting position, physical robot geometry, servo ranges, robot-space
conversion or Arduino control is implemented. Normalized image points alone
cannot supply a metric 3D target.

API references: [Ultralytics tracking](https://docs.ultralytics.com/modes/track/)
and [MediaPipe Face Landmarker](https://ai.google.dev/edge/mediapipe/solutions/vision/face_landmarker/python).

Vision verification: all 15 offline vision/voice tests pass on Python 3.14.1/macOS.
Both downloaded models successfully processed blank frames and the overlay
rendered without a camera. Live webcam tracking/gaze accuracy and FPS have not
been validated on the robot hardware.
# HackGT-26
