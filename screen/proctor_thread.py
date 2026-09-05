from PyQt5.QtCore import QThread, pyqtSignal, Qt
from PyQt5.QtGui import QImage
import cv2
import time
import numpy as np
import threading

# Import all AI & Monitoring Modules
try:
    from face.face_detect import FaceDetector
    from face.face_mesh import FaceMeshDetector
    from gaze.head_pose import HeadPoseEstimator
    from gaze.gaze_estimator import GazeEstimator
    from rules.rule_engine import RuleEngine
    from rules.thresholds import Thresholds
    from screen.focus_check import FocusMonitor
    from screen.monitor_check import MonitorCheck
    from screen.hardware_monitor import HardwareMonitor
    from network.advanced_monitor import AdvancedNetworkMonitor
    from network.integrity_monitor import NetworkIntegrityMonitor
    from camera.webcam import Webcam

    # Fusion / multi-modal modules
    from fusion.score_fusion import ScoreFusion
    from fusion.gaze_triangulation import GazeTriangulator

    # Analysis modules
    from analysis.room_scan import RoomScanner

    # Confidence engine + lip reading (were defined but never wired in)
    try:
        from ai.confidence_engine import ConfidenceEngine
    except ImportError as e:
        ConfidenceEngine = None
        print(f"[THREAD] ConfidenceEngine unavailable: {e}")

    try:
        from ai.lip_reading import LipFeatureExtractor
    except ImportError as e:
        LipFeatureExtractor = None
        print(f"[THREAD] LipFeatureExtractor unavailable: {e}")
    
    AI_AVAILABLE = True
except ImportError as e:
    AI_AVAILABLE = False
    print(f"[THREAD] AI Modules Warning: Failed to import some AI modules: {e}")

