"""YOLO nano + ByteTrack; construct one tracker per continuous camera stream."""
from pathlib import Path
from .models import TrackedObject

MODEL_DIR = Path(__file__).resolve().parents[1] / 'models' / 'vision'


class ObjectTracker:
    def __init__(self, model=None, confidence=0.25, image_size=416, device='cpu'):
        from ultralytics import YOLO
        if not 0 < confidence <= 1 or image_size < 32:
            raise ValueError('Invalid detection confidence or image size')
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        self.model = YOLO(str(model or MODEL_DIR / 'yolo26n.pt'))
        self.confidence = confidence
        self.image_size = image_size
        self.device = device
        self.objects = ()

    def update(self, frame):
        self.objects = ()  # Never leave stale detections after an error/empty frame.
        result = self.model.track(frame, persist=True, tracker='bytetrack.yaml',
                                  conf=self.confidence, imgsz=self.image_size,
                                  device=self.device, verbose=False)[0]
        height, width = frame.shape[:2]
        boxes = result.boxes
        if boxes is None:
            return self.objects
        coords = boxes.xyxy.cpu().tolist()
        ids = boxes.id.cpu().tolist() if boxes.id is not None else [None] * len(coords)
        objects = []
        for bbox, cls, conf, track_id in zip(coords, boxes.cls.cpu().tolist(),
                                           boxes.conf.cpu().tolist(), ids):
            x1, y1, x2, y2 = bbox
            x1, x2 = [max(0., min(float(width), x)) for x in (x1, x2)]
            y1, y2 = [max(0., min(float(height), y)) for y in (y1, y2)]
            center = ((x1 + x2) / 2, (y1 + y2) / 2)
            objects.append(TrackedObject(
                int(track_id) if track_id is not None else None,
                result.names[int(cls)], float(conf), (x1, y1, x2, y2), center,
                (center[0] / width, center[1] / height)))
        self.objects = tuple(objects)
        return self.objects

    def find_best(self, label):
        return max((o for o in self.objects if o.label.casefold() == label.casefold()),
                   key=lambda o: o.confidence, default=None)

    def get_by_id(self, track_id):
        if track_id is None:
            return None
        return next((o for o in self.objects if o.track_id == track_id), None)
