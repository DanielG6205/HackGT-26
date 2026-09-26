"""One unmirrored webcam stream, with no assumptions about mounting."""
import time
import cv2


class Camera:
    def __init__(self, index=0, width=640, height=480, fps=30):
        if width <= 0 or height <= 0 or fps <= 0:
            raise ValueError('Camera dimensions and FPS must be positive')
        self.capture = cv2.VideoCapture(index)
        if not self.capture.isOpened():
            self.capture.release()
            raise RuntimeError(f'Cannot open camera {index}; check camera permissions/device index')
        self.capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self.capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        self.capture.set(cv2.CAP_PROP_FPS, fps)
        # Best effort: some camera backends ignore this property.
        self.capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self._timestamp = -1

    def read(self):
        ok, frame = self.capture.read()
        if not ok or frame is None:
            raise RuntimeError('Webcam frame unavailable; camera may have disconnected')
        self._timestamp = max(self._timestamp + 1, time.monotonic_ns() // 1_000_000)
        return frame, self._timestamp

    def close(self):
        self.capture.release()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
