# Pico W Bluetooth robot controller

The computer runs camera tracking, conversation, microphone capture, and speaker
playback. Only motion/control commands go to the Pico W over Bluetooth Low Energy
(BLE). This is a GATT connection, not a Bluetooth serial port or audio device.

1. Install the stable **Raspberry Pi Pico W** MicroPython UF2 from
   https://micropython.org/download/RPI_PICO_W/ using BOOTSEL USB mode.
2. Open the board in Thonny, select the MicroPython Raspberry Pi Pico interpreter,
   and save this directory's `main.py` onto the **board** as `main.py`. Reset it.
   USB can remain connected for power/programming; movements arrive through BLE.
3. Wire servo signals using GPIO numbers below. Power servos from a suitable
   external servo supply and join its ground to Pico GND. Do not power servos
   from Pico's 3V3 pin.
4. On the computer: `python -m pip install -r requirements.txt`.
5. Set `.env`:

   ```dotenv
   ROBOT_TRANSPORT=bluetooth
   ROBOT_BLUETOOTH_NAME=PicoRobot
   ROBOT_BLUETOOTH_ADDRESS=
   ROBOT_BLUETOOTH_TIMEOUT=10
   ```

6. Enable computer Bluetooth and allow Bluetooth access for your terminal/Python
   app on macOS. Run `python test_pico.py`, then
   `python -m app.robot.calibrate --transport bluetooth` for manual commands.
   Run `python test_full.py --transport bluetooth` for vision and conversation.
   `python test_pico.py --mock` runs without a board.

| Axis | Pico GPIO | Physical pin | Default |
| --- | --- | --- | --- |
| Eye horizontal | GP18 | 24 | Enabled |
| Eye vertical | GP19 | 25 | Enabled |
| Head horizontal | GP21 | 27 | Disabled |
| Head vertical | GP22 | 29 | Disabled |

Calibrate `AXES` in `main.py` and matching fields in `app/robot/config.py`:
center 90°, limits 60–120°, no inversion initially. Firmware enforces its own
limits; host configuration does not automatically update the board. PWM is 50 Hz
with 1000–2000 microseconds mapped to 0–180°. Adjust to your servo specification.
Enable head axes in both configurations; set `couple_head_to_look=True` on the
host if head movements should follow gaze. This controls the existing eye/head
servos; drive motors need a motor driver and an additional control mapping.

For a board-only check, set `LED_TEST_MODE=True` in firmware before uploading.
No PWM is created and the onboard LED pulses when a command arrives. The smoke
test checks a real `PONG` notification and then sends modest eye movements.
`EXPR` stores a label for future eyelid/display behavior; it has no physical
expression mapping yet, matching the previous firmware's placeholder.

The BLE UART UUIDs are service `6e400001-b5a3-f393-e0a9-e50e24dcca9e`,
RX `6e400002-b5a3-f393-e0a9-e50e24dcca9e`, and
TX `6e400003-b5a3-f393-e0a9-e50e24dcca9e`. Newline-delimited ASCII commands:
`LOOK,x,y[,head_x,head_y]`, `CENTER`, `MOVE,LEFT|RIGHT|UP|DOWN|CENTER`,
`SET,axis,degrees`, `EXPR,label`, `PING`. Replies are `ACK,kind`, `ERR,reason`,
or `PONG`. The host splits writes into at most 20 bytes; firmware reassembles
commands and smooths servo movement every 5 ms. GATT write acknowledgement is
not confirmation of physical movement. On disconnect the firmware centers all
axes and advertises again. The host reports link failure rather than silently
replaying old movement; rerun/reconnect after restoring the link.

If discovery fails, check that the board is running `main.py` and no other app
is connected. For multiple boards, use unique firmware names or specify
`ROBOT_BLUETOOTH_ADDRESS` (a device UUID on macOS, Bluetooth address elsewhere).
Explicit Bluetooth mode ignores old Wi-Fi/serial settings. `auto` prefers an
explicit BLE address, then legacy Wi-Fi/serial endpoints, then PicoRobot BLE.
Use explicit `mock` when running without hardware.

API references: [MicroPython Bluetooth](https://docs.micropython.org/en/latest/library/bluetooth.html),
[Bleak scanner](https://bleak.readthedocs.io/en/stable/api/scanner.html).
