"""Overlay only: never mutate the source frame supplied to the trackers."""
import math
import cv2


def draw(frame, observation, fps=None):
    image = frame.copy()
    height, width = image.shape[:2]

    def pixel(point):
        return tuple(int(v) for v in (point[0] * width, point[1] * height))

    def text(message, origin, color=(255, 255, 255)):
        cv2.putText(image, message, origin, cv2.FONT_HERSHEY_SIMPLEX, 0.48, (0, 0, 0), 3)
        cv2.putText(image, message, origin, cv2.FONT_HERSHEY_SIMPLEX, 0.48, color, 1)

    for obj in observation.objects:
        x1, y1, x2, y2 = map(int, obj.bbox)
        cv2.rectangle(image, (x1, y1), (x2, y2), (80, 220, 80), 2)
        cv2.circle(image, tuple(map(int, obj.center_px)), 4, (80, 220, 80), -1)
        x, y = obj.center_normalized
        identity = obj.track_id if obj.track_id is not None else '?'
        text(f'{obj.label} #{identity} ({x:.2f}, {y:.2f}) {obj.confidence:.0%}',
             (max(0, x1), max(18, y1 - 6)), (80, 220, 80))
    face = observation.face
    lines = ['NO FACE', 'GAZE: UNKNOWN', 'LOOKING AT CAMERA: UNKNOWN']
    if face:
        for point in face.landmarks:
            cv2.circle(image, pixel(point), 1, (130, 150, 160), -1)
        for eye in (face.left_eye, face.right_eye):
            for point in eye:
                cv2.circle(image, pixel(point), 2, (255, 200, 0), -1)
        for iris in (face.left_iris, face.right_iris):
            if iris is not None:
                cv2.circle(image, pixel(iris), 4, (0, 220, 255), -1)
        cv2.circle(image, pixel(face.face_center), 4, (255, 100, 200), -1)
        head = 'HEAD: UNKNOWN'
        if face.head_yaw is not None:
            yaw, pitch = face.head_yaw, face.head_pitch
            horizontal = 'LEFT' if yaw < -5 else 'RIGHT' if yaw > 5 else 'CENTER'
            vertical = 'UP' if pitch < -5 else 'DOWN' if pitch > 5 else 'CENTER'
            head = f'HEAD: {horizontal} {yaw:+.0f} deg / {vertical} {pitch:+.0f} deg'
            start = pixel(face.face_center)
            end = (start[0] + int(70 * math.sin(math.radians(yaw))),
                   start[1] + int(70 * math.sin(math.radians(pitch))))
            cv2.arrowedLine(image, start, end, (255, 100, 200), 2)
        gaze = face.gaze
        looking = {True: 'YES', False: 'NO', None: 'UNKNOWN'}[gaze.looking_at_camera]
        lines = [head, f'GAZE: {gaze.horizontal} / {gaze.vertical}',
                 f'LOOKING AT CAMERA: {looking}']
    if fps is not None:
        lines.append(f'{fps:.1f} FPS | camera image, unmirrored | q: quit')
    for i, line in enumerate(lines):
        text(line, (10, height - 12 - (len(lines) - 1 - i) * 22))
    return image
