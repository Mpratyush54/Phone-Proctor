import cv2


BLOCKED_KEYWORDS = ["virtual", "phone", "link", "obs"]


class Webcam:
    def __init__(self, camera_id=None, width=640, height=480):
        self.width = width
        self.height = height

        self.camera_id = self._select_physical_camera() if camera_id is None else camera_id
        self.cap = cv2.VideoCapture(self.camera_id)

        if not self.cap.isOpened():
            raise RuntimeError("❌ Could not open authorized webcam")

        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)

    def _select_physical_camera(self):
        """
        Select first non-virtual camera
        """
        for idx in range(5):
            cap = cv2.VideoCapture(idx)
            if not cap.isOpened():
                continue

            name = cap.getBackendName().lower()
            cap.release()

            if any(bad in name for bad in BLOCKED_KEYWORDS):
                continue

            print(f"[INFO] Authorized camera selected: index {idx}")
            return idx

        raise RuntimeError("❌ No physical webcam found")

    def is_opened(self):
        return self.cap.isOpened()

    def read(self):
        ret, frame = self.cap.read()
        return frame if ret else None

    def release(self):
        if self.cap.isOpened():
            self.cap.release()
    def get_signature(self):
        return (
        self.cap.get(cv2.CAP_PROP_FRAME_WIDTH),
        self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT),
        self.cap.get(cv2.CAP_PROP_FPS),
    )

