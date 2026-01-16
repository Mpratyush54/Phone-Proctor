import cv2
import time

from camera.webcam import Webcam
from face.face_detect import FaceDetector
from rules.rule_engine import RuleEngine
from utils.fps import FPSCounter
from utils.logger import EventLogger


def main():
    # -------------------------------
    # Initialization
    # -------------------------------
    webcam = Webcam(camera_id=0, width=640, height=480)
    face_detector = FaceDetector(confidence=0.6)
    rule_engine = RuleEngine()
    fps_counter = FPSCounter()
    logger = EventLogger(log_file="logs/events.log")

    print("[INFO] AI Proctoring System Started")

    # -------------------------------
    # Main Loop
    # -------------------------------
    while webcam.is_opened():
        frame = webcam.read()
        if frame is None:
            break

        # Face detection
        faces = face_detector.detect(frame)
        face_count = len(faces)

        # Draw face bounding boxes
        for (x, y, w, h) in faces:
            cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)

        # Apply rules
        violations = rule_engine.evaluate(face_count)

        # Log violations
        for v in violations:
            logger.log(v)

        # FPS
        fps = fps_counter.update()

        # Overlay info
        cv2.putText(frame, f"Faces: {face_count}", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

        cv2.putText(frame, f"FPS: {fps}", (10, 60),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

        if violations:
            cv2.putText(frame, f"Warning: {violations[-1]}", (10, 90),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

        # Display
        cv2.imshow("AI Proctoring - Laptop", frame)

        # Exit key
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
