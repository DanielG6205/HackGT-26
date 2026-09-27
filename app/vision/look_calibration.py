"""Five-point, per-person calibration to normalized camera-image coordinates."""
from statistics import median

from .angles import AngularGaze

CENTER_TOLERANCE = .23
TARGETS = [('center', (.5, .5)), ('up', (.5, .05)), ('down', (.5, .95)),
           ('left', (.05, .5)), ('right', (.95, .5))]


def readings(face):
    angles = AngularGaze()
    return {'head': angles.head(face),
            'gaze': angles.gaze(face.gaze) if face and face.gaze.eyes_tracked else None}


class LookCalibration:
    def __init__(self, samples):
        self.channels = {}
        for channel in ('head', 'gaze'):
            points = {}
            for label, _ in TARGETS:
                values = [s[channel] for s in samples.get(label, []) if s.get(channel) is not None]
                if len(values) < 10:
                    break
                points[label] = tuple(median(v[i] for v in values) for i in (0, 1))
            if len(points) != 5:
                continue
            cx, cy = points['center']
            # Require distinct opposite-side samples; a stationary face is not calibration.
            lx, rx = points['left'][0] - cx, points['right'][0] - cx
            uy, dy = points['up'][1] - cy, points['down'][1] - cy
            if min(abs(v) for v in (lx, rx, uy, dy)) < 3 or lx * rx >= 0 or uy * dy >= 0:
                continue
            self.channels[channel] = points
        if not self.channels:
            raise ValueError('No usable movement range. Repeat with clear, comfortable turns toward each marker.')

    @staticmethod
    def axis(value, center, low, high):
        delta = value - center
        endpoint = low if delta * (low - center) > 0 else high
        fraction = delta / (endpoint - center)
        return max(0., min(1., .5 + (-.45 if endpoint == low else .45) * fraction))

    def points(self, face):
        result = {}
        for channel, value in readings(face).items():
            if value is None or channel not in self.channels:
                continue
            p = self.channels[channel]
            result[channel] = (self.axis(value[0], p['center'][0], p['left'][0], p['right'][0]),
                               self.axis(value[1], p['center'][1], p['up'][1], p['down'][1]))
        return result

    def centered(self, face):
        return any(abs(x - .5) <= CENTER_TOLERANCE and abs(y - .5) <= CENTER_TOLERANCE
                   for x, y in self.points(face).values())

    def matching_cues(self, face, obj, image_size, margin=.20):
        if obj is None:
            return ()
        width, height = image_size
        x1, y1, x2, y2 = obj.bbox
        return tuple(channel for channel, (x, y) in self.points(face).items()
                     if not (abs(x - .5) <= CENTER_TOLERANCE and abs(y - .5) <= CENTER_TOLERANCE)
                     and x1 - margin * width <= x * width <= x2 + margin * width
                     and y1 - margin * height <= y * height <= y2 + margin * height)


def from_mirrored_samples(samples):
    """Convert displayed marker positions back to raw camera coordinates."""
    return LookCalibration(dict(samples, left=samples['right'], right=samples['left']))


def run_calibration(vision, camera):
    """Keyboard-guided capture before microphone/game startup; q cancels."""
    import cv2
    samples = {}
    index = 0
    collecting = False
    message = 'Turn your face OR eyes toward the marker; SPACE captures.'
    window = 'Ottis looking calibration'
    last_time = None
    print('[CALIBRATION] Mirrored preview: move naturally toward the yellow marker. '
          'Keep your seat/camera fixed. SPACE captures 20 frames; q quits.', flush=True)
    try:
        while True:
            label, target = TARGETS[index]
            frame, timestamp = camera.read()
            snapshot = vision.process(frame, timestamp, detect_objects=False)
            values = readings(snapshot.face)
            if collecting:
                if last_time is not None and timestamp - last_time > 500:
                    samples[label] = []
                if all(value is None for value in values.values()):
                    samples[label] = []
                    message = 'Tracking lost; face the camera enough to keep landmarks visible.'
                else:
                    samples[label].append(values)
                if len(samples[label]) >= 20:
                    print(f'[CALIBRATION] Captured {label}', flush=True)
                    collecting = False
                    index += 1
                    if index == len(TARGETS):
                        try:
                            # Preview is mirrored; scoring stays in raw camera coordinates.
                            result = from_mirrored_samples(samples)
                            print('[CALIBRATION] Ready; calibrated cues: ' + ', '.join(result.channels), flush=True)
                            return result
                        except ValueError as exc:
                            message = str(exc)
                            print('[CALIBRATION] ' + message, flush=True)
                            samples, index = {}, 0
                    else:
                        message = 'Look toward the marker, then press SPACE.'
                    label, target = TARGETS[index]
            last_time = timestamp
            display = cv2.flip(frame, 1)
            height, width = display.shape[:2]
            cv2.circle(display, (int(target[0] * width), int(target[1] * height)), 16, (0, 255, 255), 3)
            for row, text in enumerate((f'LOOK {label.upper()} | {len(samples.get(label, []))}/20',
                                        message,
                                        'HEAD: ' + ('OK' if values['head'] is not None else 'unavailable') +
                                        ' | EYES: ' + ('OK' if values['gaze'] is not None else 'unavailable') +
                                        ' | Mirrored preview',
                                        'SPACE: capture | r: restart | q: quit')):
                cv2.putText(display, text, (10, 30 + row * 25), cv2.FONT_HERSHEY_SIMPLEX,
                            .5, (0, 255, 255), 1)
            cv2.imshow(window, display)
            key = cv2.waitKey(1) & 0xff
            if key == ord('q') or cv2.getWindowProperty(window, cv2.WND_PROP_VISIBLE) < 1:
                return None
            if key == ord('r'):
                samples, index, collecting = {}, 0, False
            if key == ord(' '):
                samples[label] = []
                collecting = True
                message = 'Hold this direction comfortably while samples are captured.'
    finally:
        cv2.destroyAllWindows()
