import psutil
import scapy.all as scapy
import threading
import time
import socket
from datetime import datetime
from collections import defaultdict, deque
import logging

class AdvancedNetworkMonitor:
    def __init__(self):
        # Whitelisted Processes (Educational/System)
        self.WHITELIST_PROCESSES = [
            "python.exe", "svchost.exe", "chrome.exe", "msedge.exe", "firefox.exe",
            "System", "Registry", "spoolsv.exe", "explorer.exe", "Phone-Proctor.exe"
        ]
        
        # Blacklisted Processes (Communication/Cheating)
        self.BLACKLIST_PROCESSES = [
            "discord.exe", "telegram.exe", "whatsapp.exe", "zoom.exe", "skype.exe", 
            "teamviewer.exe", "anydesk.exe", "obs64.exe", "vlc.exe"
        ]
        
        # Suspicious Ports (RDP, VNC, HTTP Proxy)
        self.SUSPICIOUS_PORTS = [3389, 5900, 8080, 1080, 53] # 53 monitored for DNS tunneling
        
        # State
        self.active_connections = {} # PID -> Connection Details
        self.packet_counts = defaultdict(int) # IP -> Count
        self.suspicious_events = []
        
        # Rolling Log of ALL events for display (Thread-safe)
        self.event_log = deque(maxlen=20) 
        self.last_known_connections = set()
        
        # Sniffer Control
        self.is_sniffing = False
        self.sniffer_thread = None
        
        logging.getLogger("scapy.runtime").setLevel(logging.ERROR)

    def start_monitoring(self):
        """
        Starts both Process-Level monitoring and Packet-Level sniffing.
        """
        self.is_sniffing = True
        
        # Start Packet Sniffer in background
        self.sniffer_thread = threading.Thread(target=self._sniff_packets, daemon=True)
        self.sniffer_thread.start()
        print("[INFO] Network Packet Sniffer Started")

    def stop_monitoring(self):
        self.is_sniffing = False

    def get_process_name(self, pid):
        try:
            return psutil.Process(pid).name()
        except:
            return "Unknown"
    
    def log_event(self, msg, is_suspicious=False):
        timestamp = datetime.now().strftime("%H:%M:%S")
        entry = f"[{timestamp}] {msg}"
        self.event_log.append(entry)
        if is_suspicious:
            self.suspicious_events.append(entry)

    def scan_active_connections(self):
        """
        Scans all open sockets on the OS using psutil.
        """
        connections = psutil.net_connections(kind='inet')
        current_conns_signature = set()
        suspicious_activity = []
        
        for conn in connections:
            if conn.status == psutil.CONN_ESTABLISHED:
                pid = conn.pid
                proc_name = self.get_process_name(pid)
                
                # Remote Address
                if conn.raddr:
                    remote_ip, remote_port = conn.raddr
                    signature = f"{proc_name}-{remote_ip}:{remote_port}"
                    current_conns_signature.add(signature)

                    # Check if NEW connection
                    if signature not in self.last_known_connections:
                        # Log it
                        self.log_event(f"New Conn: {proc_name} > {remote_ip}:{remote_port}")

                    # 1. Check Blacklist App
                    if proc_name.lower() in self.BLACKLIST_PROCESSES:
                        alert = f"Blacklisted App: {proc_name} -> {remote_ip}:{remote_port}"
                        suspicious_activity.append(alert)
                        if signature not in self.last_known_connections:
                             self.log_event(f"⚠️ {alert}", True)

                    # 2. Check Suspicious Ports
                    if remote_port in self.SUSPICIOUS_PORTS and proc_name.lower() not in self.WHITELIST_PROCESSES:
                         if remote_port in [3389, 5900]:
                             alert = f"RDP/VNC Active: {proc_name}:{remote_port}"
                             suspicious_activity.append(alert)
                             if signature not in self.last_known_connections:
                                 self.log_event(f"⚠️ {alert}", True)

                # 3. Store for analytics
                self.active_connections[pid] = {
                    "name": proc_name,
                    "remote": conn.raddr,
                    "status": "ESTABLISHED"
                }
        
        self.last_known_connections = current_conns_signature

        if suspicious_activity:
            return suspicious_activity # Just return current suspicious state for persistence check
            
        return []

    def _sniff_packets(self):
        try:
            scapy.sniff(
                prn=self._process_packet,
                store=False,
                stop_filter=lambda x: not self.is_sniffing,
                filter="ip", # Only IP traffic
                count=0 # Infinite
            )
        except Exception as e:
            print(f"[WARN] Packet Sniffing Failed (Npcap missing?): {e}")

    def _process_packet(self, packet):
        if not self.is_sniffing:
            return

        if packet.haslayer(scapy.IP):
            src_ip = packet[scapy.IP].src
            dst_ip = packet[scapy.IP].dst
            
            # Simple Volume Analysis
            self.packet_counts[src_ip] += 1
            self.packet_counts[dst_ip] += 1
            
            # DNS Inspection (if available)
            if packet.haslayer(scapy.DNS) and packet.haslayer(scapy.DNSQR):
                try:
                    query = packet[scapy.DNSQR].qname.decode('utf-8')
                    # Log ALL DNS queries (User requested "every request")
                    # Filter local noise slightly
                    if not query.endswith(".local.") and "arpa" not in query:
                         self.log_event(f"DNS Query: {query.strip('.')}")
                    
                    # Check for cheating sites
                    if any(s in query for s in ["chegg", "brainly", "chatgpt", "openai", "quora"]):
                        self.suspicious_events.append(f"Suspicious DNS Query: {query}")
                except:
                    pass

    def get_sniffing_alerts(self):
        """
        Returns and clears pending sniffing alerts.
        """
        alerts = list(self.suspicious_events)
        self.suspicious_events.clear()
        return alerts
        
    def get_recent_logs(self):
        return list(self.event_log)

    def get_top_talkers(self):
        sorted_ips = sorted(self.packet_counts.items(), key=lambda x: x[1], reverse=True)
        return sorted_ips[:5]
