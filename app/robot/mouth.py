"""Optional mouth animation tied to SpeechService playback, not TTS requests.

Set ROBOT_MOUTH_CONFIG=config/robot-servos.json and ROBOT_MOUTH_PORT (or
ROBOT_SERIAL_PORT). Reuses an already-open USB transport; never owns gaze motion.
"""
import atexit
import json
import logging
import math
import os
import threading
from pathlib import Path

from .transport.serial_transport import SerialTransport, wait_for_reply

log = logging.getLogger(__name__)


class MouthAnimator:
    def __init__(self, config, port):
        self.config = config
        self.port = port
        self.link = None
        self.owned = False
        self.thread = None
        self.stop_event = threading.Event()
        self._command_lock = threading.Lock()
        self._cleanup_registered = False

    @classmethod
    def from_env(cls):
        path = os.getenv('ROBOT_MOUTH_CONFIG')
        if not path:
            return None  # Existing installations have exactly the old behavior.
        try:
            data = json.loads(Path(path).read_text())
            # Shared servo JSON is preferred; old mouth-only files still work.
            config = data.get('mouth', data)
            if 'mouth' in data and any(
                    axis.get('pin') == config['pin']
                    for name, axis in data.items() if name != 'mouth'):
                raise ValueError('Mouth pin conflicts with another servo')
            pin = config['pin']
            values = [config[k] for k in ('min_deg', 'closed_deg', 'open_deg', 'max_deg')]
            if (not isinstance(pin, int) or isinstance(pin, bool) or not 2 <= pin <= 13 or pin in (6, 7)
                    or not all(math.isfinite(v) and int(v) == v for v in values)):
                raise ValueError('Use pin 2..13 and finite integer degree values')
            lo, closed, opened, hi = values
            if not (0 <= lo <= closed <= hi <= 180 and lo <= opened <= hi):
                raise ValueError('Mouth open/closed angles must lie within min/max')
            port = os.getenv('ROBOT_MOUTH_PORT') or os.getenv('ROBOT_SERIAL_PORT')
            if not port:
                raise ValueError('Set ROBOT_MOUTH_PORT or ROBOT_SERIAL_PORT')
            return cls(config, port)
        except Exception as exc:
            log.warning('Mouth animation disabled: %s', exc)
            return None

    def prepare(self):
        """Configure and close the mouth without starting speech motion."""
        try:
            self.stop()
            if self.link is None or not self.link.is_open():
                self.link = SerialTransport.active(self.port)
                self.owned = self.link is None
                if self.owned:
                    self.link = SerialTransport(self.port)
                    self.link.open()
                    if not self._cleanup_registered:
                        atexit.register(self.close)
                        self._cleanup_registered = True
                    wait_for_reply(self.link._serial, 'GAZE_READY,2', timeout=6)
            cfg = self.config
            self.link.send_line('MOUTH_CONFIG,' + ','.join(str(int(cfg[k])) for k in
                                ('pin', 'min_deg', 'closed_deg', 'open_deg', 'max_deg')))
            # Legacy LOOK/CENTER may leave unsupported-command replies on this
            # shared port; only ignore that exact unrelated error. Mouth config
            # errors still fail, and an old sketch times out without MOUTH_READY.
            wait_for_reply(self.link._serial, 'MOUTH_READY', timeout=1,
                           ignored_replies=('ERROR command',))
            self.link.send_line('TALK,0')
            return True
        except Exception as exc:
            log.warning('Mouth animation unavailable; continuing speech: %s', exc)
            self.close()
            return False

    def start(self):
        """Called immediately before the first PCM write. Failures never stop audio."""
        if not self.prepare():
            return
        try:
            self.stop_event.clear()
            self.link.send_line('TALK,1')
            self.thread = threading.Thread(target=self._heartbeat, name='robot-mouth', daemon=True)
            self.thread.start()
        except Exception as exc:
            log.warning('Mouth animation unavailable; continuing speech: %s', exc)
            self.close()

    def _heartbeat(self):
        # Firmware closes automatically if host exits or this heartbeat stops.
        while not self.stop_event.wait(.2):
            try:
                with self._command_lock:
                    if self.stop_event.is_set():
                        return
                    self.link.send_line('TALK,1')
            except Exception:
                log.warning('Mouth connection lost; firmware watchdog will close it')
                return

    def stop(self):
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=1)
            self.thread = None
        if self.link is not None:
            try:
                with self._command_lock:
                    self.link.send_line('TALK,0')  # Stops animation on older sketches too.
                    self.link.send_line('MOUTH_CLOSE')
                    expected = f"MOUTH_CLOSED,{int(self.config['closed_deg'])}"
                    wait_for_reply(self.link._serial, expected, timeout=1,
                                   ignored_replies=('ERROR command',))
                log.info('Mouth close confirmed: pin %s, %s degrees (commanded, not measured)',
                         self.config['pin'], self.config['closed_deg'])
            except Exception:
                log.warning('Mouth close not acknowledged. Re-upload the robot sketch and verify closed_deg; watchdog will expire.')

    def close(self):
        self.stop()
        try:
            if self.owned and self.link is not None:
                self.link.close()
        except Exception:
            log.warning('Could not close mouth serial connection')
        finally:
            self.link = None
            self.owned = False
