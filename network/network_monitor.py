import subprocess
import re
import time
import socket

class NetworkMonitor:
    def __init__(self):
        self.last_check_time = 0
        self.cached_ssid = None
        self.last_bytes_sent = 0
        self.last_bytes_recv = 0
        self.last_traffic_check = time.time()

    def get_wifi_ssid(self):
        """
        Get the current connected WiFi SSID using Windows netsh command.
        """
        try:
            cmd = ["netsh", "wlan", "show", "interfaces"]
            output = subprocess.check_output(cmd, shell=True).decode('utf-8', errors='ignore')
            
            match = re.search(r"^\s*SSID\s*:\s*(.*)$", output, re.MULTILINE)
            if match:
                return match.group(1).strip()
            return "Ethernet/Unknown"
        except Exception:
            return "No WiFi / Error"

    def get_traffic_stats(self):
        """
        Returns average speed in KB/s since last check (Upload, Download).
        Uses 'netstat -e' for interface statistics.
        """
        try:
            cmd = ["netsh", "interface", "ipv4", "show", "subinterfaces"]
            # Parsing complex output is hard across locales.
            # Fallback to the simpler 'netstat -e' which shows total generic Ethernet stats
            output = subprocess.check_output(["netstat", "-e"], shell=True).decode('utf-8', errors='ignore')
            
            # Line 2 typically: "Bytes     123456789    987654321"
            lines = output.splitlines()
            for line in lines:
                if "Bytes" in line:
                    parts = line.split()
                    # parts[0] is "Bytes"
                    # parts[1] is Received (Download) usually
                    # parts[2] is Sent (Upload) usually
                    if len(parts) >= 3:
                        received = int(parts[1])
                        sent = int(parts[2])
                        
                        now = time.time()
                        elapsed = now - self.last_traffic_check
                        if elapsed <= 0: elapsed = 0.001
                        
                        # Calculate speeds (if not first run)
                        if self.last_bytes_recv == 0:
                            dl_speed = 0
                            ul_speed = 0
                        else:
                            dl_speed = (received - self.last_bytes_recv) / 1024 / elapsed
                            ul_speed = (sent - self.last_bytes_sent) / 1024 / elapsed
                        
                        self.last_bytes_recv = received
                        self.last_bytes_sent = sent
                        self.last_traffic_check = now
                        
                        return round(ul_speed, 1), round(dl_speed, 1) # KB/s
            
            return 0, 0
        except Exception as e:
            # print(f"Traffic check error: {e}")
            return 0, 0

    def get_active_connections(self):
        """
        Returns a count of ESTABLISHED TCP connections and list of remote IPs.
        Uses 'netstat -n'.
        """
        try:
            output = subprocess.check_output(["netstat", "-n"], shell=True).decode('utf-8', errors='ignore')
            lines = output.splitlines()
            
            established_count = 0
            remote_ips = []
            
            for line in lines:
                if "TkIP" in line: continue # filter garbage
                if "ESTABLISHED" in line:
                    established_count += 1
                    # Parse Remote Address
                    # Format: Proto  Local Address          Foreign Address        State
                    #         TCP    192.168.1.5:5000       1.2.3.4:443            ESTABLISHED
                    parts = line.split()
                    if len(parts) >= 3:
                        remote = parts[2]
                        # remote ip without port
                        if ":" in remote:
                            ip = remote.rsplit(':', 1)[0]
                            # Filter local IPs
                            if not ip.startswith("127.0") and not ip.startswith("192.168") and not ip.startswith("10."):
                                remote_ips.append(ip)
                                
            # De-dupe IPs
            remote_ips = list(set(remote_ips))
            # Limit list size for logging
            return established_count, remote_ips[:5] 
            
        except Exception:
            return 0, []

    def check_compliance(self, allowed_ssid):
        """
        Checks if the current network matches the allowed hotspot.
        """
        current_ssid = self.get_wifi_ssid()
        
        # If we are strictly enforcing hotspot
        if allowed_ssid and current_ssid != allowed_ssid:
            return False, current_ssid
            
        return True, current_ssid

    def get_local_ip(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except:
            return "127.0.0.1"
