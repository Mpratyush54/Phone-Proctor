import ctypes

class MonitorCheck:
    def __init__(self):
        self.user32 = ctypes.windll.user32
        self.SM_CMONITORS = 80  # Metric index for number of monitors

    def check_monitors(self):
        """
        Checks the number of connected monitors.
        Returns:
            is_violation (bool): True if more than 1 monitor is detected.
            count (int): Number of monitors found.
        """
        count = self.user32.GetSystemMetrics(self.SM_CMONITORS)
        
        if count > 1:
            return True, count
        
        return False, count
