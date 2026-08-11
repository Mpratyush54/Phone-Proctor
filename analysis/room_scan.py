"""
Pre-Exam Room Scan (VISION.md Sections 1 & 3, Design Doc Section 12.1)

Concept: before the exam, the phone camera sweeps the room to build a baseline
of the environment: number of faces/persons, restricted objects (book, phone,
etc.), brightness, and frame-content signatures.

During the exam, periodic re-scans over the same camera feed compare against the
baseline and flag:
   - a second person appearing in the room,
   - restricted objects appearing (brought in mid-exam),
   - large scene changes (someone/something moved in).

Modules are dependency-injected so the scanner stays testable without OpenCV
(or heavy models). When no detector is supplied, only optical frame-differencing
heuristics are used.
"""

import time


class RoomScanner:
    def __init__(self, thresholds=None, object_detector=None, face_detector=None):
        if thresholds is None:
            from rules.thresholds import Thresholds
            thresholds = Thresholds()

        self.scan_enabled = thresholds.room_scan("scan_enabled", default=True)
        self.base_frames = max(thresholds.room_scan("base_frames", default=15), 1)
        self.change_threshold = thresholds.room_scan("change_threshold", default=0.18)
        self.min_second_person_frames = thresholds.room_scan("min_second_person_frames", default=3)
        self.restricted_classes = thresholds.room_scan("restricted_classes", default=["cell phone", "book", "remote", "tv"])

        self.object_detector = object_detector
        self.face_detector = face_detector

        # Baseline state
        self.has_baseline = False
        self._baseline_frames = []
        self._baseline_objects = {}      # class_name -> max count seen
        self._baseline_max_faces = 0
        self._baseline_brightness = 0.0
        self._last_frame = None

        # Second-person persistence
        self._multi_face_streak = 0
        self.last_scan_time = 0.0
        self.last_scan = {
            "changed": False,
            "faces": 0,
            "objects": [],
            "brightness": 0.0,
            "notes": [],
        }

    # ------------------------------------------------------------------
    # Baseline building
    # ------------------------------------------------------------------
    def feed_baseline_frame(self, frame):
        """Accumulates frames for the baseline. Called during pre-exam / calibration."""
        if not self.scan_enabled:
            return
        self._baseline_frames.append(frame)
        # Keep a bounded window so we always have a stable recent reference.
        if len(self._baseline_frames) > self.base_frames:
            self._baseline_frames.pop(0)

    def build_baseline(self):
        """
        Finalizes the baseline from collected frames. Returns (ok, notes[]).
        """
        if not self.scan_enabled or not self._baseline_frames:
            return False, ["No baseline frames collected"]

        notes = []
        frames = self._baseline_frames
        self._baseline_max_faces = 0
        self._baseline_objects = {}
        brightness_sum = 0.0

        for f in frames:
            brightness = self._frame_brightness(f)
            brightness_sum += brightness

            if self.face_detector is not None:
                try:
                    faces = self.face_detector.detect(f)
                    if len(faces) > self._baseline_max_faces:
                        self._baseline_max_faces = len(faces)
                except Exception as e:
                    print(f"[ROOM] face detect baseline error: {e}")

            if self.object_detector is not None:
                try:
                    detections, _ = self.object_detector.detect(f)
                    for d in detections:
                        # detections look like "Cell Phone Detected", "Book/Notes Detected"
                        key = d
                        self._baseline_objects[key] = self._baseline_objects.get(key, 0) + 1
                except Exception as e:
                    print(f"[ROOM] object detect baseline error: {e}")

        self._baseline_brightness = brightness_sum / len(frames)
        self._last_frame = frames[-1].copy()
        self.has_baseline = True

        if self._baseline_max_faces > 1:
            notes.append(f"Room baseline: {self._baseline_max_faces} people present at start")
        if self._baseline_objects:
            notes.append(f"Room baseline objects: {', '.join(self._baseline_objects)}")
        notes.append(f"Room baseline brightness: {self._baseline_brightness:.2f}")

        return True, notes

    # ------------------------------------------------------------------
    # Periodic re-scan
    # ------------------------------------------------------------------
    def scan_frame(self, frame, cooldown_sec=3.0):
        """
        Re-scans a single frame against the baseline. Rate-limited by cooldown_sec
        so the caller can call it every loop iteration cheaply.

        Returns the last_scan dict (already populated).
        """
        if not self.scan_enabled or not self.has_baseline:
            return self.last_scan

        now = time.time()
        if now - self.last_scan_time < cooldown_sec:
            return self.last_scan
        self.last_scan_time = now

        notes = []
        changed = False

        # 1. Scene-change (optical) heuristic
        if self._last_frame is not None:
            change = self._frame_diff_ratio(self._last_frame, frame)
            self._frame_change_since_last = change
            if change > self.change_threshold:
                changed = True
                notes.append(f"Room scene change detected (diff={change:.2f})")
            self._last_frame = frame.copy()

        # 2. Person count (persistence based)
        faces_now = 0
        if self.face_detector is not None:
            try:
                faces_now = len(self.face_detector.detect(frame))
            except Exception as e:
                print(f"[ROOM] face detect error: {e}")

        if faces_now >= 2:
            self._multi_face_streak += 1
        else:
            self._multi_face_streak = 0

        if self._multi_face_streak >= self.min_second_person_frames:
            changed = True
            notes.append("Second person detected in room")

        # 3. Restricted objects appearing
        object_notes = []
        if self.object_detector is not None and not changed:
            try:
                detections, _ = self.object_detector.detect(frame)
                for d in detections:
                    # Only flag objects that weren't in the baseline
                    if self._baseline_objects.get(d, 0) == 0:
                        object_notes.append(f"New object in room: {d}")
            except Exception as e:
                print(f"[ROOM] object detect error: {e}")
        if object_notes:
            changed = True
            notes.extend(object_notes)

        self.last_scan = {
            "changed": changed,
            "faces": faces_now,
            "objects": object_notes,
            "brightness": self._frame_brightness(frame),
            "notes": notes,
        }
        return self.last_scan

    # ------------------------------------------------------------------
    # Heuristics (pure, testable)
    # ------------------------------------------------------------------
    def _frame_brightness(self, frame):
        try:
            import cv2
        except ImportError:
            return 0.0
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        return float(gray.mean()) / 255.0

    def _frame_diff_ratio(self, prev, curr):
        """Normalized mean abs difference between two frames (0..1)."""
        try:
            import cv2
        except ImportError:
            return 0.0
        if prev is None or curr is None:
            return 0.0
        if prev.shape != curr.shape:
            return 1.0
        diff = cv2.absdiff(prev, curr)
        gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
        return float(gray.mean()) / 255.0