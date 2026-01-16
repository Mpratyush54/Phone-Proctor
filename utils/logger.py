import os
from datetime import datetime


class EventLogger:
    def __init__(self, log_file="logs/events.log"):
        self.log_file = log_file
        os.makedirs(os.path.dirname(self.log_file), exist_ok=True)

    def log(self, event):
        """
        Log an event with timestamp.
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = f"{timestamp} | {event}\n"

        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(entry)

        print(f"[LOG] {entry.strip()}")
