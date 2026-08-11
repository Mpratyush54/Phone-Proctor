import os
import psutil
import scapy.all as scapy
import threading
import time
import socket
from datetime import datetime
from collections import defaultdict, deque
import logging
import subprocess

class AdvancedNetworkMonitor:
    def __init__(self):
        # Whitelisted Processes (Educational/System)
        self.WHITELIST_PROCESSES = [
             "svchost.exe", "System", "Registry", "spoolsv.exe", "explorer.exe", "Phone-Proctor.exe", "QtWebEngineProcess.exe"
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
        
        # Signature Cache (Path -> Signer Name)
        self.signer_cache = {}
        
        # Persistent dedupe for script-engine alerts (survives event buffer clears)
        self._reported_script_engines = set()
        
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
            
    def get_file_signer(self, path):
        """
        Uses PowerShell to get the Digital Signature Subject of a file.
        Returns "Unsigned" or the signer name.
        Cached to avoid repeated heavy subprocess calls.
        """
        if not path or path in ["N/A", "Registry", "System", "MemCompression"]: return "System/Virtual"
        if path in self.signer_cache: return self.signer_cache[path]
        
        try:
            # Fast check: Get-AuthenticodeSignature
            cmd = [
                "powershell", "-NoProfile", "-Command",
                f"try {{ (Get-AuthenticodeSignature '{path}' -ErrorAction Stop).SignerCertificate.Subject }} catch {{ 'Error' }}"
            ]
            # CREATE_NO_WINDOW
            output = subprocess.check_output(cmd, creationflags=0x08000000, timeout=2).decode('utf-8', errors='ignore').strip()
            
            if not output or "Error" in output or "CategoryInfo" in output:
                signer = "Unsigned/Error"
            else:
                signer = output
            
            self.signer_cache[path] = signer
            return signer
        except Exception:
            self.signer_cache[path] = "Check Failed"
            return "Check Failed"

    def get_running_process_details(self):
        """
        Returns a list of dicts: {'name', 'path', 'signer', 'trusted'} for all running processes.
        trusted = Signed by Microsoft/Google/Trusted Vendors.
        """
        procs = []
        TRUSTED_SIGNERS = ["Microsoft", "Google", "Mozilla", "Brave", "Opera", "NVIDIA", "Intel", "AMD"]
        
        for p in psutil.process_iter(['name', 'exe']):
            try:
                name = p.info['name']
                path = p.info['exe'] or "N/A"
                
                # Get Signer (Cached)
                signer = "Unknown"
                if path != "N/A":
                    # Only check signature for suspicious or non-system paths to save time?
                    # Or check everything once? 
                    # Let's check everything.
                    signer = self.get_file_signer(path)
                
                # Trust Logic: MUST be signed by a known vendor
                is_trusted = False
                if any(t in signer for t in TRUSTED_SIGNERS):
                    is_trusted = True
                elif "phone-proctor" in path.lower():
                    is_trusted = True # Trust ourselves
                
                procs.append({
                    "name": name,
                    "pid": p.pid,
                    "path": path,
                    "signer": signer,
                    "trusted": is_trusted
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
        return procs
    
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
            return suspicious_activity 
            
        # 4. Check for Suspicious Script Engines (cmd, powershell) - Even without network
        # Since this is a "scan", we can afford a quick process check
        try:
            own_pids = self._get_own_process_tree()
            for proc in psutil.process_iter(['name', 'pid']):
                try:
                    if proc.info['pid'] in own_pids:
                        # Skip our own process and the terminal that launched us
                        continue
                    pname = (proc.info['name'] or '').lower()
                    if pname in ["cmd.exe", "powershell.exe", "wscript.exe", "cscript.exe", "autohotkey.exe"]:
                        alert = f"Script Engine Detected: {pname}"
                        # Persistent dedupe: report each engine once per session.
                        # self.suspicious_events is cleared every scan by
                        # get_sniffing_alerts(), so it cannot be used for dedupe.
                        if alert not in self._reported_script_engines:
                            self._reported_script_engines.add(alert)
                            self.log_event(f"⚠️ {alert}", True)
                            suspicious_activity.append(alert)
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    pass
        except: pass

        return suspicious_activity

    def _get_own_process_tree(self):
        """
        PIDs of the current process and all of its ancestors (e.g. the terminal
        that launched the proctor app). Used to avoid self-detection false
        positives (cmd.exe / powershell.exe that run our own app).
        """
        pids = set()
        try:
            proc = psutil.Process(os.getpid())
            pids.add(proc.pid)
            for parent in proc.parents():
                pids.add(parent.pid)
        except Exception:
            pids.add(os.getpid())
        return pids

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
        
    def get_and_clear_logs(self):
        """
        Returns all accumulated logs and clears the buffer.
        """
        logs = list(self.event_log)
        self.event_log.clear()
        return logs

    def get_top_talkers(self):
        sorted_ips = sorted(self.packet_counts.items(), key=lambda x: x[1], reverse=True)
        return sorted_ips[:5]
