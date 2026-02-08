# 🧠 AI-Based Multi-Modal Proctoring System

## 1️⃣ CORE IDEA
Online exams should be monitored using **multiple cameras**, **controlled internet access**, and **time-based AI rules**.
The system enforces:
1. **Visual Integrity**: Candidate behavior (Head pose, Gaze, Person detection).
2. **Network Integrity**: Connection source (Phone Hotspot) and device count.
3. **System Integrity**: Laptop environment (Alt-Tab, Focus loss, VM detection).

## 2️⃣ DEVICE SETUP
### 🖥️ Laptop (Primary)
- **Role**: Exam Interface, AI Processing Hub.
- **Sensors**: Webcam (Face/Gaze), Screen (Focus/Window).
- **Tasks**: Run `main.py`, aggregate signals, log events.

### 📱 Phone (Control & Monitor)
- **Role**: Trusted Anchor, Internet Source.
- **Sensors**: Rear Cam (Desk/Hands), Front Cam (Room), Network (Hotspot telemetry).
- **Tasks**: Stream video segments to laptop, report network status.

## 3️⃣ CAMERA ARCHITECTURE
1. **Laptop Front**: Face, Attention, Gaze.
2. **Phone Rear**: Desk, Hands, Phone usage.
3. **Phone Front**: Room view, Second person.

## 4️⃣ DISTRIBUTED COMPUTATION
- **Laptop**: Heavy lifting (Face Mesh, Gaze, Fusion Logic).
- **Phone**: Lightweight (Motion detection, Network stats).

## 5️⃣ NETWORK CONTROL
- **Rule**: Exam only valid if connected to Phone Hotspot.
- **Metrics**: Device count, Data spikes (NO packet sniffing).

## 6️⃣ AI DECISION LOGIC
- **Fusion**: Combine signals (e.g., Phone detected + Gaze away = Cheating).
- **Temporal**: No instant flags. Violations must persist > Threshold.

## 7️⃣ RULE ENGINE
- Centralized logic receiving inputs from all sensors.
- Outputs `VIOLATION` or `WARNING` with confidence scores.

## 8️⃣ SYSTEM CHECKS (Laptop)
- **Focus Loss**: Alt-Tab detection.
- **Multi-Monitor**: Detect HDMI/External displays.
- **Virtual Camera**: Signature analysis (Implemented).

## 9️⃣ PRIVACY
- **Local Processing**: No video upload.
- **Logs**: JSONL format for audit/training (Implemented).

## 🔟 OUTPUT
- Real-time interaction.
- Structured training data for future AI models.
