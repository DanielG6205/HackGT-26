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
        self.index = index

    def read(self):
        # USB cameras can return empty frames while negotiating a capture mode.
        for attempt in range(30 if self._timestamp < 0 else 5):
            ok, frame = self.capture.read()
            if ok and frame is not None and frame.size:
                break
            time.sleep(0.1)
        else:
            raise RuntimeError(
                f'Camera {self.index} opened but produced no frames. Close other camera apps, '
                'check camera permission and USB connection, or try another --camera index. '
                'Try --width 640 --height 480 to check whether the requested mode is the issue.')
        if self._timestamp < 0:
            height, width = frame.shape[:2]
            print(f'Camera {self.index}: actual capture {width}x{height}', flush=True)
        self._timestamp = max(self._timestamp + 1, time.monotonic_ns() // 1_000_000)
        return frame, self._timestamp

    def close(self):
        self.capture.release()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
