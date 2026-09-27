"""Eye-only webcam diagnostic by default. Use --objects for full object vision."""
import argparse
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--objects', action='store_true', help='Also load YOLO and detect objects')
    parser.add_argument('--frames', type=int, default=0, help='Exit after this many frames (0: unlimited)')
    parser.add_argument('--camera', type=int, default=0)
    parser.add_argument('--preview', action='store_true', help='Test camera without loading AI models')
    parser.add_argument('--width', type=int, default=640)
    parser.add_argument('--height', type=int, default=480)
    parser.add_argument('--imgsz', type=int, default=640, help='YOLO inference size')
    parser.add_argument('--confidence', type=float, default=0.25)
    parser.add_argument('--device', default='auto', help='YOLO device: auto, cpu, mps, or 0 for CUDA')
    parser.add_argument('--yolo-model', help='Local weights or Ultralytics model name')
    parser.add_argument('--face-model', help='Local MediaPipe face_landmarker.task')
    parser.add_argument('--smoothing', type=int, default=5)
    args = parser.parse_args()
    import cv2
    from app.vision.camera import Camera
    if args.preview:
        try:
            with Camera(args.camera, args.width, args.height) as camera:
                print('Camera preview: press q to exit.')
                while True:
                    frame, _ = camera.read()
                    cv2.imshow('Camera preview', frame)
                    if cv2.waitKey(1) & 0xFF == ord('q'):
                        break
                    if cv2.getWindowProperty('Camera preview', cv2.WND_PROP_VISIBLE) < 1:
                        break
        finally:
            cv2.destroyAllWindows()
        return
    from app.vision.gaze_tracker import GazeTracker
    from app.vision.models import VisionFrame
    from app.vision.eye_diagnostic import EyeDiagnostic
    from app.vision.visualizer import draw

    try:
        print('Loading face/eye tracking (YOLO disabled unless --objects)...', flush=True)
        if args.objects:
            from app.vision.pipeline import VisionPipeline
            tracker = VisionPipeline(yolo_model=args.yolo_model, face_model=args.face_model,
                                     image_size=args.imgsz, confidence=args.confidence,
                                     device=args.device, smoothing=args.smoothing)
        else:
            tracker = GazeTracker(args.face_model, args.smoothing)
        diagnostic = EyeDiagnostic()
        with tracker as vision:
            with Camera(args.camera, args.width, args.height) as camera:
                print('Camera coordinates: unmirrored, +x right, +y down. Press q to exit.')
                print('Keep your head still and move only your eyes. Press c while looking at the camera to zero eye angles.', flush=True)
                print('Angles are estimates: +yaw=image right, +pitch=image down. No speech or robot commands.', flush=True)
                count = 0
                last_log = 0
                previous = time.monotonic()
                fps = None
                while True:
                    frame, timestamp = camera.read()
                    if args.objects:
                        observation = vision.process(frame, timestamp)
                    else:
                        observation = VisionFrame(timestamp, (frame.shape[1], frame.shape[0]),
                                                  face=vision.update(frame, timestamp))
                    status, eyes = diagnostic.update(observation.face)
                    now = time.monotonic()
                    instantaneous = 1 / max(now - previous, 1e-6)
                    fps = instantaneous if fps is None else 0.9 * fps + 0.1 * instantaneous
                    previous = now
                    eye_text = ('IRIS: unavailable' if eyes is None else
                                f'IRIS ONLY: yaw={eyes[0]:+.1f}deg pitch={eyes[1]:+.1f}deg')
                    if now - last_log >= .5:
                        face = observation.face
                        head = ('unavailable' if face is None or face.head_yaw is None else
                                f'yaw={face.head_yaw:+.1f}deg pitch={face.head_pitch:+.1f}deg')
                        print(f'[EYES] {status} | {eye_text} | HEAD: {head}', flush=True)
                        last_log = now
                    display = draw(frame, observation, fps)
                    for row, text in enumerate((status, eye_text, 'c: calibrate neutral | q: quit')):
                        cv2.putText(display, text, (10, 22 + row * 22),
                                    cv2.FONT_HERSHEY_SIMPLEX, .45, (0, 255, 255), 1)
                    cv2.imshow('Robot vision', display)
                    key = cv2.waitKey(1) & 0xFF
                    count += 1
                    if key == ord('c'):
                        diagnostic.calibrate()
                    if key == ord('q') or (args.frames > 0 and count >= args.frames):
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
