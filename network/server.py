import socket
import threading
import json
import logging

class ProctorServer:
    def __init__(self, host='0.0.0.0', port=5000):
        self.host = host
        self.port = port
        self.server_socket = None
        self.client_socket = None
        self.is_running = False
        self.latest_telemetry = {}
        self.connected_device_ip = None

    def start(self):
        """Starts the socket server in a background thread."""
        self.is_running = True
        self.thread = threading.Thread(target=self._run_server, daemon=True)
        self.thread.start()

    def _run_server(self):
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        try:
            self.server_socket.bind((self.host, self.port))
            self.server_socket.listen(1)
            print(f"[NET] Server listening on {self.host}:{self.port}...")

            while self.is_running:
                try:
                    self.server_socket.settimeout(1.0)
                    client, addr = self.server_socket.accept()
                    print(f"[NET] Phone Connected: {addr}")
                    self.connected_device_ip = addr[0]
                    self.client_socket = client
                    self._handle_client(client)
                except socket.timeout:
                    continue
                except Exception as e:
                    print(f"[NET] Connection Error: {e}")

        except Exception as e:
            print(f"[NET] Server Start Error: {e}")
        finally:
            self.stop()

    def _handle_client(self, client):
        """
        Reads data from the connected phone.
        Protocol: Newline-delimited JSON.
        """
        buffer = ""
        while self.is_running:
            try:
                data = client.recv(1024).decode('utf-8')
                if not data:
                    print("[NET] Phone Disconnected.")
                    break
                
                buffer += data
                while "\n" in buffer:
                    message_str, buffer = buffer.split("\n", 1)
                    if message_str.strip():
                        self._process_message(json.loads(message_str))
            
            except Exception as e:
                print(f"[NET] Data Read Error: {e}")
                break
        
        self.connected_device_ip = None
        self.client_socket = None
        client.close()

    def _process_message(self, msg):
        """
        Parses JSON messages from the phone.
        Expected keys: 'type', 'data'
        """
        msg_type = msg.get("type")
        data = msg.get("data")

        if msg_type == "TELEMETRY":
            # Store for the main thread to read
            self.latest_telemetry = data
            # print(f"[NET] Telemetry: {data}")
        elif msg_type == "ALERT":
            print(f"[NET] 🚨 PHONE ALERT: {data}")

    def get_status(self):
        """Returns connection status and latest telemetry."""
        return {
            "connected": self.client_socket is not None,
            "ip": self.connected_device_ip,
            "telemetry": self.latest_telemetry
        }

    def stop(self):
        self.is_running = False
        if self.server_socket:
            self.server_socket.close()
        if self.client_socket:
            self.client_socket.close()
