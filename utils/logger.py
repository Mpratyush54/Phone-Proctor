import json
import os
import cv2
import uuid
from datetime import datetime


class EventLogger:
    def __init__(self, base_dir=None, uplink=None):
        from utils.paths import session_data_dir
        self.session_id = str(uuid.uuid4())[:8]
        self.base_dir = base_dir or str(session_data_dir())
        self.session_dir = os.path.join(self.base_dir, self.session_id)
        self.images_dir = os.path.join(self.session_dir, "images")
        self.log_file = os.path.join(self.session_dir, "events.jsonl")
        self.uplink = uplink

        os.makedirs(self.images_dir, exist_ok=True)
        print(f"[DATA] Session ID: {self.session_id}. Logging to {self.session_dir}")

    def log(self, event_type, details=None, frame=None):
        """
        Log a structured event.
        :param event_type: str (e.g., "VIOLATION", "METRICS", "INFO")
        :param details: dict or str (extra data)
        :param frame: numpy array (optional) - saves image if provided
        """
        timestamp = datetime.now().isoformat()
        image_rel_path = None

        if frame is not None:
            filename = f"{int(datetime.now().timestamp() * 1000)}.jpg"
            image_path = os.path.join(self.images_dir, filename)
            cv2.imwrite(image_path, frame)
            image_rel_path = os.path.join("images", filename)

        data = details if details else {}
        if isinstance(data, str):
            data = {"msg": data}

        record = {
            "timestamp": timestamp,
            "session_id": self.session_id,
            "type": event_type,
            "image_path": image_rel_path,
            "data": data,
        }

        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

        if self.uplink is not None and event_type in (
            "VIOLATION",
            "NETWORK",
            "AUDIO",
            "TAMPERED",
            "INFO",
        ):
            try:
                self.uplink.emit(event_type, data if isinstance(data, dict) else {"msg": data})
            except Exception:
                pass

        if event_type in ["VIOLATION", "NETWORK", "INFO", "AUDIO"]:
            print(f"[LOG] {timestamp} | {details}")
