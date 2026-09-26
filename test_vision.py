"""Manual webcam demo. First run downloads YOLO and Face Landmarker weights."""
import argparse
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--camera', type=int, default=0)
    parser.add_argument('--width', type=int, default=640)
    parser.add_argument('--height', type=int, default=480)
    parser.add_argument('--imgsz', type=int, default=416, help='YOLO inference size')
    parser.add_argument('--confidence', type=float, default=0.25)
    parser.add_argument('--device', default='cpu', help='YOLO device: cpu, mps, or 0 for CUDA')
    parser.add_argument('--yolo-model', help='Local weights or Ultralytics model name')
    parser.add_argument('--face-model', help='Local MediaPipe face_landmarker.task')
    parser.add_argument('--smoothing', type=int, default=5)
    args = parser.parse_args()
    import cv2
    from app.vision.camera import Camera
    from app.vision.pipeline import VisionPipeline
    from app.vision.visualizer import draw

    try:
        print('Loading vision models (first run needs internet)...', flush=True)
        with VisionPipeline(yolo_model=args.yolo_model, face_model=args.face_model,
                            image_size=args.imgsz, confidence=args.confidence,
                            device=args.device, smoothing=args.smoothing) as vision:
            with Camera(args.camera, args.width, args.height) as camera:
                print('Camera coordinates: unmirrored, +x right, +y down. Press q to exit.')
                previous = time.monotonic()
                fps = None
                while True:
                    frame, timestamp = camera.read()
                    observation = vision.process(frame, timestamp)
                    now = time.monotonic()
                    instantaneous = 1 / max(now - previous, 1e-6)
                    fps = instantaneous if fps is None else 0.9 * fps + 0.1 * instantaneous
                    previous = now
                    cv2.imshow('Robot vision', draw(frame, observation, fps))
                    if cv2.waitKey(1) & 0xFF == ord('q'):
                        break
                    if cv2.getWindowProperty('Robot vision', cv2.WND_PROP_VISIBLE) < 1:
                        break
    finally:
        cv2.destroyAllWindows()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
    except (RuntimeError, ValueError, OSError, ImportError) as exc:
        print(f'[VISION ERROR] {exc}')
        raise SystemExit(1)
