"""Small, bounded servo pulses driven by quiz and gaze success events."""
import queue
import re
import time

from .transport.serial_transport import wait_for_reply


class CameraServoTest:
    QUESTION = 'How many legs does a dog have?'
    ANSWERS = {'four', '4', 'four legs', '4 legs', 'a dog has four legs',
               'a dog has 4 legs', 'it has four legs', 'it has 4 legs'}

    def __init__(self):
        self.events = queue.Queue()
        self.port = None
        self.pending = {}
        self.armed = []

    def add_arguments(self, parser):
        parser.add_argument('--port', help='Uno USB port; omit for mock servo output')
        parser.add_argument('--servo1-rest-us', type=int)
        parser.add_argument('--servo3-rest-us', type=int)
        parser.add_argument('--step-us', type=int, default=10,
                            help='Signed movement from rest, -25 to 25 microseconds')

    def configure(self, args, parser):
        if not 1 <= abs(args.step_us) <= 25:
            parser.error('--step-us must be between -25 and 25, excluding zero')
        self.args = args
        self.rest = {}
        for servo, reference in ((1, 1200), (3, 1650)):
            value = getattr(args, f'servo{servo}_rest_us')
            if value is None:
                if args.port:
                    parser.error(f'Hardware requires --servo{servo}-rest-us after checking the rest position; see firmware/camera_servo_test/README.md')
                value = reference
            if not (reference - 50 <= value <= reference + 50 and
                    reference - 50 <= value + args.step_us <= reference + 50):
                parser.error(f'Servo {servo}: rest and moved pulse must stay within {reference - 50}..{reference + 50} us')
            self.rest[servo] = value

    def bind(self, dialogue, audio):
        original_handle, original_emit = dialogue.handle, audio.emit

        def question():
            dialogue.game_question = True
            return self.QUESTION

        def handle(text, context=None):
            normalized = ' '.join(re.findall(r'\w+', text.casefold()))
            wake = re.search(r'\b(?:ottis|otis|ottish)\b', normalized)
            if dialogue.game_question and not dialogue.active and not wake:
                if normalized in self.ANSWERS:
                    dialogue.game_question = False
                    self.events.put(1)
                    return 'Yes, four legs! Let’s spot something together.'
                return 'Try again! How many legs does a dog have?'
            return original_handle(text, context)

        def emit(message):
            if message.startswith('[SUCCESS] User followed gaze toward '):
                self.events.put(3)
            original_emit(message)

        dialogue.handle = handle
        audio.make_question = question
        audio.emit = emit

    def send(self, command):
        if self.port is None:
            print('MOCK SERVO:', command, flush=True)
            return
        self.port.write((command + '\n').encode('ascii'))
        self.port.flush()
        wait_for_reply(self.port, 'OK,' + command)

    def open(self):
        if self.args.port:
            import serial
            self.port = serial.Serial(self.args.port, 115200, timeout=.1, write_timeout=1)
            wait_for_reply(self.port, 'CAMERA_SERVO_READY', timeout=5)
        else:
            print('Mock servo mode: camera and speech are real; no hardware connection.')
        for servo, rest in self.rest.items():
            self.armed.append(servo)
            self.send(f'ARM,{servo},{rest}')

    def tick(self, now=None):
        now = time.monotonic() if now is None else now
        for servo, deadline in list(self.pending.items()):
            if now >= deadline:
                self.send(f'PULSE,{servo},{self.rest[servo]}')
                del self.pending[servo]
        while True:
            try:
                servo = self.events.get_nowait()
            except queue.Empty:
                break
            if servo not in self.pending:
                self.send(f'PULSE,{servo},{self.rest[servo] + self.args.step_us}')
                self.pending[servo] = now + 1.0

    def close(self):
        try:
            for servo in self.armed:
                try:
                    self.send(f'OFF,{servo}')
                except (OSError, RuntimeError) as exc:
                    print(f'Could not detach servo {servo}: {exc}')
        finally:
            if self.port is not None:
                self.port.close()
                self.port = None
