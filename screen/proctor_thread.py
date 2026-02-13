from PyQt5.QtCore import QThread, pyqtSignal, Qt
from PyQt5.QtGui import QImage
import cv2
import time
import numpy as np

# Import all AI & Monitoring Modules
try:
    from face.face_detect import FaceDetector
    from face.face_mesh import FaceMeshDetector
    from gaze.head_pose import HeadPoseEstimator
    from gaze.gaze_estimator import GazeEstimator
    from rules.rule_engine import RuleEngine
    from screen.focus_check import FocusMonitor
    from screen.monitor_check import MonitorCheck
    from network.advanced_monitor import AdvancedNetworkMonitor
    from camera.webcam import Webcam
    
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
    
    def __init__(self, server=None, dev_mode=False, logger=None):
        super().__init__()
        self.server = server
        self.dev_mode = dev_mode
        self.logger = logger
        self.running = True
        
        # Placeholders
        self.audio_monitor = None
        self.obj_detector = None
        self.face_detector = None
        self.mesh_detector = None
        self.head_pose = None
        self.gaze_estimator = None
        self.rule_engine = None
        self.focus_monitor = None
        self.monitor_check = None
        self.net_monitor = None

    def _init_ai_components(self):
        if not AI_AVAILABLE: return
        try:
            print("[THREAD] Initializing AI Components...")
            # 1. Audio
            try:
                from ai.audio import AudioMonitor
                self.audio_monitor = AudioMonitor()
                self.audio_monitor.start()
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
            
            # 4. System
            self.focus_monitor = FocusMonitor()
            self.monitor_check = MonitorCheck()
            self.net_monitor = AdvancedNetworkMonitor()
            self.net_monitor.start_monitoring()
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

        webcam = None
        if not self.dev_mode and AI_AVAILABLE:
             try:
                 webcam = Webcam() # Use custom wrapper
                 print(f"[THREAD] Webcam Initialized: {webcam.get_signature()}")
             except Exception as e:
                 print(f"[THREAD] Webcam Init Failed: {e}")
                 if self.logger:
                     self.logger.log("ERROR", f"Webcam Init Failed: {e}")
        
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
                net_status = {"connected": False, "ip": "N/A", "audio_diff": False, "logs": []}
                
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

                # B. Object Detection (YOLO - Server Side)
                if self.obj_detector and frame_count % 30 == 0:
                    detections, _ = self.obj_detector.detect(phone_frame)
                    if detections:
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
                if webcam and webcam.is_opened():
                    frame = webcam.read()
                
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
                
                # Only run AI if webcam actually works and is not dummy
                if webcam and webcam.is_opened():
                     # Tamper Check
                    if webcam.check_tampering(frame):
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

                                    # Emit 3D Gaze Viz (combining webcam pose + phone view)
                                    direction = gaze_data.get('direction', 'CENTER') if gaze_data else 'CENTER'
                                    is_violation = is_head_away or is_gaze_away
                                    try:
                                        self.gaze_update.emit(
                                            float(yaw), float(pitch),
                                            direction, is_violation,
                                            self.phone_face_detected
                                        )
                                    except: pass

                        # c. Face Count Rules
                        msgs = self.rule_engine.evaluate_faces(face_count)
                        for m in msgs:
                            net_status["logs"].append(f"AI: {m}")
                            if self.logger: self.logger.log("VIOLATION", m, frame)
                    
                    # d. Focus Check
                    if self.focus_monitor and frame_count % 30 == 0:
                        is_lost, title = self.focus_monitor.check_focus()
                        if is_lost:
                            msg = f"Focus Lost: {title}"
                            net_status["logs"].append(msg)
                            if self.logger: self.logger.log("VIOLATION", msg)
                    
                    # e. Monitor Check
                    if self.monitor_check and frame_count % 100 == 0:
                        is_multi, count = self.monitor_check.check_monitors()
                        if is_multi:
                            msg = f"Multi-Monitor: {count} screens"
                            net_status["logs"].append(msg)
                            if self.logger: self.logger.log("VIOLATION", msg)
                            
                    # f. Network Alerts
                    if self.net_monitor and frame_count % 60 == 0:
                        alerts = self.net_monitor.get_sniffing_alerts()
                        for a in alerts:
                            net_status["logs"].append(f"NET: {a}")
                            if self.logger: self.logger.log("VIOLATION", a)

                # Emit Frame (Whether it's real or error frame)
                try:
                    rgb_image = cv2.cvtColor(annotated_frame, cv2.COLOR_BGR2RGB)
                    h, w, ch = rgb_image.shape
                    qt_image = QImage(rgb_image.data, w, h, ch*w, QImage.Format_RGB888).copy()
                    self.image_update.emit(qt_image)
                except Exception as e:
                    print(f"[THREAD] Frame Emit Error: {e}")

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
            self.audio_monitor.stop()
        if self.net_monitor:
             self.net_monitor.stop_monitoring()
        self.wait()

