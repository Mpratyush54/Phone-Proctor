import cv2
import threading
import subprocess
import sys

BLOCKED_KEYWORDS = ["virtual", "phone", "link", "obs"]


class Webcam:
    def __init__(self, camera_id=None, width=640, height=480):
        self.width = width
        self.height = height
        self._lock = threading.Lock()
        self._released = False

        self.camera_id = self._select_physical_camera() if camera_id is None else camera_id
        if self.camera_id == -1:
             raise RuntimeError("❌ No physical webcam found (All available cameras are blocked/virtual)")

        backend = cv2.CAP_DSHOW if sys.platform.startswith("win") else cv2.CAP_ANY
        self.cap = cv2.VideoCapture(self.camera_id, backend)

        if not self.cap.isOpened():
            self.cap = cv2.VideoCapture(self.camera_id)

        if not self.cap.isOpened():
            raise RuntimeError("❌ Could not open authorized webcam")

        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)

        self.last_frame = None
        self.frozen_count = 0
        self.FROZEN_THRESHOLD = 30  # Number of identical frames to trigger warning

    def _get_camera_names_windows(self):
        """
        Uses PowerShell to get list of camera FriendlyNames.
        Returns list of strings.
        """
        try:
            # We look for PnP devices in 'Camera' and 'Image' classes which are active (OK)
            # This generally returns them in an order that matches OpenCV's enumeration (mostly)
            cmd = "Get-PnpDevice -Class 'Camera','Image' -Status 'OK' | Select-Object -ExpandProperty FriendlyName"
            result = subprocess.check_output(["powershell", "-Command", cmd], shell=True).decode('utf-8')
            names = [line.strip() for line in result.splitlines() if line.strip()]
            return names
        except Exception as e:
            print(f"[WARN] Could not enumerate cameras via PS: {e}")
            return []

    def _select_physical_camera(self):
        """
        Select first non-virtual camera using actual device names.
        """
        names = self._get_camera_names_windows()
        
        # If we found names, try to match them
        if names:
            print(f"[INFO] Detected Cameras: {names}")
            valid_idx = 0
            found_physical = False
            
            # Note: OpenCV index usually increments for each available video source.
            # However, exact mapping between PnP list and OpenCV index isn't 100% guaranteed strict 1:1 
            # if there are disabled devices.
             # Heuristic: Test each index. If it opens, check if "corresponding" name is blocked.
            
            for idx in range(10): # Check first 10 indices
                cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW if sys.platform.startswith("win") else cv2.CAP_ANY)
                if cap.isOpened():
                    # We have a working camera at this index.
                    # Does it match a blocked name?
                    # Since mapping is fuzzy, we check if *any* of the physically detected names 
                    # that seem to correspond to this count are blocked.
                    
                    # Safer approach: 
                    # If names list exists, assume strict ordering (Name 0 -> Index 0) for active devices.
                    if idx < len(names):
                        name = names[idx].lower()
                        is_blocked = any(bad in name for bad in BLOCKED_KEYWORDS)
                        if is_blocked:
                            print(f"[WARN] Blocking Virtual Camera (Index {idx}): {names[idx]}")
                            cap.release()
                            continue
                        else:
                            print(f"[INFO] Selected Physical Camera (Index {idx}): {names[idx]}")
                            cap.release()
                            return idx
                    else:
                        # Index out of range of names list - risky but maybe a newly plugged device
                        # Default to accepting if we ran out of names but camera works
                        cap.release()
                        return idx
                cap.release()
            
            return -1

        else:
            # Fallback: Original behavior (blind selection)
             print("[WARN] Camera name enumeration failed. Using blind fallback.")
             for idx in range(5):
                cap = cv2.VideoCapture(idx)
                if cap.isOpened():
                    # Here we can't check the name easily, but valid is better than none
                    cap.release()
                    return idx
             return -1

    def is_opened(self):
        with self._lock:
            return bool(self.cap is not None and self.cap.isOpened())

    def read(self):
        with self._lock:
            if self._released or self.cap is None:
                return None
            ret, frame = self.cap.read()
        return frame if ret else None

    def check_tampering(self, frame):
        """
        Checks for static/frozen frames (virtual camera spoofing).
        Returns: True if tampering detected.
        """
        if frame is None:
            return False

        if self.last_frame is None:
            self.last_frame = frame.copy()
            return False

        # Compute difference
        diff = cv2.absdiff(frame, self.last_frame)
        non_zero_count = cv2.countNonZero(cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY))

        self.last_frame = frame.copy()

        # If practically no pixels changed (accounting for compression noise)
        if non_zero_count < 200: 
            self.frozen_count += 1
        else:
            self.frozen_count = 0

        if self.frozen_count > self.FROZEN_THRESHOLD:
            return True
            
        return False

    def release(self):
        with self._lock:
            if self._released:
                return
            self._released = True
            if self.cap is not None:
                try:
                    if self.cap.isOpened():
                        self.cap.release()
                finally:
                    self.cap = None

    def get_signature(self):
        with self._lock:
            if self.cap is None:
                return (0, 0, 0)
            return (
                self.cap.get(cv2.CAP_PROP_FRAME_WIDTH),
                self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT),
                self.cap.get(cv2.CAP_PROP_FPS),
            )

