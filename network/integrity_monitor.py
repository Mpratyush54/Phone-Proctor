"""
Network Integrity Monitor (VISION.md Section 5)

Rules enforced:
  1. HOTSPOT WHITELIST  - Exam is only valid if the laptop is connected to the
                          phone's hotspot (allowed SSIDs configured by proctor).
  2. DEVICE COUNT        - Number of devices on the hotspot network should stay
                           within [expected_devices_min, expected_devices_max].
                           Unexpected devices => potential helper present.
  3. DATA SPIKES         - Sustained upload/download throughput above a threshold
                           signals bulk data transfer / answer exfiltration.
                           (NO packet sniffing - OS-level interface counters only.)

Also supports a benign "network lock" that reports compliance without blocking,
leaving the decision to the rule engine / fusion module.
"""

import os
import time

# Only bind platform-specific network command helpers when available.
try:
    from .network_monitor import NetworkMonitor
    _NETWORK_MONITOR_AVAILABLE = True
except ImportError:
    NetworkMonitor = None
    _NETWORK_MONITOR_AVAILABLE = False


class NetworkIntegrityMonitor:
    def __init__(self, thresholds=None, network_monitor=None):
        if thresholds is None:
            from rules.thresholds import Thresholds
            thresholds = Thresholds()
        self.thresholds = thresholds

        # Allow injecting a NetworkMonitor (existing module) or a lightweight stub.
        if network_monitor is not None:
            self.net = network_monitor
        elif _NETWORK_MONITOR_AVAILABLE:
            self.net = NetworkMonitor()
        else:
            self.net = None

        self.allowed_ssids = self.thresholds.network_integrity("allowed_ssids", default=[]) or []
        self.enforce_hotspot = self.thresholds.network_integrity("enforce_hotspot", default=True)
        self.min_devices = self.thresholds.network_integrity("expected_devices_min", default=1)
        self.max_devices = self.thresholds.network_integrity("expected_devices_max", default=3)
        self.check_interval = self.thresholds.network_integrity("device_check_interval_sec", default=10)
        self.spike_upload_kbs = self.thresholds.network_integrity("data_spike_upload_kbs", default=80)
        self.spike_download_kbs = self.thresholds.network_integrity("data_spike_download_kbs", default=300)
        self.spike_window_sec = self.thresholds.network_integrity("data_spike_window_sec", default=5)

        # State
        self.last_device_check = 0.0
        self._spike_start_time = None
        self._last_traffic = (0, 0)  # (upload_kbs, download_kbs)
        self._violations = []

    # ------------------------------------------------------------------
    # Core checks
    # ------------------------------------------------------------------
    def check_hotspot(self):
        """
        Verifies the laptop is connected to one of the allowed (hotspot) SSIDs.
        Returns (ok: bool, current_ssid: str, message: str)
        """
        if not self.enforce_hotspot:
            return True, "N/A", "Hotspot enforcement disabled"

        if self.net is None:
            return False, "Unknown", "Network monitor unavailable"

        current_ssid = self.net.get_wifi_ssid()
        if not self.allowed_ssids:
            # No whitelist configured -> skip strict enforcement
            return True, current_ssid, "No whitelist configured"

        if current_ssid in self.allowed_ssids:
            return True, current_ssid, f"Hotspot OK: {current_ssid}"

        return False, current_ssid, f"Not on allowed hotpot: {current_ssid}"

    def get_device_count(self):
        """
        Returns the number of devices currently seen on the local network
        via the OS ARP table (no scanning / sniffing).
        """
        if self.net is None:
            return 0
        try:
            arp = self._run_command("arp -a")
            lines = arp.splitlines() if arp else []
            ips = set()
            for line in lines:
                parts = line.split()
                # Format:  interface (192.168.1.1) at xx:xx:xx:xx:xx:xx
                #          interface (192.168.1.1) at xx:xx:xx on en0
                for part in parts:
                    if part.startswith("(") and part.endswith(")") and "." in part:
                        ips.add(part.strip("()"))
                    elif "." in part and part.count(".") == 3:
                        # plain "192.168.1.2" tokens in some layouts
                        try:
                            int(part.split(".")[0])
                            ips.add(part)
                        except ValueError:
                            pass
            # Subtract gateway/self if detectable
            local_ip = ""
            if self.net:
                try:
                    local_ip = self.net.get_local_ip() or ""
                except Exception:
                    local_ip = ""
            if local_ip in ips:
                ips.remove(local_ip)
            return len(ips)
        except Exception as e:
            print(f"[NET-INTEGRITY] Device count failed: {e}")
            return 0

    def check_device_count(self):
        """
        Returns (ok: bool, count: int, message: str)
        """
        count = self.get_device_count()
        if self.min_devices <= count <= self.max_devices:
            return True, count, f"Device count OK ({count})"
        return False, count, f"Unexpected device count: {count} (expected {self.min_devices}-{self.max_devices})"

    def _run_command(self, cmd):
        """Subprocess wrapper, overridable in tests."""
        import subprocess
        try:
            result = subprocess.run(
                cmd.split(),
                capture_output=True,
                text=True,
                timeout=3,
                creationflags=0x08000000 if os.name == "nt" else 0,
            )
            return result.stdout
        except Exception:
            return ""

    def check_data_spike(self):
        """
        Monitors sustained throughput. Returns a list of messages when an
        upload/download spike above threshold persists for spike_window_sec.
        """
        if self.net is None:
            return []

        try:
            up_kbs, down_kbs = self.net.get_traffic_stats()
        except Exception as e:
            print(f"[NET-INTEGRITY] Traffic stats failed: {e}")
            return []

        is_spiking = (up_kbs > self.spike_upload_kbs) or (down_kbs > self.spike_download_kbs)

        messages = []
        now = time.time()
        if is_spiking:
            if self._spike_start_time is None:
                self._spike_start_time = now
            elif (now - self._spike_start_time) >= self.spike_window_sec:
                # Sustained spike -> violation
                msg = (f"Data spike: UP {up_kbs:.0f} KB/s / DOWN {down_kbs:.0f} KB/s"
                       f" (limits {self.spike_upload_kbs}/{self.spike_download_kbs})")
                messages = [msg]
        else:
            self._spike_start_time = None

        self._last_traffic = (up_kbs, down_kbs)
        return messages

    # ------------------------------------------------------------------
    # Aggregated evaluation (called periodically by ProctorThread)
    # ------------------------------------------------------------------
    def evaluate(self):
        """
        Runs hotspot, device-count (rate limited), and data-spike checks.
        Returns (violations: list[str], health: dict)
        """
        violations = []
        health = {"hotspot": True, "device_count": True, "data_spike": False, "ssid": "?", "devices": 0}

        # 1. Hotspot
        hotspot_ok, ssid, msg = self.check_hotspot()
        health["ssid"] = ssid
        if not hotspot_ok:
            violations.append(f"NETWORK_INTEGRITY: {msg}")
            health["hotspot"] = False

        # 2. Data spike (always check)
        spike_msgs = self.check_data_spike()
        if spike_msgs:
            violations.extend(f"NETWORK_INTEGRITY: {m}" for m in spike_msgs)
            health["data_spike"] = True

        # 3. Device count (rate limited)
        now = time.time()
        if now - self.last_device_check >= self.check_interval:
            self.last_device_check = now
            ok, count, msg = self.check_device_count()
            health["devices"] = count
            if not ok:
                violations.append(f"NETWORK_INTEGRITY: {msg}")
                health["device_count"] = False

        return violations, health