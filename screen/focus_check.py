import ctypes
from ctypes import wintypes

class FocusMonitor:
    def __init__(self, expected_window_name="AI Proctoring - Laptop"):
        self.expected_window_name = expected_window_name
        self.user32 = ctypes.windll.user32
        # Define return types for safety
        self.user32.GetForegroundWindow.restype = wintypes.HWND
        self.user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]

    def get_active_window_title(self):
        hwnd = self.user32.GetForegroundWindow()
        length = self.user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return ""
        
        buff = ctypes.create_unicode_buffer(length + 1)
        self.user32.GetWindowTextW(hwnd, buff, length + 1)
        return buff.value

    def check_focus(self):
        """
        Checks if the expected window is in the foreground.
        Returns:
            is_violation (bool): True if focus is lost.
            current_title (str): Title of the window currently in focus.
        """
        current_title = self.get_active_window_title()
        
        # Logic: Violation if the current title is NOT the expected one.
        # Note: We use 'in' because sometimes window titles have prefixes/suffixes
        if self.expected_window_name not in current_title:
            return True, current_title
        
        return False, current_title
