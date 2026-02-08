import time


class RuleEngine:
    def __init__(self):
        # Timers
        self.face_missing_start = None
        self.multiple_faces_start = None
        self.look_away_start = None

        # Thresholds (seconds)
        self.FACE_MISSING_THRESHOLD = 5
        self.MULTIPLE_FACES_THRESHOLD = 2
        self.LOOK_AWAY_THRESHOLD = 0.5

    def evaluate_faces(self, face_count):
        violations = []
        now = time.time()

        # Face missing
        if face_count == 0:
            if self.face_missing_start is None:
                self.face_missing_start = now
            elif now - self.face_missing_start >= self.FACE_MISSING_THRESHOLD:
                violations.append("Face Missing")
        else:
            self.face_missing_start = None

        # Multiple faces
        if face_count > 1:
            if self.multiple_faces_start is None:
                self.multiple_faces_start = now
            elif now - self.multiple_faces_start >= self.MULTIPLE_FACES_THRESHOLD:
                violations.append("Multiple Faces Detected")
        else:
            self.multiple_faces_start = None

        return violations

    def evaluate_look_away(self, is_looking_away):
        violations = []
        now = time.time()

        if is_looking_away:
            if self.look_away_start is None:
                self.look_away_start = now
            elif now - self.look_away_start >= self.LOOK_AWAY_THRESHOLD:
                violations.append("Looking Away")
        else:
            self.look_away_start = None

        return violations
