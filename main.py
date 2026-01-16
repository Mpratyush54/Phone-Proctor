import cv2

from camera.webcam import Webcam
from face.face_detect import FaceDetector
from face.face_mesh import FaceMeshDetector
from gaze.head_pose import HeadPoseEstimator
from rules.rule_engine import RuleEngine
from utils.fps import FPSCounter
from utils.logger import EventLogger


def main():
    # -------------------------------
    # Initialization
    # -------------------------------
    webcam = Webcam(camera_id=1, width=640, height=480)
    face_detector = FaceDetector(confidence=0.6)
    face_mesh = FaceMeshDetector()
    head_pose = HeadPoseEstimator()
    rule_engine = RuleEngine()
    fps_counter = FPSCounter()
    logger = EventLogger(log_file="logs/events.log")

    yaw_baseline = None

    print("[INFO] AI Proctoring System Started")

    # -------------------------------
    # Main Loop
    # -------------------------------
    while webcam.is_opened():
        frame = webcam.read()
        if frame is None:
            break

        # -------------------------------
        # Face detection
        # -------------------------------
        faces = face_detector.detect(frame)
        face_count = len(faces)

        for (x, y, w, h) in faces:
            cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)

        # Face-based rules
        violations = rule_engine.evaluate_faces(face_count)
        for v in violations:
            logger.log(v)

        # -------------------------------
        # Looking Away Logic (DAY 3)
        # -------------------------------
        is_looking_away = False

        landmarks = face_mesh.get_landmarks(frame)
        if landmarks:
            yaw, pitch = head_pose.estimate(landmarks, frame.shape)

            if yaw is not None:
                if yaw_baseline is None:
                    yaw_baseline = yaw

                relative_yaw = yaw - yaw_baseline

                cv2.putText(
                    frame,
                    f"RelYaw: {int(relative_yaw)}",
                    (10, 120),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (255, 255, 0),
                    2
                )

                if abs(relative_yaw) > 30:
                    is_looking_away = True

        # Time-based looking away rule
        look_away_violations = rule_engine.evaluate_look_away(is_looking_away)

        for v in look_away_violations:
            logger.log(v)

        violations.extend(look_away_violations)

        if "Looking Away" in look_away_violations:
            cv2.putText(
                frame,
                "Looking Away",
                (10, 150),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (0, 0, 255),
                2
            )

        # -------------------------------
        # FPS & overlays
        # -------------------------------
        fps = fps_counter.update()

        cv2.putText(frame, f"Faces: {face_count}", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

        cv2.putText(frame, f"FPS: {fps}", (10, 60),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

        if violations:
            cv2.putText(frame, f"Warning: {violations[-1]}", (10, 90),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

        # -------------------------------
        # Display
        # -------------------------------
        cv2.imshow("AI Proctoring - Laptop", frame)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    # -------------------------------
    # Cleanup
    # -------------------------------
    webcam.release()
    cv2.destroyAllWindows()
    print("[INFO] Proctoring Session Ended")


if __name__ == "__main__":
    main()
