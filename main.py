import os
import cv2
import sys
import subprocess

from camera.webcam import Webcam
from face.face_detect import FaceDetector
from face.face_mesh import FaceMeshDetector
from gaze.head_pose import HeadPoseEstimator
from gaze.gaze_estimator import GazeEstimator
from rules.rule_engine import RuleEngine
from utils.fps import FPSCounter
from screen.focus_check import FocusMonitor
from screen.monitor_check import MonitorCheck
from network.network_monitor import NetworkMonitor
from network.advanced_monitor import AdvancedNetworkMonitor
from network.server import ProctorServer
from utils.logger import EventLogger
from analysis.session_analyzer import SessionAnalyzer
from ai.audio import AudioMonitor
from ai.lip_reading import LipFeatureExtractor
from ai.confidence_engine import ConfidenceEngine

def main():
    # -------------------------------
    # Initialization
    # -------------------------------
    # -------------------------------
    # Start Safe Browser (Subprocess)
    # -------------------------------
    script_dir = os.path.dirname(os.path.abspath(__file__))
    browser_script = os.path.join(script_dir, "screen", "safe_browser.py")
    
    if os.path.exists(browser_script):
        # Pass stdout/stderr to main console so user sees errors
        browser_process = subprocess.Popen([sys.executable, browser_script])
        print(f"[INFO] Secure Browser Launched (PID: {browser_process.pid})")
    else:
        print(f"[ERROR] Browser script not found at: {browser_script}")
        browser_process = None
    
    webcam = Webcam(camera_id=0, width=640, height=480)
    face_detector = FaceDetector(confidence=0.6)
    face_mesh = FaceMeshDetector()
    head_pose = HeadPoseEstimator()
    gaze_estimator = GazeEstimator()
    rule_engine = RuleEngine()
    focus_monitor = FocusMonitor()
    monitor_check = MonitorCheck()
    network_monitor = NetworkMonitor()
    advanced_network = AdvancedNetworkMonitor()
    advanced_network.start_monitoring() # This starts its own thread internally now
    
    # New AI Modules
    audio_monitor = AudioMonitor()
    audio_monitor.start()
    
    lip_extractor = LipFeatureExtractor()
    confidence_engine = ConfidenceEngine()
    
    # Network Server for Phone
    server = ProctorServer(port=5000)
    server.start()

    fps_counter = FPSCounter()
    logger = EventLogger() # Defaults to data/dataset/{uuid}

    yaw_baseline = None
    frame_count = 0
    current_network_warnings = []
    network_logs = []

    print("[INFO] AI Proctoring System Started")

    # -------------------------------
    # Main Loop
    # -------------------------------
    while webcam.is_opened():
        frame = webcam.read()
        if frame is None:
            break

        frame_count += 1

        # -------------------------------
        # Security Checks
        # -------------------------------
        # Security Checks
        # -------------------------------
        if webcam.check_tampering(frame):
            logger.log("VIOLATION", "Camera Tampering / Freezing Detected", frame=frame)
            cv2.putText(frame, "TAMPERING DETECTED", (10, 250), 
                       cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 3)

        # Focus / Screen Monitoring
        is_focus_lost, active_window = focus_monitor.check_focus()
        if is_focus_lost:
            logger.log("VIOLATION", f"Focus Lost: Active Window='{active_window}'", frame=frame)
            cv2.putText(frame, "FOCUS LOST", (10, 280), 
                       cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 3)

        # Multi-Monitor Check (Throttle: check every 100 frames to save resource)
        if frame_count % 100 == 0:
            is_multi_monitor, monitor_count = monitor_check.check_monitors()
            if is_multi_monitor:
                logger.log("VIOLATION", f"Multiple Monitors Detected: {monitor_count}")
                # We persist this warning for a bit or just log it
                # For now just logging is sufficient as this is a hardware state

        # Network Check (Throttle: check every 100 frames)
        if frame_count % 100 == 0:
            # Pass None as allowed_ssid for now, or get it from config
            is_compliant, net_msg = network_monitor.check_compliance(allowed_ssid=None)
            if not is_compliant:
                 logger.log("VIOLATION", f"Network Violation: {net_msg}")

        # Always display network status
        current_ssid = network_monitor.cached_ssid or network_monitor.get_wifi_ssid()
        cv2.putText(frame, f"Net: {current_ssid}", (450, 30), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)

        # Traffic & Connection Monitoring (Every 1 second)
        if frame_count % 30 == 0:
            ul_speed, dl_speed = network_monitor.get_traffic_stats()
            conn_count, remote_ips = network_monitor.get_active_connections()

            # Display Stats
            cv2.putText(frame, f"UL: {ul_speed}KB/s DL: {dl_speed}KB/s Conn: {conn_count}", 
                       (10, 460), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
            
            # Simple Heuristics for Violations
            # 1. High Uplink (Screen sharing / Streaming?)
            if ul_speed > 500: 
                logger.log("VIOLATION", f"High Upload Traffic: {ul_speed} KB/s")
                cv2.putText(frame, "HIGH TRAFFIC", (450, 60), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

            # 2. Too many connections (P2P / Background apps)
            if conn_count > 50:
                logger.log("VIOLATION", f"High Connections: {conn_count} IPs:{remote_ips}")
                
            # Advanced Monitor (Process & Packet Level)
            adv_warnings = advanced_network.scan_active_connections()
            current_network_warnings = adv_warnings
            
            for warn in adv_warnings:
                logger.log("VIOLATION", f"[ADV-NET] {warn}")
                
            sniff_alerts = advanced_network.get_sniffing_alerts()
            for alert in sniff_alerts:
                logger.log("VIOLATION", f"[SNIFF] {alert}")
            
            # Fetch latest logs for display
            network_logs = advanced_network.get_recent_logs()
                
        # Always Display Persistent Network Warnings
        if current_network_warnings:
             cv2.putText(frame, "SUSPICIOUS APP DETECTED", (400, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
             # Show first warning details
             cv2.putText(frame, current_network_warnings[0][:40] + "...", (400, 115), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)

        # Draw Network Activity Log (Bottom Left above status)
        # Background box
        h, w, _ = frame.shape
        cv2.rectangle(frame, (10, h - 160), (350, h - 10), (0, 0, 0), -1) # Black BG
        cv2.putText(frame, "LIVE NETWORK TRAFFIC", (15, h - 145), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
        
        y_offset = h - 125
        for log in list(network_logs)[-5:]: # Show last 5
            color = (0, 255, 0)
            if "Suspicious" in log or "Blacklisted" in log:
                color = (0, 0, 255)
            elif "New Conn" in log:
                color = (200, 200, 0)
                
            # Truncate length
            display_text = log[:45]
            cv2.putText(frame, display_text, (15, y_offset), cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1)
            y_offset += 20

        # -------------------------------
        # Face detection
        # -------------------------------
        faces = face_detector.detect(frame)
        face_count = len(faces)

        for (x, y, w, h) in faces:
            cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)

        # Face-based rules
        violations = rule_engine.evaluate_faces(face_count)
        for v in violations:
            logger.log("VIOLATION", v, frame=frame)

        # -------------------------------
        # Multimodal AI Analysis (Audio + Visual)
        # -------------------------------
        
        # 1. Audio / VAD
        vad_prob = audio_monitor.get_voice_activity()
        
        # 2. Visual Features (Head Pose + Lip Reading)
        current_yaw = 0
        current_pitch = 0
        is_lip_moving = False
        lip_mar = 0.0
        lip_prob = 0.0
        is_looking_away = False
        
        landmarks = face_mesh.get_landmarks(frame)
        if landmarks:
            # Head Pose
            yaw, pitch = head_pose.estimate(landmarks, frame.shape)
            if yaw is not None:
                current_yaw = yaw
                current_pitch = pitch
                
                if yaw_baseline is None:
                    yaw_baseline = yaw
                
                relative_yaw = yaw - yaw_baseline
                
                # Check for looking away
                if abs(relative_yaw) > 30:
                    is_looking_away = True

            # Gaze
            eye_looking_away, gaze_scores = gaze_estimator.estimate(landmarks, frame.shape)
            gaze_ratio_h = gaze_scores['h_ratio']
            gaze_ratio_v = gaze_scores['v_ratio']
            
            if eye_looking_away:
                is_looking_away = True
                
            # Lip Reading (CNN+LSTM or Heuristic)
            lip_prob, lip_mar = lip_extractor.process(frame, landmarks)
            is_lip_moving = lip_prob > 0.5


        # 3. Confidence Scoring Engine
        conf_result = confidence_engine.evaluate(
            vad_prob=vad_prob,
            lip_prob=lip_prob, 
            head_yaw=current_yaw,
            head_pitch=current_pitch,
            face_count=face_count
        )
        
        status = conf_result["status"]
        score = conf_result["score"]
        reasons = conf_result["reasons"]
        
        # -------------------------------
        # Display & Visual Feedback
        # -------------------------------
        
        # Draw status background
        color_map = {
            "SAFE": (0, 255, 0),
            "WARNING": (0, 255, 255),
            "FLAG": (0, 0, 255)
        }
        status_color = color_map.get(status, (0, 255, 0))
        
        # VAD & Lip IO
        cv2.putText(frame, f"VAD: {vad_prob:.2f}", (10, 150), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
        cv2.putText(frame, f"Lip: {'Moving' if is_lip_moving else 'Still'} (MAR:{lip_mar:.2f})", (10, 170), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
        
        # Main Status Box
        cv2.rectangle(frame, (400, 400), (630, 470), (50, 50, 50), -1)
        cv2.putText(frame, f"STATUS: {status}", (410, 425), cv2.FONT_HERSHEY_SIMPLEX, 0.7, status_color, 2)
        cv2.putText(frame, f"Conf Score: {score:.2f}", (410, 450), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1)
        
        # Show Reasons
        for i, reason in enumerate(reasons[:2]): # Show top 2 reasons
            cv2.putText(frame, reason, (10, 350 + (i*25)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

        if status == "FLAG":
             logger.log("VIOLATION", f"High Confidence Anomaly: {reasons}", frame=frame)

        # -------------------------------
        # Metrics Logging (for AI Training)
        # -------------------------------
        if frame_count % 5 == 0:
            metrics = {
                "face_count": face_count,
                "fps": round(fps_counter.fps, 1) if hasattr(fps_counter, 'fps') else 0,
                "gaze_h": gaze_ratio_h if 'gaze_ratio_h' in locals() else -1,
                "gaze_v": gaze_ratio_v if 'gaze_ratio_v' in locals() else -1,
                "head_yaw": relative_yaw if 'relative_yaw' in locals() else -1,
                "is_looking_away": is_looking_away,
                "vad_prob": vad_prob,
                "lip_mar": lip_mar,
                "lip_moving": is_lip_moving,
                "conf_score": score,
                "status": status
            }
            logger.log("METRICS", metrics, frame=frame)

        # -------------------------------
        # FPS & overlays
        # -------------------------------
        fps = fps_counter.update()

        cv2.putText(frame, f"Faces: {face_count}", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

        cv2.putText(frame, f"FPS: {fps}", (10, 60),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

        if violations:
            cv2.putText(frame, f"Warning: {violations[-1]}", (10, 90),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

        # -------------------------------
        # Display
        # -------------------------------
        cv2.imshow("AI Proctoring - Laptop", frame)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    # -------------------------------
    # Cleanup
    # -------------------------------
    server.stop()
    audio_monitor.stop()
    advanced_network.stop_monitoring()
    
    # Close Browser
    if browser_process:
        try:
            browser_process.terminate()
            print("[INFO] Secure Browser Closed")
        except:
            pass
        
    webcam.release()
    cv2.destroyAllWindows()
    print("[INFO] Proctoring Session Ended")
    
    # Run Final Analysis
    print("[INFO] Generating Final Report...")
    analyzer = SessionAnalyzer(logger.session_dir)
    analyzer.analyze()


if __name__ == "__main__":
    main()
