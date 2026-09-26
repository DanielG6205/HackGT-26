"""Webcam joint-attention demo; robot speech/actions are printed only."""
import argparse

from app.vision.interaction import GazeInteraction


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--camera', type=int, default=0)
    parser.add_argument('--face-model', help='Optional local Face Landmarker model')
    parser.add_argument('--smoothing', type=int, default=5, help='Head/iris moving-average frames')
    parser.add_argument('--horizontal-threshold', type=float, default=0.65, help='Horizontal gaze score dead zone')
    parser.add_argument('--vertical-threshold', type=float, default=0.65, help='Vertical gaze score dead zone')
    parser.add_argument('--hold-frames', type=int, default=5)
    parser.add_argument('--timeout', type=float, default=5.0, help='Target timeout in seconds')
    parser.add_argument('--delay', type=float, default=1.0, help='Pause between trials in seconds')
    args = parser.parse_args()
    # Validate before loading models or opening the camera; defer messages until ready.
    initial_messages = []
    interaction = GazeInteraction(
        horizontal_threshold=args.horizontal_threshold,
        vertical_threshold=args.vertical_threshold, hold_frames=args.hold_frames,
        timeout=args.timeout, delay=args.delay, emit=initial_messages.append)
    if args.smoothing < 1:
        parser.error('--smoothing must be positive')

    import cv2
    from app.vision.camera import Camera
    from app.vision.gaze_tracker import GazeTracker

    try:
        with GazeTracker(args.face_model, args.smoothing) as tracker, Camera(args.camera) as camera:
            print('Unmirrored CAMERA directions: N=up, E=right. Press q to exit.', flush=True)
            interaction.emit = lambda message: print(message, flush=True)
            for message in initial_messages:
                interaction.emit(message)
            while True:
                frame, timestamp_ms = camera.read()
                face = tracker.update(frame, timestamp_ms)
                interaction.update(face.gaze if face else None, timestamp_ms / 1000)
                if face:
                    height, width = frame.shape[:2]
                    for iris in (face.left_iris, face.right_iris):
                        if iris is not None:
                            cv2.circle(frame, (int(iris[0] * width), int(iris[1] * height)),
                                       4, (0, 220, 255), -1)
                lines = [interaction.state.name,
                         f'TARGET: {interaction.target_direction or "CAMERA / CENTER"}',
                         f'GAZE: {interaction.direction}', 'N=up E=right | q: quit']
                for i, line in enumerate(lines):
                    for color, thickness in (((0, 0, 0), 3), ((255, 255, 255), 1)):
                        cv2.putText(frame, line, (10, 25 + 25 * i),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, thickness)
                cv2.imshow('Gaze interaction', frame)
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break
                if cv2.getWindowProperty('Gaze interaction', cv2.WND_PROP_VISIBLE) < 1:
                    break
    except cv2.error as exc:
        raise RuntimeError(f'Camera/display error: {exc}') from exc
    finally:
        cv2.destroyAllWindows()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
    except (RuntimeError, ValueError, OSError, ImportError) as exc:
        print(f'[ERROR] {exc}')
        raise SystemExit(1)
