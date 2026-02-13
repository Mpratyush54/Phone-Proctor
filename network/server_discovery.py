import socket
import threading
import time

class DiscoveryServer:
    def __init__(self, tcp_port=5000, udp_port=5001):
        self.tcp_port = tcp_port
        self.udp_port = udp_port
        self.running = False
        self.sock = None

    def start(self):
        """Starts the UDP discovery listener and announcer."""
        self.running = True
        
        # 1. Listener Thread (Responds to Phone Probes)
        self.listener_thread = threading.Thread(target=self._listen_for_broadcasts, daemon=True)
        self.listener_thread.start()
        
        # 2. Announcer Thread (Active Broadcast from PC)
        self.announcer_thread = threading.Thread(target=self._announce_presence, daemon=True)
        self.announcer_thread.start()

        print(f"-"*40)
        print(f"[DISCOVERY] 🟢 UDP Discovery & Announcement Service Started")
        print(f"[DISCOVERY] Listening on UDP {self.udp_port}")
        print(f"[DISCOVERY] Announcing every 3s to network...")
        print(f"-"*40)

    def _listen_for_broadcasts(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        try:
            self.sock.bind(('0.0.0.0', self.udp_port))
        except Exception as e:
            print(f"[DISCOVERY] ❌ Failed to bind UDP port: {e}")
            return

        while self.running:
            try:
                data, addr = self.sock.recvfrom(1024)
                message = data.decode('utf-8').strip()
                
                # Filter out our own announcements if we catch them
                if message == "PROCTOR_ANNOUNCE":
                    continue

                print(f"[DISCOVERY] 📡 Packet from {addr}: '{message}'")
                
                if message == "PROCTOR_DISCOVER":
                    self._send_response(addr)
                    
            except Exception as e:
                pass

    def _announce_presence(self):
        """Periodically broadcasts sending PC presence to the network."""
        announce_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        announce_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        
        msg = "PROCTOR_ANNOUNCE".encode('utf-8')
        
        while self.running:
            try:
                # Broadcast to generic and common subnets
                targets = ['255.255.255.255', '192.168.1.255', '192.168.0.255', '172.20.10.15', '192.168.43.255']
                for ip in targets:
                    try:
                        announce_sock.sendto(msg, (ip, self.udp_port))
                    except: 
                        pass
                
                # Also try to send to local subnet if possible (skipped simplified)
                time.sleep(3)
            except Exception as e:
                print(f"[DISCOVERY] Announce error: {e}")
                time.sleep(5)
        
        announce_sock.close()

    def _send_response(self, addr):
        try:
            msg = "PROCTOR_HERE".encode('utf-8')
            self.sock.sendto(msg, addr)
            print(f"[DISCOVERY] ✅ Sent handshake to {addr}")
        except Exception as e:
            print(f"[DISCOVERY] ❌ Failed to send response: {e}")

    def stop(self):
        self.running = False
        if self.sock:
            self.sock.close()

if __name__ == "__main__":
    svc = DiscoveryServer()
    svc.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        svc.stop()
