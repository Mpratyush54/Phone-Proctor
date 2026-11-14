import asyncio
import websockets
import threading
import json
import socket
import base64
import time

# Try importing OpenCV
try:
    import cv2
    import numpy as np
    OpencvAvailable = True
    print("[NET] OpenCV is available.")
except ImportError:
    OpencvAvailable = False
    print("⚠️ OpenCV not installed. Video decoding disabled.")

# Import new modules
from agent.product_mode import lan_bind_host
from .webrtc_manager import WebRTCManager
from .tcp_server import TCPServer

class ProctorServer:
    def __init__(self, host=None, port=5000, tcp_port=5001):
        self.host = host if host is not None else lan_bind_host()
        self.port = port
        self.tcp_port = tcp_port
        self.server_loop = None
        self.server_thread = None
        self.is_running = False
        self.ws_server = None
        self._stop_future = None
        
        # Data store
        self.latest_telemetry = {}
        self.connected_device_ip = None
        self.latest_frame = None # Store latest phone frame here
        self.last_frame_time = 0
        self.latest_phone_audio_level = 0
        self.latest_camera_type = None  # 'front' or 'back' from phone
        self.frame_lock = threading.Lock()
        
        # WebRTC & TCP Managers
        self.webrtc_manager = WebRTCManager(
            frame_callback=self._on_webrtc_frame, 
            audio_callback=self._on_webrtc_audio
        )
        self.tcp_server = TCPServer(port=self.tcp_port, callback=self._on_tcp_telemetry)

    def start(self):
        """Starts the WebSocket server in a background thread."""
        self.is_running = True
        
        # Start WebSocket Server Thread
        self.server_thread = threading.Thread(target=self._run_async_server, daemon=True)
        self.server_thread.start()
        
        # Start UDP Discovery
        try:
            from .server_discovery import DiscoveryServer
            self.discovery = DiscoveryServer(tcp_port=self.port)
            self.discovery.start()
        except ImportError as e:
            print(f"[NET] warning: server_discovery module not found: {e}")

    def _run_async_server(self):
        """Runs the asyncio event loop for WebSockets and TCP Server."""
        self.server_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.server_loop)
        
        print(f"[NET] WebSocket Server starting on {self.host}:{self.port}...")
        self._print_ips()

        async def start():
            # Start TCP Server
            await self.tcp_server.start()

            # max_size=10MB for images
            print(f"[NET] Listening for connections on {self.host}:{self.port}")
            try:
                self.ws_server = await websockets.serve(self._handle_client, self.host, self.port, max_size=10_000_000)
            except Exception as e:
                print(f"[NET] WebSocket Start Error: {e}")
                return

            # Run forever until stop() resolves this future
            self._stop_future = asyncio.get_running_loop().create_future()
            await self._stop_future

            # Graceful cleanup: close WS server (cancels client handlers
            # cleanly -> no "Task exception was never retrieved"), then TCP.
            try:
                self.ws_server.close()
                await self.ws_server.wait_closed()
            except Exception as e:
                print(f"[NET] WS shutdown error: {e}")
            try:
                await self.tcp_server.stop()
            except Exception as e:
                print(f"[NET] TCP shutdown error: {e}")
            try:
                await self.webrtc_manager.close()
            except Exception as e:
                print(f"[NET] WebRTC shutdown error: {e}")

        self.server_loop.run_until_complete(start())

    def _print_ips(self):
        try:
            hostname = socket.gethostname()
            ips = socket.gethostbyname_ex(hostname)[2]
            print(f"[NET] 📡 AVAILABLE SERVER IPs:")
            for ip in ips:
                if not ip.startswith("127."):
                        print(f"       👉 {ip}")
        except: pass

    async def _handle_client(self, websocket):
        """Handles a new WebSocket connection."""
        print(f"[NET] Phone Connected: {websocket.remote_address}")
        self.connected_device_ip = websocket.remote_address[0]
        self.client_ws = websocket
        self._injected_wifi_candidate = False  # Reset for new session
        
        try:
            async for message in websocket:
                try:
                    # Message can be JSON (telemetry) or just binary?
                    # Assuming JSON wrapping for now as per previous design
                    data = json.loads(message)
                    await self._process_message(data)
                except json.JSONDecodeError:
                    pass
        except websockets.exceptions.ConnectionClosed:
            print("[NET] Phone Disconnected.")
        except Exception as e:
             print(f"[NET] Connection Error: {e}")
        finally:
            self.connected_device_ip = None
            self.client_ws = None

    async def send_command(self, cmd_type, data=None):
        """Sends a command to the connected phone (async - call from event loop)."""
        if not self.client_ws:
            print(f"[NET] Cannot send {cmd_type}: No client connected")
            return False
            
        payload = json.dumps({
            "type": cmd_type,
            "data": data or {}
        })
        
        try:
            await self.client_ws.send(payload)
            print(f"[NET] ✅ Sent {cmd_type} to phone ({len(payload)} bytes)")
            return True
        except Exception as e:
            print(f"[NET] Failed to send command {cmd_type}: {e}")
            return False

    def send_command_sync(self, cmd_type, data=None):
        """Sends a command from a non-async context (other threads)."""
        if not self.client_ws or not self.server_loop:
            return False
            
        payload = json.dumps({
            "type": cmd_type,
            "data": data or {}
        })
        
        try:
            asyncio.run_coroutine_threadsafe(self.client_ws.send(payload), self.server_loop)
            return True
        except Exception as e:
            print(f"[NET] Failed to send command: {e}")
            return False

    async def _process_message(self, msg):
        try:
            # Check if message is binary (raw bytes)
            if isinstance(msg, bytes):
                # Assume raw JPEG frame (Legacy fallback)
                if OpencvAvailable:
                    loop = asyncio.get_running_loop()
                    await loop.run_in_executor(None, self._decode_binary_frame, msg)
                return

            msg_type = msg.get("type")
            data = msg.get("data")

            if msg_type == "TELEMETRY":
                # Legacy websocket telemetry (optional fallback)
                self.latest_telemetry = data
                # Extract real audio level (0..1 from phone RMS) if present
                if isinstance(data, dict):
                    audio_lvl = data.get("audioLevel", None)
                    if isinstance(audio_lvl, (int, float)):
                        self.latest_phone_audio_level = float(audio_lvl)
            
            elif msg_type == "WEBRTC_OFFER":
                # Handle WebRTC Offer
                print("[NET] Received WebRTC Offer")
                answer = await self.webrtc_manager.handle_offer(data)
                await self.send_command("WEBRTC_ANSWER", answer)

            elif msg_type == "WEBRTC_CANDIDATE":
                 # Candidate handling
                 if self.webrtc_manager:
                     await self.webrtc_manager.add_ice_candidate(data)
                     
                     # HACK: Inject Synthetic Candidate for WiFi IP if missing
                     # (Fixes issue where phone hides local IP but is connected via WiFi)
                     try:
                        cand_str = data.get('candidate', '')
                        if cand_str and 'udp' in cand_str and self.connected_device_ip:
                             parts = cand_str.split()
                             if len(parts) >= 6:
                                 port = parts[5]
                                 # Check if we already did this? (Simple toggle)
                                 if not getattr(self, '_injected_wifi_candidate', False):
                                     print(f"[NET] 💉 Injecting Synthetic WiFi Candidate: {self.connected_device_ip}:{port}")
                                     # Create simplified host candidate
                                     # foundation 1 udp priority <high> ip port typ host
                                     synth_cand = f"candidate:99999999 1 udp 2122260223 {self.connected_device_ip} {port} typ host generation 0"
                                     
                                     synth_data = data.copy()
                                     synth_data['candidate'] = synth_cand
                                     
                                     await self.webrtc_manager.add_ice_candidate(synth_data)
                                     self._injected_wifi_candidate = True
                     except Exception as e:
                         print(f"[NET] Candidate Injection Error: {e}")

            elif msg_type == "VIDEO_FRAME":
                # JSON-wrapped Base64 Frame (WS Fallback)
                if OpencvAvailable:
                    current_time = time.time()
                    if current_time - self.last_frame_time > 2.0:
                        img_data = data.get('image', '')
                        print(f"[NET] 📸 WS Frame received ({len(img_data)} bytes b64)")
                        self.last_frame_time = current_time
                    loop = asyncio.get_running_loop()
                    await loop.run_in_executor(None, self._decode_frame, data)

            elif msg_type == "ALERT":
                print(f"\n[NET] 🚨 ALERT: {data.get('type')} - {data.get('detail', '')}")

            elif msg_type == "AUDIO":
                self.latest_phone_audio_level = data.get('volume', 0)
            
            elif msg_type == "VIDEO_FALLBACK":
                # Phone reports WebRTC failed, requesting WS frame streaming
                print(f"[NET] 📸 Phone requesting VIDEO_FALLBACK mode")
                # Ask the phone to start sending frames over WebSocket
                await self.send_command("START_WS_FRAMES", {"fps": 10, "quality": 50})

        except Exception as e:
            print(f"[NET] Error processing message: {e}")
            import traceback
            traceback.print_exc()

    def _on_webrtc_frame(self, frame):
        """Callback from WebRTC Video Track"""
        if frame is not None:
             # Debug log
             current_time = time.time()
             if current_time - self.last_frame_time > 1.0: # 1s check
                 print(f"[NET] WebRTC Frame Received: {frame.shape}")
                 self.last_frame_time = current_time

             with self.frame_lock:
                self.latest_frame = frame
                
    def _on_webrtc_audio(self, level):
        """Callback from WebRTC Audio Track"""
        self.latest_phone_audio_level = level

    def _on_tcp_telemetry(self, data):
        """Callback from TCP Server"""
        # print(f"[TCP] Telemetry: {data}")
        self.latest_telemetry = data

    def _decode_binary_frame(self, data):
        try:
            nparr = np.frombuffer(data, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

            if frame is not None:
                with self.frame_lock:
                    self.latest_frame = frame
                
                # Debug log
                if time.time() - self.last_frame_time > 5:
                    # print(f"[VIDEO] Binary Frame received. Size: {frame.shape}")
                    self.last_frame_time = time.time()
            else:
                print(f"[CV debug] Error: cv2.imdecode binary returned None")

        except Exception as e:
            print(f"[CV Fatal Error] _decode_binary_frame: {e}")

    
    def _decode_frame(self, data):
        try:
            b64_img = data.get('image')
            if not b64_img:
                print(f"[CV debug] Error: 'image' key missing in VIDEO_FRAME data")
                return
            
            # Track which camera the frame came from (front=room/face, back=desk)
            self.latest_camera_type = data.get('camera')
            
            # Robust Base64 Decoding (Fix Padding)
            pad = len(b64_img) % 4
            if pad:
                b64_img += "=" * (4 - pad)
                
            try:
                img_bytes = base64.b64decode(b64_img)
            except Exception as b64e:
                print(f"[VIDEO] Base64 Decode Error: {b64e}")
                return

            nparr = np.frombuffer(img_bytes, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

            if frame is not None:
                with self.frame_lock:
                    self.latest_frame = frame
                # print(f"[CV Debug] Frame updated. Size: {frame.shape}") 
            else:
                print(f"[CV debug] Error: cv2.imdecode returned None (Corrupt JPEG?)")

        except Exception as e:
            print(f"[CV Fatal Error] _decode_frame: {e}")

    def stop(self):
        self.is_running = False
        if hasattr(self, 'discovery'):
             self.discovery.stop()
        
        # Signal the asyncio loop to shut down gracefully instead of stopping
        # it mid-await (which produced "Event loop stopped before Future
        # completed" / "Task exception was never retrieved" on exit).
        if self.server_loop and self._stop_future and not self._stop_future.done():
            try:
                self.server_loop.call_soon_threadsafe(self._stop_future.set_result, None)
            except RuntimeError:
                pass

        # Give the background thread a moment to finish cleanup.
        if self.server_thread and self.server_thread.is_alive():
            self.server_thread.join(timeout=3)

    def get_status(self):
        return {
            "running": self.is_running,
            "ip": self.connected_device_ip,
            "connected": self.connected_device_ip is not None,
            "latest_telemetry": self.latest_telemetry,
            "camera": self.latest_camera_type,
            "phone_audio": self.latest_phone_audio_level
        }
    
    def get_latest_frame(self):
        """Returns a copy of the latest phone frame under the shared lock."""
        with self.frame_lock:
            frame = self.latest_frame
            if frame is None:
                return None
            try:
                return frame.copy()
            except Exception:
                return frame
