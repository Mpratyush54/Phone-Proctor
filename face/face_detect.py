import cv2
import mediapipe as mp


class FaceDetector:
    def __init__(self, confidence=0.6):
        self.confidence = confidence
        self.mp_face = mp.solutions.face_detection
        self.detector = self.mp_face.FaceDetection(
            min_detection_confidence=self.confidence
        )

    def detect(self, frame):
        """
        Detect faces in a frame.

        Returns:
            faces: list of (x, y, w, h) bounding boxes
        """
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = self.detector.process(rgb)

        faces = []
        if results.detections:
            h, w, _ = frame.shape
            for det in results.detections:
                bbox = det.location_data.relative_bounding_box

                x = int(bbox.xmin * w)
                y = int(bbox.ymin * h)
                bw = int(bbox.width * w)
                bh = int(bbox.height * h)

                # Clamp values (safety)
                x = max(0, x)
                y = max(0, y)
                bw = min(bw, w - x)
                bh = min(bh, h - y)

                faces.append((x, y, bw, bh))

        return faces
