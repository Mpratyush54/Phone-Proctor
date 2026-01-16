import time


class FPSCounter:
    def __init__(self):
        self.prev_time = time.time()
        self.fps = 0

    def update(self):
        """
        Calculate FPS based on time difference.
        Returns:
            fps (int)
        """
        current_time = time.time()
        delta = current_time - self.prev_time

        if delta > 0:
            self.fps = int(1 / delta)

        self.prev_time = current_time
        return self.fps