class ProctorThread(QThread):
    # Signals
    image_update = pyqtSignal(QImage) # For Webcam
    phone_update = pyqtSignal(QImage) # For Phone Camera
    status_update = pyqtSignal(dict)  # Connection status
    gaze_update = pyqtSignal(float, float, str, bool, bool)  # yaw, pitch, direction, violation, phone_face
    
    def __init__(self, server=None, dev_mode=False, logger=None, enable_sniff=False, uplink=None):
        super().__init__()
        self.server = server
        self.dev_mode = dev_mode
        self.logger = logger
        self.enable_sniff = bool(enable_sniff)
        self.uplink = uplink
        self.running = True
        
        # Placeholders
        self.audio_monitor = None
        self.obj_detector = None
        self.webcam = None
        self.face_detector = None
        self.mesh_detector = None
        self.head_pose = None
        self.gaze_estimator = None
        self.rule_engine = None
        self.focus_monitor = None
        self.monitor_check = None
        self.hw_monitor = None
        self.net_monitor = None

        # Fusion / multi-modal modules
        self.score_fusion = None
        self.triangulator = None
        self.confidence_engine = None
        self.lip_reader = None
        self.room_scanner = None
        self.net_integrity = None
        self.thresholds = None
        
        # Async State
        self.process_scan_running = False
        self.blocking_apps = []

        # Persistent dedupe for state-type violations that repeat every frame
        # (e.g. NETWORK_INTEGRITY device count). Prevents log spam for the same
        # unchanged condition while still re-reporting if the message changes.
        self._reported_integrity_violations = set()

    def _async_process_scan(self):
        """Runs heavy process snapshotting in a separate thread."""
        try:
            if not self.net_monitor: return
            
            all_procs = self.net_monitor.get_running_process_details()
            
            # Identify Blocking Apps (Browsers, Remote Tools, Chat)
            # SafeBrowser uses QtWebEngineProcess, not chrome.exe
            blocklist = [
                "chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe",
                "discord.exe", "teamviewer.exe", "anydesk.exe", "zoom.exe", "skype.exe", 
                "whatsapp.exe", "telegram.exe", "obs64.exe"
            ]
            
            detected_blocks = []
            for p in all_procs:
                if p["name"].lower() in blocklist:
                     detected_blocks.append({"name": p["name"], "pid": p["pid"]})
            
            self.blocking_apps = detected_blocks

            # Filter Untrusted
            trusted_procs = [p['name'] for p in all_procs if p['trusted']]
            untrusted_procs = [p for p in all_procs if not p['trusted']]
            
            # Log Violation if Blocking Apps Found
            if detected_blocks:
                    names = ", ".join(set(b["name"] for b in detected_blocks))
                    if self.logger: self.logger.log("VIOLATION", f"Blocked App(s) Running: {names}")
            
            # Full Detailed Dump to File (Optimized)
            if self.logger:
                snapshot_data = {
                    "timestamp": time.strftime("%H:%M:%S"),
                    "total_processes": len(all_procs),
                    "trusted_count": len(trusted_procs),
                    "untrusted_count": len(untrusted_procs),
                    "untrusted_details": untrusted_procs,
                    "trusted_names": sorted(trusted_procs)
                }
                self.logger.log("INFO", details={"msg": "Process Snapshot Summary", "data": snapshot_data})
                
        except Exception as e:
            print(f"[THREAD] Async Process Scan Error: {e}")
        finally:
            self.process_scan_running = False

    def _init_ai_components(self):
        if not AI_AVAILABLE: return
        from agent.consent import Capability
        decision = getattr(self, "consent_decision", None)
        def allowed(cap: Capability) -> bool:
            if decision is None:
                return True  # local development: capabilities start unless gated
            return decision.may_start(cap)
        try:
            print("[THREAD] Initializing AI Components...")
            # 1. Audio
            try:
                if allowed(Capability.MICROPHONE):
                    from ai.audio import AudioMonitor
                    self.audio_monitor = AudioMonitor(logger=self.logger)
                    self.audio_monitor.start()
                else:
                    print("[THREAD] Microphone declined — audio monitor not started")
            except Exception as e: print(f"[WARN] Audio Init: {e}")

            # 2. YOLO
            try:
                from ai.object_detector import ObjectDetector
                self.obj_detector = ObjectDetector()
            except Exception as e: print(f"[WARN] ObjectDetector Init: {e}")

            # 3. Vision
            self.face_detector = FaceDetector()
            self.mesh_detector = FaceMeshDetector()
            self.head_pose = HeadPoseEstimator()
            self.gaze_estimator = GazeEstimator()
            self.rule_engine = RuleEngine()
            self.thresholds = Thresholds()
            
            # 4. System
            self.focus_monitor = FocusMonitor()
            self.monitor_check = MonitorCheck()
            self.hw_monitor = HardwareMonitor()
            if allowed(Capability.NETWORK_MONITOR):
                self.net_monitor = AdvancedNetworkMonitor(enable_sniff=self.enable_sniff)
                self.net_monitor.start_monitoring()
            else:
                print("[THREAD] Network monitor declined — not started")

            # 5. Fusion / multi-modal (VISION.md Sections 6 & 7)
            self.score_fusion = ScoreFusion(thresholds=self.thresholds)
            self.triangulator = GazeTriangulator(thresholds=self.thresholds)
            self.confidence_engine = ConfidenceEngine() if ConfidenceEngine else None
            self.lip_reader = None
            if LipFeatureExtractor:
                try:
                    self.lip_reader = LipFeatureExtractor()
                except Exception as e:
                    print(f"[WARN] LipReader Init: {e}")

            # 6. Network integrity (VISION.md Section 5)
            try:
                self.net_integrity = NetworkIntegrityMonitor(thresholds=self.thresholds)
            except Exception as e:
                print(f"[WARN] NetIntegrity Init: {e}")
                self.net_integrity = None

            # 7. Room scanner (Design Doc 12.1)
            try:
                self.room_scanner = RoomScanner(
                    thresholds=self.thresholds,
                    object_detector=self.obj_detector,
                    face_detector=self.face_detector,
                )
            except Exception as e:
                print(f"[WARN] RoomScanner Init: {e}")
                self.room_scanner = None

            print("[THREAD] AI Components Ready")
        except Exception as e:
            print(f"[ERROR] AI Init Failed: {e}")


    def run(self):
        print(f"[THREAD] Proctor Logic Started (Dev Mode: {self.dev_mode})")
        
        # --- 0. Send Loading Frame Immediately ---
        loading_frame = np.zeros((480, 640, 3), dtype=np.uint8)
        cv2.putText(loading_frame, "INITIALIZING AI SYSTEMS...", (50, 240), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 165, 0), 2)
        cv2.putText(loading_frame, "Please Wait...", (50, 280), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 1)
        try:
            rgb_load = cv2.cvtColor(loading_frame, cv2.COLOR_BGR2RGB)
            h, w, ch = rgb_load.shape
            qt_load = QImage(rgb_load.data, w, h, ch*w, QImage.Format_RGB888).copy()
            self.image_update.emit(qt_load)
        except: pass
            
        # --- 1. Init AI (Heavy Lifting) ---
        if not self.dev_mode:
            self._init_ai_components()

        self.webcam = None
        if not self.dev_mode and AI_AVAILABLE:
             from agent.consent import Capability
             decision = getattr(self, "consent_decision", None)
             camera_ok = decision is None or decision.may_start(Capability.CAMERA)
             if camera_ok:
                 try:
                     self.webcam = Webcam() # Use custom wrapper
                     print(f"[THREAD] Webcam Initialized: {self.webcam.get_signature()}")
                 except Exception as e:
                     print(f"[THREAD] Webcam Init Failed: {e}")
                     if self.logger:
                         self.logger.log("ERROR", f"Webcam Init Failed: {e}")
             else:
                 print("[THREAD] Camera declined — self.webcam not started")
        
        frame_count = 0
        
        # Audio/Camera State
        self.using_back_camera = False
        
        # Head Pose Smoothing
        self.smooth_yaw = 0
        self.smooth_pitch = 0
        
        # --- CALIBRATION STATE MACHINE ---
        # 0: Waiting for Phone
        # 1: Intrinsic/Face Check (Look Straight - Stability)
        # 2: Capture Neutral Baseline
        # 3: Look Left (Range Check)
        # 4: Look Right (Range Check)
        # 5: Look Up
        # 6: Look Down
        # 7: Complete
        self.calibrating = True
        self.calib_stage = 0
        self.calib_timer = 0
        self.calib_data = []
        
        # Baselines
        self.baseline_yaw = 0
        self.baseline_pitch = 0
        self.range_yaw = [-30, 30] # default safe range
        self.range_pitch = [-20, 20] # default safe range

        # Phone face state (for 3D viz)
        self.phone_face_detected = False

        while self.running:
            try:
                frame_count += 1
                current_time = time.time()
                
                # --- 1. Network Status & Phone Logic ---
                net_status = {
                    "connected": False,
                    "ip": "N/A",
                    "audio_diff": False,
                    "logs": [],
                    "blocking_apps": []
                }
                
                # Copy from async thread
                if hasattr(self, "blocking_apps"):
                    net_status["blocking_apps"] = self.blocking_apps

                if self.server:
                    s = self.server.get_status()
                    connected = s["connected"]
                    net_status["connected"] = connected
                    net_status["ip"] = s["ip"] if connected else "Listening..."
                    
                # Phone Frame Logic (Continuous)
                phone_frame = self.server.get_latest_frame()
                
                if phone_frame is not None:
                    # OPTIMIZATION: Resize
                    h, w = phone_frame.shape[:2]
                    if w > 640:
                        scale = 640 / w
                        new_h = int(h * scale)
                        phone_frame = cv2.resize(phone_frame, (640, new_h))
                else:
                    # Fallback Placeholder
                    phone_frame = np.zeros((480, 640, 3), dtype=np.uint8)
                    if connected:
                        cv2.putText(phone_frame, "VIDEO CONNECTING...", (50, 240), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 255), 2)
                        cv2.putText(phone_frame, "Please Wait...", (50, 290), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (200, 200, 200), 1)
                    else:
                        cv2.putText(phone_frame, "WAITING FOR PHONE...", (50, 240), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)

                display_frame = phone_frame.copy()
                        
                # A. Continuous Side-Angle Monitoring (Triangulation Lite)
                # We use Phone (Side View) to ensure profile view (No frontal face)
                if self.face_detector and phone_frame is not None:
                        if frame_count % 10 == 0: 
                            p_faces = self.face_detector.detect(phone_frame)
                            self.phone_face_detected = len(p_faces) > 0
                            if self.phone_face_detected:
                                msg = "ALERT: Head Turn Detected (Phone View)"
                                if frame_count % 60 == 0:
                                    print(f"[THREAD] {msg}")
                                    net_status["logs"].append(msg)
                                
                                # Visual Alert
                                cv2.putText(display_frame, "LOOK AT SCREEN!", (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 3)
                                for (px, py, pw, ph) in p_faces:
                                        cv2.rectangle(display_frame, (px, py), (px+pw, py+ph), (0, 0, 255), 3)

                # A2. Room Scan Baseline Feeding (Pre-Exam, Design Doc 12.1)
                # While waiting for calibration to finish (phone active), feed
                # phone frames into the room-scanner to build the environment baseline.
                if (self.room_scanner and phone_frame is not None
                        and self.calibrating and not self.room_scanner.has_baseline):
                    # Rate-limit feeding to keep the loop fast
                    if frame_count % 5 == 0:
                        self.room_scanner.feed_baseline_frame(phone_frame)

                # A3. Periodic Room Re-Scan (During Exam)
                if (self.room_scanner and phone_frame is not None and not self.calibrating):
                    scan = self.room_scanner.scan_frame(phone_frame, cooldown_sec=5.0)
                    if scan["changed"]:
                        for note in scan["notes"]:
                            if note not in net_status["logs"]:
                                net_status["logs"].append(f"ROOM: {note}")
                                if self.logger:
                                    self.logger.log("VIOLATION", f"ROOM: {note}", phone_frame)

                # B. Object Detection (YOLO - Server Side)
                detections_this_frame = False
                if self.obj_detector and frame_count % 30 == 0:
                    detections, _ = self.obj_detector.detect(phone_frame)
                    if detections:
                        detections_this_frame = True
                        for d in detections:
                            # Log format: { object: "name", confidence: 0.XX, bbox: [...] } (Simplified for log)
                            log_msg = f"OBJECT: {d}" 
                            net_status["logs"].append(log_msg)
                            if self.logger:
                                self.logger.log("VIOLATION", details=log_msg, frame=phone_frame)

                try:
                    p_rgb = cv2.cvtColor(display_frame, cv2.COLOR_BGR2RGB)
                    h, w, ch = p_rgb.shape
                    qt_img = QImage(p_rgb.data, w, h, ch*w, QImage.Format_RGB888).copy()
                    self.phone_update.emit(qt_img)
                except Exception as e:
                    print(f"[THREAD] Phone frame error: {e}")

                # Audio Comparison Logic
                phone_vol = getattr(self.server, 'latest_phone_audio_level', 0)
                pc_vol = 0.0
                if self.audio_monitor:
                    pc_vol = self.audio_monitor.get_current_volume()
                
                if pc_vol > 0.2 and phone_vol < 0.05:
                     msg = "Audio Alert: Noise at PC not on Phone"
                     if frame_count % 30 == 0:
                         net_status["logs"].append(msg)
                         if self.logger: self.logger.log("VIOLATION", details=msg)
                
                if phone_vol > 0.2 and pc_vol < 0.05:
                     msg = "Audio Alert: Noise at Phone not on PC"
                     if frame_count % 30 == 0:
                         net_status["logs"].append(msg)
                         if self.logger: self.logger.log("VIOLATION", details=msg)

                if connected:
                    net_status["phone_vol"] = f"{phone_vol:.2f}"
                    net_status["pc_vol"] = f"{pc_vol:.2f}"
                
        
                # --- 2. Webcam & AI Proctoring Logic ---
                frame = None
                if self.webcam and self.webcam.is_opened():
                    frame = self.webcam.read()
                
                # FALLBACK: Create Dummy Frame if Webcam Fails
                if frame is None:
                    # Create Fallback Error Frame (480p Black)
                    frame = np.zeros((480, 640, 3), dtype=np.uint8)
                    cv2.putText(frame, "WEBCAM FAILURE", (50, 200), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 0, 255), 3)
                    cv2.putText(frame, "Check Camera Connection", (50, 250), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
                    if not AI_AVAILABLE:
                         cv2.putText(frame, "AI MODULES MISSING", (50, 300), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
                
                annotated_frame = frame.copy()
                h, w = frame.shape[:2]
                
                # Only run AI if self.webcam actually works and is not dummy
                if self.webcam and self.webcam.is_opened():
                     # Tamper Check
                    if self.webcam.check_tampering(frame):
                             cv2.putText(annotated_frame, "TAMPERING DETECTED", (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 3)

                    if self.face_detector and self.mesh_detector: 
                        # a. Detect Faces
                        faces = self.face_detector.detect(frame)
                        face_count = len(faces)
                        
                        for (x, y, w_box, h_box) in faces:
                            cv2.rectangle(annotated_frame, (x, y), (x+w_box, y+h_box), (0, 255, 0), 2)
                        
                        # b. Head Pose & Gaze
                        if face_count == 1:
                            landmarks = self.mesh_detector.get_landmarks(frame)
                            if landmarks:
                                # 1. Head Pose Extraction
                                raw_yaw, raw_pitch = self.head_pose.estimate(landmarks, frame.shape)
                                
                                # Normalize to [-180, 180]
                                if raw_pitch > 180: raw_pitch -= 360
                                elif raw_pitch < -180: raw_pitch += 360
                                
                                if raw_yaw > 180: raw_yaw -= 360
                                elif raw_yaw < -180: raw_yaw += 360

                                # --- CALIBRATION SEQUENCE ---
                                if self.calibrating:
                                    phone_active = (self.server.get_latest_frame() is not None)
                                    
                                    # Overlay Text Helper
                                    def draw_instr(text, subtext=""):
                                        cv2.putText(annotated_frame, text, (40, 100), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 0), 2)
                                        if subtext:
                                            cv2.putText(annotated_frame, subtext, (40, 140), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 2)

                                    if self.calib_stage == 0:
                                        draw_instr("WAITING FOR DEVICES...", "Connect Phone & Place at Side View")
                                        if phone_active:
                                            self.calib_stage = 1
                                            self.calib_timer = 0
                                    
                                    elif self.calib_stage == 1:
                                        draw_instr("STEP 1: SIT NORMALLY", "Look Straight at Screen")
                                        self.calib_timer += 1
                                        if self.calib_timer > 60: # 2 sec
                                            self.calib_stage = 2
                                            self.calib_timer = 0
                                            self.calib_data = []

                                    elif self.calib_stage == 2:
                                        draw_instr("CAPTURING NEUTRAL BASELINE", "Keep Looking Straight")
                                        self.calib_data.append((raw_yaw, raw_pitch))
                                        # Visual Progress
                                        cv2.rectangle(annotated_frame, (50, 160), (int(50 + (len(self.calib_data)*4)), 170), (0, 255, 0), -1)
                                        
                                        if len(self.calib_data) > 60: # Capture for 2 sec
                                            # Compute Baseline
                                            avg_y = sum(x[0] for x in self.calib_data)/len(self.calib_data)
                                            avg_p = sum(x[1] for x in self.calib_data)/len(self.calib_data)
                                            self.baseline_yaw = avg_y
                                            self.baseline_pitch = avg_p
                                            print(f"[CALIB] Neutral Baseline Set: Y={avg_y:.1f}, P={avg_p:.1f}")
                                            
                                            self.calib_stage = 3
                                            self.calib_timer = 0
                                    
                                    elif self.calib_stage == 3:
                                        draw_instr("STEP 2: LOOK LEFT", "Turn head left comfortably")
                                        self.calib_timer += 1
                                        if abs(raw_yaw - self.baseline_yaw) > 20 and self.calib_timer > 30:
                                            self.calib_stage = 4
                                            self.calib_timer = 0

                                    elif self.calib_stage == 4:
                                        draw_instr("STEP 3: LOOK RIGHT", "Turn head right comfortably")
                                        self.calib_timer += 1
                                        if abs(raw_yaw - self.baseline_yaw) > 20 and self.calib_timer > 30:
                                            self.calib_stage = 5
                                            self.calib_timer = 0
                                    
                                    elif self.calib_stage == 5:
                                        draw_instr("STEP 4: LOOK UP", "Chin up")
                                        self.calib_timer += 1
                                        if (raw_pitch - self.baseline_pitch) > 10 and self.calib_timer > 30: # Pitch up is usually positive
                                                self.calib_stage = 6
                                                self.calib_timer = 0
                                    
                                    elif self.calib_stage == 6:
                                        draw_instr("STEP 5: LOOK DOWN", "Chin down")
                                        self.calib_timer += 1
                                        if (self.baseline_pitch - raw_pitch) > 10 and self.calib_timer > 30:
                                                self.calib_stage = 7
                                                self.calib_timer = 0

                                    elif self.calib_stage == 7:
                                        draw_instr("CALIBRATION COMPLETE", "Starting Exam...")
                                        self.calib_timer += 1
                                        if self.calib_timer > 30:
                                            self.calibrating = False
                                            print("[CALIB] Calibration Finished. Monitoring Active.")
                                            # Finalize room-scan baseline now that
                                            # calibration frames have been collected.
                                            if self.room_scanner:
                                                ok, notes = self.room_scanner.build_baseline()
                                                for n in notes:
                                                    print(f"[ROOM] {n}")
                                                    if self.logger:
                                                        self.logger.log("INFO", details=n)

                                # --- MONITORING PHASE ---
                                else:
                                    # Calculate Deviation from Baseline
                                    yaw_diff = raw_yaw - self.baseline_yaw
                                    pitch_diff = raw_pitch - self.baseline_pitch

                                    # Normalize Diffs
                                    if yaw_diff > 180: yaw_diff -= 360
                                    elif yaw_diff < -180: yaw_diff += 360
                                    if pitch_diff > 180: pitch_diff -= 360
                                    elif pitch_diff < -180: pitch_diff += 360

                                    # Smoothing
                                    alpha = 0.15
                                    self.smooth_yaw = (alpha * yaw_diff) + ((1 - alpha) * self.smooth_yaw)
                                    self.smooth_pitch = (alpha * pitch_diff) + ((1 - alpha) * self.smooth_pitch)
                                    
                                    yaw = self.smooth_yaw
                                    pitch = self.smooth_pitch

                                    # Thresholds (Degrees deviation from PERSONAL baseline)
                                    YAW_THRESH = 35 
                                    PITCH_THRESH = 30 
                                    
                                    is_head_away = (abs(yaw) > YAW_THRESH or abs(pitch) > PITCH_THRESH)
                                    
                                    # Gaze Check
                                    is_gaze_away = False
                                    gaze_data = {}
                                    if self.gaze_estimator:
                                            is_gaze_away, gaze_data = self.gaze_estimator.estimate(landmarks, frame.shape)
                                    
                                    # Visuals
                                    if is_head_away:
                                        cv2.putText(annotated_frame, f"HEAD VIOLATION: dY={int(yaw)} dP={int(pitch)}", (50, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
                                        cv2.rectangle(annotated_frame, (0,0), (w,h), (0,0,255), 4)
                                    elif is_gaze_away:
                                        d = gaze_data.get("direction", "?")
                                        cv2.putText(annotated_frame, f"GAZE VIOLATION: {d}", (50, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 165, 255), 2)
                                        cv2.rectangle(annotated_frame, (0,0), (w,h), (0,165,255), 4)

                                    # Logging Logic (Preserved as requested)
                                    if is_head_away or is_gaze_away:
                                        msgs = self.rule_engine.evaluate_look_away(True)
                                        for m in msgs:
                                            violation_type = "HEAD_AWAY" if is_head_away else "GAZE_AWAY"
                                            full_msg = f"{m} ({violation_type} | Y:{int(yaw)} P:{int(pitch)})"
                                            net_status["logs"].append(full_msg)
                                            if self.logger: self.logger.log("VIOLATION", full_msg, frame)
                                    else:
                                        self.rule_engine.evaluate_look_away(False)

                                    # Emit 3D Gaze Viz (combining self.webcam pose + phone view)
                                    direction = gaze_data.get('direction', 'CENTER') if gaze_data else 'CENTER'
                                    is_violation = is_head_away or is_gaze_away
                                    try:
                                        self.gaze_update.emit(
                                            float(yaw), float(pitch),
                                            direction, is_violation,
                                            self.phone_face_detected
                                        )
                                    except: pass

                                    # ── Multi-Modal Fusion (VISION Section 6/7) ──
                                    # 1. 3D Gaze Triangulation (Design Doc 12.2)
                                    triangulation = None
                                    if self.triangulator:
                                        try:
                                            triangulation = self.triangulator.triangulate(
                                                float(yaw), float(pitch),
                                                phone_face_detected=self.phone_face_detected,
                                            )
                                            if triangulation["looking_at_phone"]:
                                                msg = f"GAZE TRIANGULATION: looking at phone region (dist {triangulation['phone_distance_cm']}cm)"
                                                net_status["logs"].append(msg)
                                                if self.logger:
                                                    self.logger.log("VIOLATION", msg, frame)
                                        except Exception as e:
                                            print(f"[THREAD] Triangulation Error: {e}")

                                    # 2. Lip Reading + Confidence Engine
                                    vad_prob = 0.0
                                    lip_prob = 0.0
                                    if self.audio_monitor:
                                        try:
                                            vad_prob = self.audio_monitor.get_voice_activity()
                                        except Exception:
                                            vad_prob = 0.0
                                    if self.lip_reader:
                                        try:
                                            lip_prob, _ = self.lip_reader.process(frame, landmarks)
                                        except Exception as e:
                                            print(f"[THREAD] LipReader Error: {e}")

                                    confidence_result = None
                                    if self.confidence_engine:
                                        try:
                                            confidence_result = self.confidence_engine.evaluate(
                                                vad_prob, lip_prob,
                                                raw_yaw, raw_pitch, face_count
                                            )
                                            if confidence_result["status"] != "SAFE":
                                                for r in confidence_result["reasons"]:
                                                    full = f"CONFIDENCE [{confidence_result['status']}]: {r}"
                                                    if full not in net_status["logs"]:
                                                        net_status["logs"].append(full)
                                                        if self.logger:
                                                            self.logger.log("VIOLATION", full, frame)
                                        except Exception as e:
                                            print(f"[THREAD] ConfidenceEngine Error: {e}")

                                    # 3. Score Fuser (all signals -> single confidence)
                                    if self.score_fusion:
                                        try:
                                            fused = self.score_fusion.fuse({
                                                "gaze_away": 1.0 if is_gaze_away else 0.0,
                                                "head_away": 1.0 if is_head_away else 0.0,
                                                "phone_face": 1.0 if self.phone_face_detected else 0.0,
                                                "multi_face": 1.0 if face_count > 1 else 0.0,
                                                "no_face": 1.0 if face_count == 0 else 0.0,
                                                "object": 1.0 if detections_this_frame else 0.0,
                                                "audio": 1.0 if vad_prob > 0.5 else 0.0,
                                            })
                                            if fused["status"] != "SAFE":
                                                for r in fused["reasons"]:
                                                    full = f"FUSION [{fused['status']} {fused['score']:.2f}]: {r}"
                                                    if full not in net_status["logs"]:
                                                        net_status["logs"].append(full)
                                                        if self.logger:
                                                            self.logger.log("VIOLATION", full, frame)
                                        except Exception as e:
                                            print(f"[THREAD] ScoreFusion Error: {e}")

                                        # c0. Periodic METRICS logging (~2 Hz) for model training.
                                        #     Real sessions now emit the same schema as the synthetic
                                        #     data produced by tools/generate_synthetic_data.py, so a
                                        #     single frame-model can train on both.
                                        if frame_count % 15 == 0 and self.logger:
                                            try:
                                                fused_obj = locals().get("fused") or {}
                                                fused_score = float(fused_obj.get("score", 0.0))
                                                fused_status = fused_obj.get("status", "SAFE")
                                                gaz_d = gaze_data.get("direction", "CENTER") if gaze_data else "CENTER"
                                                tri_obj = triangulation or {}
                                                metric_data = {
                                                    "gaze_h": round(float(gaze_data.get("h_ratio", 0.5)), 4) if gaze_data else 0.5,
                                                    "gaze_v": round(float(gaze_data.get("v_ratio", 0.5)), 4) if gaze_data else 0.5,
                                                    "head_yaw": round(float(raw_yaw), 2),
                                                    "head_pitch": round(float(raw_pitch), 2),
                                                    "yaw_diff": round(float(yaw), 2),
                                                    "pitch_diff": round(float(pitch), 2),
                                                    "face_count": int(face_count),
                                                    "phone_face": 1 if self.phone_face_detected else 0,
                                                    "phone_yaw": 0.0,
                                                    "phone_pitch": 0.0,
                                                    "gaze_direction": gaz_d,
                                                    "screen_region": tri_obj.get("screen_region", "OFF_SCREEN"),
                                                    "on_screen": 1 if tri_obj.get("on_screen") else 0,
                                                    "looking_at_phone": 1 if tri_obj.get("looking_at_phone") else 0,
                                                    "phone_distance_cm": round(tri_obj.get("phone_distance_cm", -1.0), 2) if tri_obj else -1.0,
                                                    "vad_prob": round(float(vad_prob), 4),
                                                    "lip_prob": round(float(lip_prob), 4),
                                                    "fused_score": fused_score,
                                                    "fused_status": fused_status,
                                                    "head_away": int(is_head_away),
                                                    "gaze_away": int(is_gaze_away),
                                                    "is_looking_away": int(is_head_away or is_gaze_away),
                                                }
                                                self.logger.log("METRICS", metric_data)
                                            except Exception as e:
                                                print(f"[THREAD] METRICS Log Error: {e}")

                        # c. Face Count Rules
                        msgs = self.rule_engine.evaluate_faces(face_count)
                        for m in msgs:
                            net_status["logs"].append(f"AI: {m}")
                            if self.logger: self.logger.log("VIOLATION", m, frame)
                    
                    # PROCESS SNAPSHOT (Async Thread - Avoids UI Freeze)
                    if self.net_monitor and frame_count % 300 == 0:
                        if not self.process_scan_running:
                            self.process_scan_running = True
                            threading.Thread(target=self._async_process_scan, daemon=True).start()
                            
                    # d. Focus Check
                    if self.focus_monitor and frame_count % 10 == 0:
                        is_lost, title = self.focus_monitor.check_focus()
                        if is_lost:
                            # Filter Dev/IDE/shell windows from UI logs to reduce noise
                            # during testing. Note: In production exam, ANY focus loss
                            # is a violation.
                            dev_noise = [
                                "Antigravity", "Visual Studio", "Windows Terminal",
                                "Command Prompt", "cmd.exe", "powershell", "PowerShell",
                                "conhost", "python", "pythonw", "node", "Node.js",
                            ]
                            if not any(dev in title for dev in dev_noise):
                                msg = f"Focus Lost: {title}"
                                net_status["logs"].append(msg)
                                if self.logger: self.logger.log("VIOLATION", msg)

                    # e. Monitor Check (Standard + Advanced Hardware)
                    if self.monitor_check and frame_count % 100 == 0:
                        # Existing monitor check (simple)
                        is_multi, count = self.monitor_check.check_monitors()
                        if is_multi:
                            msg = f"Multi-Monitor: {count} screens"
                            if msg not in net_status["logs"]:
                                net_status["logs"].append(msg)
                                if self.logger: self.logger.log("VIOLATION", msg)
                        
                        # Advanced Hardware Check (Capture Cards/Bluetooth)
                        if self.hw_monitor:
                            hw_issues = self.hw_monitor.check_hardware()
                            for issue in hw_issues:
                                if issue not in net_status["logs"]:
                                    net_status["logs"].append(f"HW: {issue}")
                                    if self.logger: self.logger.log("VIOLATION", issue)
                            
                    # f. Network Alerts & Monitoring
                    if self.net_monitor and frame_count % 60 == 0:
                        # 1. Run Active Scan (Process/Connection check)
                        self.net_monitor.scan_active_connections()

                        # 2. Log Violations to Backend (Alerts only)
                        alerts = self.net_monitor.get_sniffing_alerts()
                        for a in alerts:
                            if self.logger: self.logger.log("VIOLATION", a)

                        # 3. Send All Traffic Logs to UI and Logger
                        traffic_logs = self.net_monitor.get_and_clear_logs()
                        
                        # UI Noise Filter
                        ui_ignored = ["127.0.0.1", "localhost", "Antigravity", "language_server", "Code.exe", "adb.exe", "svchost.exe", "SearchHost.exe", "conhost.exe"]
                        
                        for log in traffic_logs:
                             # Skip noisy local/dev logs for UI
                             if not any(ign in log for ign in ui_ignored):
                                 net_status["logs"].append(f"NET: {log}")
                              
                             if self.logger:
                                  # Send ALL network logs to file/terminal for audit
                                  self.logger.log("NETWORK", log)

                    # g. Network Integrity (VISION Section 5: hotspot whitelist,
                    #    device count, data spikes)
                    if self.net_integrity and frame_count % 60 == 0:
                        try:
                            violations, health = self.net_integrity.evaluate()
                            for v in violations:
                                # Dedupe unchanged conditions: net_status["logs"]
                                # is cleared every frame, so only log once until
                                # the message actually changes.
                                if v not in self._reported_integrity_violations:
                                    self._reported_integrity_violations.add(v)
                                    net_status["logs"].append(v)
                                    if self.logger:
                                        self.logger.log("VIOLATION", v)
                        except Exception as e:
                            print(f"[THREAD] NetIntegrity Error: {e}")

                # Emit Frame (Whether it's real or error frame)
                try:
                    rgb_image = cv2.cvtColor(annotated_frame, cv2.COLOR_BGR2RGB)
                    h, w, ch = rgb_image.shape
                    qt_image = QImage(rgb_image.data, w, h, ch*w, QImage.Format_RGB888).copy()
                    self.image_update.emit(qt_image)
                except Exception as e:
                    print(f"[THREAD] Frame Emit Error: {e}")

                # Force Clear Logs from UI (User Request: "dont show any thing in html pagr")
                # Backend logging (file/terminal) is still active via self.logger.log calls above.
                net_status["logs"] = [] 

                self.status_update.emit(net_status)
                
                time.sleep(0.03)

            except Exception as e:
                print(f"[THREAD] Critical Error in Proctor Loop: {e}")
                if self.logger:
                     self.logger.log("ERROR", details=str(e))
                time.sleep(1) 
            
    def stop(self):
        self.running = False
        if self.audio_monitor:
            try:
                self.audio_monitor.stop()
            except Exception as e:
                print(f"[THREAD] audio stop: {e}")
        if self.net_monitor:
            try:
                self.net_monitor.stop_monitoring()
            except Exception as e:
                print(f"[THREAD] net stop: {e}")
        obj = getattr(self, "obj_detector", None)
        if obj and hasattr(obj, "close"):
            try:
                obj.close()
            except Exception:
                pass
        lip = getattr(self, "lip_reader", None)
        if lip and hasattr(lip, "close"):
            try:
                lip.close()
            except Exception:
                pass
        cam = getattr(self, "webcam", None)
        if cam is not None and hasattr(cam, "release"):
            try:
                cam.release()
            except Exception as e:
                print(f"[THREAD] webcam release: {e}")
            self.webcam = None
        self.wait()