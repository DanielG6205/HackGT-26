# Choosing a game

Playful conversation (riddles, imagination questions, word games):

```sh
.venv/bin/python -m app.main --mode conversation --transport serial --port /dev/cu.usbmodem11201
```

Say hello or ask for a game to start the conversation. Add `--no-vision` if you
want audio-only conversation. Robot startup still loads the saved servo/world
calibration, as it does in the existing main application.

Object question and gaze game:

```sh
.venv/bin/python -m app.main --mode objects --transport serial --port /dev/cu.usbmodem11201
```

Complete the human iris/head setup calibration at startup. The game itself stays
silent until you say “Hi Ottis.” Ottis asks your name, saves it, and asks you to
look at it. Once iris/head detection confirms eye contact, it chooses a supported
visible object, looks toward it, and asks one short question. After your answer,
it responds briefly and asks you to look at that same object. Robot aiming uses
only the selected object’s normalized camera center, never the human face. If the
object disappears or the round ends, the robot holds its pose. Sustained iris/head
direction confirms success; scoring pauses during speech. Ottis says “Good job,”
asks you to look back, and repeats. It can reuse objects once all visible choices
have been tried. Unrelated utterances do not switch object mode into general chat.
Say “stop” or “goodbye” to end; “Hi Ottis” starts the sequence again.
The camera and saved robot world calibration are required. Missing faces or
targets cannot produce gaze success.

Existing modes remain: `--mode chat` for free conversation (default) and
`--mode game` for the quick find-object game without the question/answer step.
The voice shortcuts to switch between chat and looking rounds remain available
in the other modes; object mode stays in its prescribed sequence.

No firmware changes are needed to switch games.


Object mode displays live detections continuously, including before wake-up.
Only a supported class detected at 55% confidence or higher for three consecutive
selection frames can become a target. The selected object has a yellow box and
crosshair, with its tracking ID, confidence, and pixel center displayed. Empty
frames cannot select an object. If the selected tracking ID disappears, aiming
holds rather than switching to a different object. YOLO labels remain estimates:
a persistent wrong label can still occur, so check the box against the real scene.


If the child has not looked near the object after eight seconds of available
face/target observations, the configured AI provider (Grok by default) supplies a
short encouraging hint. Further hints wait 12 seconds after speech, up to three
per round. Missing face/target observations pause the hint timer. AI only chooses
encouragement; visual iris/head matching still decides success. API failure uses
a gentle built-in hint and does not end the game.
