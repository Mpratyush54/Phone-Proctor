import cv2
import mediapipe as mp


class FaceMeshDetector:
    def __init__(self):
        self.mp_mesh = mp.solutions.face_mesh
        self.mesh = self.mp_mesh.FaceMesh(
            static_image_mode=False,
            max_num_faces=1,
            refine_landmarks=True,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        )

    def get_landmarks(self, frame):
        """
        Returns:
            landmarks: list of (x, y) tuples or None
        """
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = self.mesh.process(rgb)

        if not results.multi_face_landmarks:
            return None

        h, w, _ = frame.shape
        face_landmarks = results.multi_face_landmarks[0]

        landmarks = []
        for lm in face_landmarks.landmark:
            x = int(lm.x * w)
            y = int(lm.y * h)
            landmarks.append((x, y))

        return landmarks
