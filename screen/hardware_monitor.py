
import subprocess
import threading
import time
import re

class HardwareMonitor:
    def __init__(self):
        self.blacklist_audio = [
            "stereo mix", "vb-audio", "virtual", "cable input", "cable output",
            "hands-free", "headset", "bluetooth", "airpods", "buds", "wireless"
        ]
        
        self.blacklist_video = [
            "elgato", "avermedia", "blackmagic", "rode", "obs", "xsplit", 
            "manycam", "epoccam", "droidcam", "iriun", "usb video", "capture"
        ]
        
        self.last_check_time = 0
        self.cached_violations = []
        self.is_checking = False

    def check_hardware(self):
        """
        Runs hardware checks in a non-blocking way (if possible) or fast way.
        Returns a list of violation strings.
        """
        current_time = time.time()
        
        # Don't check too often (every 5 seconds)
        if current_time - self.last_check_time < 5.0:
            return self.cached_violations
            
        if self.is_checking:
            return self.cached_violations
            
        # Start a thread to run the check so we don't block the main proctor loop
        thread = threading.Thread(target=self._run_checks)
        thread.start()
        
        self.last_check_time = current_time
        return self.cached_violations

    def _run_checks(self):
        self.is_checking = True
        violations = []
        
        try:
            # 1. Check Physical Monitors (HDMI/DP/VGA)
            # Win32_DesktopMonitor is unreliable on Win10+. Use PnPEntity 'monitor'.
            # This lists actual connected hardware screens.
            monitors = self._get_wmic_list("Win32_PnPEntity", "Caption", condition="Service='monitor'")
            if len(monitors) > 1:
                 # Filter out generic/duplicate entries if needed, but usually count is accurate for physical screens
                 violations.append(f"External Monitor(s) Detected: {len(monitors)}")
                 
                 # Also try to detect purely by PnP IDs in case of generic names
                 # (Just reporting the count is usually sufficient)
  
            # 2. Check Audio Devices (for Bluetooth/Virtual)
            # 'wmic path Win32_SoundDevice get Caption'
            audio_devices = self._get_wmic_list("Win32_SoundDevice", "Caption")
            for dev in audio_devices:
                dev_lower = dev.lower()
                for bad in self.blacklist_audio:
                    if bad in dev_lower:
                        violations.append(f"Forbidden Audio Device: {dev}")
                        break

            # 3. Check Plug and Play Video Devices (Capture Cards)
            video_devices = self._get_wmic_list("Win32_PnPEntity", "Caption", condition="Caption like '%Video%' or Caption like '%Camera%' or Caption like '%Capture%'")
            for dev in video_devices:
                dev_lower = dev.lower()
                for bad in self.blacklist_video:
                    if bad in dev_lower:
                        violations.append(f"Capture Card/Virtual Cam: {dev}")
                        break

            # 4. Check USB Storage / Suspicious USB
            # USB Rubber Ducky often appears as a generic HID keyboard or Storage
            usb_devices = self._get_wmic_list("Win32_PnPEntity", "Caption", condition="Service='USBSTOR'")
            if len(usb_devices) > 0:
                 for dev in usb_devices:
                     violations.append(f"USB Storage Detected: {dev}")
            
            # 5. Check for Change in Device Count (Simple heuristic for plugging in anything)
            # We can't easily list ALL devices every 5s without lag, but we can check specific categories.
            # Let's track the TOTAL count of PnP entities to detect insertion?
            # Too slow.
            # Stick to scanning valuable categories for "New Device".
            
            # Compare with previous checks (if implemented) to detect *new* items in these categories
            # For now, just reporting presence is safer than diffing which can be noisy.

                        
        except Exception as e:
            print(f"[HW] Check failed: {e}")
            
        self.cached_violations = list(set(violations)) # Dedupe
        self.is_checking = False

    def _get_wmic_list(self, class_name, property_name, condition=None):
        try:
            cmd = ["wmic", "path", class_name]
            if condition:
                cmd.extend(["where", condition])
            cmd.extend(["get", property_name])
            
            # Run without opening a window
            creationflags = 0x08000000 # CREATE_NO_WINDOW
            output = subprocess.check_output(cmd, creationflags=creationflags).decode('utf-8', errors='ignore')
            
            lines = [line.strip() for line in output.splitlines() if line.strip() and property_name not in line]
            return lines
        except:
            return []

    def _get_wmic_counts(self, class_name):
        lines = self._get_wmic_list(class_name, "DeviceID")
        return len(lines)
