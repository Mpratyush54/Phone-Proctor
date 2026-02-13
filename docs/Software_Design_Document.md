# Phone-Proctor — Software Design Document
### Author: Pratyush Mishra
### Version: 1.0 | February 2026

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [System Architecture](#2-system-architecture)
3. [Network Layer — Discovery & Communication](#3-network-layer--discovery--communication)
4. [Camera & Video Pipeline](#4-camera--video-pipeline)
5. [Audio Pipeline](#5-audio-pipeline)
6. [AI & Detection Engine](#6-ai--detection-engine)
7. [Data Logging & Storage](#7-data-logging--storage)
8. [Secure Browser (UI)](#8-secure-browser-ui)
9. [Session Analysis & Reporting](#9-session-analysis--reporting)
10. [ML Training Pipeline](#10-ml-training-pipeline)
11. [Security Considerations](#11-security-considerations)
12. [Future Plans & Vision](#12-future-plans--vision)

---

## 1. Project Overview

### 1.1 What is Phone-Proctor?

Phone-Proctor is an **AI-powered exam proctoring system** that uses a student's **PC webcam** and **phone camera** simultaneously to detect cheating behavior during online exams. Unlike commercial proctoring solutions that rely on simple rule-based checks, Phone-Proctor uses:

- **Multi-modal AI** — Computer vision, audio analysis, and behavioral pattern detection
- **Unsupervised Machine Learning** — Learns what "normal" looks like without labeled data
- **Multi-camera fusion** — Combines PC webcam + phone camera for full coverage
- **Real-time processing** — All detections happen live during the exam

### 1.2 Why This Approach?

| Problem | Traditional Proctoring | Our Approach |
|---------|----------------------|--------------|
| Single camera blind spots | Webcam only, side cheating possible | **Dual camera** (PC + Phone) covers all angles |
| Easy to game rigid rules | Fixed thresholds (look away > 3s = flag) | **AI learns baseline** per student, adapts |
| No audio intelligence | Ignores audio or uses basic VAD | **Audio analysis** detects external voices vs self-speech |
| Privacy concerns with cloud | Streams video to cloud servers | **Fully local processing** — nothing leaves the PC |
| Expensive licenses | $10-30 per student per exam | **Free, open-source** |
| False positives | Flags everything | **Unsupervised learning** separates real anomalies from normal variation |

### 1.3 Technology Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| **Backend** | Python 3.13 | Main application logic |
| **UI Framework** | PyQt5 + QtWebEngine | Secure browser & dashboard |
| **Frontend** | HTML/CSS/JavaScript | Dashboard interface |
| **Mobile App** | React Native (Expo) | Phone camera & sensor streaming |
| **Networking** | WebSocket + WebRTC + TCP + UDP | Multi-protocol communication |
| **Computer Vision** | OpenCV + MediaPipe + YOLOv8 | Face, gaze, object detection |
| **Machine Learning** | scikit-learn (Isolation Forest) | Unsupervised anomaly detection |
| **Audio** | PyAudio + SpeechRecognition + scipy | Voice detection & analysis |

---

## 2. System Architecture

### 2.1 High-Level Architecture

```
┌───────────────────────────────────────────────────────────────────────────┐
│                         STUDENT'S PC                                     │
│                                                                          │
│  ┌──────────────┐   ┌───────────────┐   ┌──────────────────────────┐    │
│  │   Webcam      │──>│ ProctorThread │──>│   Dashboard (PyQt5)      │    │
│  │   (OpenCV)    │   │               │   │   - Camera feeds         │    │
│  └──────────────┘   │  AI Pipeline:  │   │   - 3D head viz          │    │
│                      │  - FaceDetect  │   │   - Status cards         │    │
│                      │  - GazeEstim   │   │   - Violation log        │    │
│  ┌──────────────┐   │  - HeadPose    │   └──────────────────────────┘    │
│  │  Phone Feed   │──>│  - ObjectDet   │                                   │
│  │  (WebRTC)     │   │  - Audio       │   ┌──────────────────────────┐    │
│  └──────────────┘   │  - Confidence   │──>│   EventLogger            │    │
│                      │  - Rules        │   │   - events.jsonl         │    │
│  ┌──────────────┐   └───────────────┘   │   - images/*.jpg          │    │
│  │  Phone Sensors│                       │   - audio/*.wav           │    │
│  │  (TCP)        │──> Telemetry Data     └──────────────────────────┘    │
│  └──────────────┘                                                        │
│                                                                          │
│  ┌──────────────┐   ┌───────────────┐   ┌──────────────────────────┐    │
│  │  Focus Check  │──>│  Rule Engine   │──>│   Session Analyzer       │    │
│  │  (Win32 API)  │   │               │   │   - FINAL_REPORT.md      │    │
│  └──────────────┘   └───────────────┘   │   - ML anomaly scoring   │    │
│                                          └──────────────────────────┘    │
│                                                                          │
│  ┌──────────────┐                                                        │
│  │ Network Mon   │──> Packet-level traffic analysis                      │
│  │ (Raw Sockets) │                                                       │
│  └──────────────┘                                                        │
└───────────────────────────────────────────────────────────────────────────┘
         │                    │
         │ WebSocket :5000    │ UDP :5001
         │ WebRTC (SDP/ICE)   │ TCP :5001
         │                    │
┌────────▼────────────────────▼─────────────────────────────────────────────┐
│                         STUDENT'S PHONE                                   │
│                                                                          │
│  ┌──────────────┐   ┌───────────────┐   ┌──────────────────────────┐    │
│  │  Camera       │──>│  WebRTC        │──>│  WebSocket Client        │    │
│  │  (CameraKit)  │   │  Video/Audio   │   │  - Commands              │    │
│  └──────────────┘   │  Stream        │   │  - Status updates        │    │
│                      └───────────────┘   └──────────────────────────┘    │
│  ┌──────────────┐                                                        │
│  │  Sensors      │──> TCP Telemetry (accelerometer, proximity, etc.)     │
│  │  (Expo)       │                                                       │
│  └──────────────┘                                                        │
└───────────────────────────────────────────────────────────────────────────┘
```

### 2.2 Directory Structure & Module Map

```
Phone-Proctor/
├── main.py                    # Entry point — starts everything
│
├── network/                   # All networking (PC <-> Phone)
│   ├── server.py              #   WebSocket server (port 5000)
│   ├── server_discovery.py    #   UDP broadcast discovery (port 5001)
│   ├── tcp_server.py          #   TCP sensor telemetry (port 5001)
│   ├── webrtc_manager.py      #   WebRTC video/audio handler
│   ├── network_monitor.py     #   OS-level network traffic analysis
│   └── advanced_monitor.py    #   Deep packet inspection
│
├── screen/                    # UI & Desktop monitoring
│   ├── safe_browser.py        #   PyQt5 secure browser window
│   ├── proctor_thread.py      #   Main AI processing loop (QThread)
│   └── focus_check.py         #   Win32 API focus monitoring
│
├── ai/                        # AI & ML models
│   ├── confidence_engine.py   #   Multi-modal confidence scoring
│   ├── object_detector.py     #   YOLOv8 restricted item detection
│   ├── ml_model.py            #   Isolation Forest anomaly detector
│   ├── cheat_predictor.py     #   Multi-modal cheat probability model
│   ├── audio.py               #   Audio monitoring & transcription
│   ├── lip_reading.py         #   Lip movement detection
│   └── anomaly_detector.py    #   Statistical anomaly detection
│
├── face/                      # Face processing
│   ├── face_detect.py         #   Face detection (MediaPipe)
│   └── face_mesh.py           #   468-landmark face mesh
│
├── gaze/                      # Eye & head tracking
│   ├── gaze_estimator.py      #   3D gaze direction estimation
│   └── head_pose.py           #   Head pose from solvePnP
│
├── eyes/                      # Eye-specific analysis
│
├── fusion/                    # Multi-sensor fusion
│   └── score_fusion.py        #   Combine multi-modal scores
│
├── rules/                     # Rule engine
│   ├── rule_engine.py         #   Hard-coded violation rules
│   └── thresholds.py          #   Configurable thresholds
│
├── camera/                    # Webcam management
│   └── webcam.py              #   OpenCV webcam capture
│
├── utils/                     # Utilities
│   └── logger.py              #   Structured event logger (JSONL)
│
├── analysis/                  # Post-session analysis
│   └── session_analyzer.py    #   Final report generation
│
├── assets/                    # Frontend assets
│   └── dashboard.html         #   Dashboard UI (HTML/CSS/JS)
│
├── config/                    # Configuration
│
├── data/                      # Session data storage
│   ├── dataset/               #   Current sessions
│   ├── dataset.old/           #   Historical sessions
│   └── audio/                 #   Audio recordings
│
├── models/                    # Saved ML models
│   ├── cheat_model.pkl        #   Supervised model
│   └── cheat_model_unsupervised.pkl  # Unsupervised model
│
├── train_model_concept.py     # Presentation training pipeline
│
└── docs/                      # Documentation
    ├── Isolation_Forest_Documentation.md
    └── Software_Design_Document.md     # (this file)
```

### 2.3 Startup Sequence

When `main.py` runs, the system starts in this exact order:

```
1. main.py
   │
   ├─> ProctorServer(port=5000).start()
   │     ├─> WebSocket server on :5000  (background thread)
   │     ├─> TCP telemetry on :5001     (asyncio task)
   │     └─> WebRTCManager initialized  (awaits SDP offer)
   │
   ├─> EventLogger()
   │     └─> Creates data/dataset/{session_id}/
   │         ├── events.jsonl
   │         └── images/
   │
   ├─> run_browser_app()
   │     └─> SafeBrowser (PyQt5 QMainWindow)
   │         └─> Loads dashboard.html
   │
   ├─> ProctorThread.start()
   │     ├─> FaceDetector (MediaPipe)
   │     ├─> GazeEstimator
   │     ├─> ObjectDetector (YOLOv8)
   │     ├─> AudioMonitor (PyAudio)
   │     ├─> ConfidenceEngine
   │     ├─> RuleEngine
   │     ├─> FocusMonitor (Win32)
   │     └─> NetworkMonitor
   │
   └─> app.exec_()  (Qt event loop - BLOCKING)
        └─> On exit: stop() everything + generate FINAL_REPORT.md
```

---

## 3. Network Layer — Discovery & Communication

### 3.1 The Discovery Problem

When a student opens the phone app, it needs to find the PC on the local network **automatically** — no IP addresses to type manually. This is critical because:

- Students don't know their PC's IP address
- IP addresses change between Wi-Fi networks
- Hotspot mode assigns different subnet ranges

### 3.2 UDP Broadcast Discovery Protocol

We use **UDP broadcast** to solve this problem. UDP supports sending a packet to every device on the local network simultaneously.

```
┌──────────────────┐                        ┌──────────────────┐
│   PHONE           │                        │   PC              │
│   (React Native)  │                        │   (Python)        │
└──────┬───────────┘                        └──────┬───────────┘
       │                                            │
       │  1. Broadcast "PROCTOR_DISCOVER"           │
       │    to 255.255.255.255:5001 (UDP)           │
       │───────────────────────────────────────────>│
       │                                            │
       │                                2. Receives │
       │                                   packet   │
       │                                            │
       │  3. Unicast "PROCTOR_HERE"                 │
       │    back to phone's IP (UDP)                │
       │<───────────────────────────────────────────│
       │                                            │
       │  4. Phone now knows PC's IP!               │
       │     Connects via WebSocket ws://ip:5000    │
       │───────────────────────────────────────────>│
       │                                            │
```

#### How UDP Broadcast Works

```python
# Phone sends (React Native / UDP):
socket.send("PROCTOR_DISCOVER", "255.255.255.255", 5001)
#                                ^^^^^^^^^^^^^^^^
#                                Broadcast address = ALL devices on subnet

# PC listens (Python):
sock = socket.socket(AF_INET, SOCK_DGRAM)
sock.setsockopt(SOL_SOCKET, SO_BROADCAST, 1)
sock.bind(('0.0.0.0', 5001))
data, addr = sock.recvfrom(1024)  # Receives from phone
# addr = ('192.168.1.45', 54321)  -> phone's IP!
sock.sendto("PROCTOR_HERE", addr)  # Reply directly to phone
```

#### Dual-Mode Discovery

The PC runs **two discovery threads**:

| Thread | Role | Why |
|--------|------|-----|
| **Listener** | Waits for phone's "PROCTOR_DISCOVER" broadcasts | Phone initiates (standard pattern) |
| **Announcer** | Periodically broadcasts "PROCTOR_ANNOUNCE" every 3s | PC reaches phone even if phone can't broadcast (mobile data, hotspot NAT) |

The announcer sends to multiple subnet broadcast addresses to handle different network configurations:

```python
targets = [
    '255.255.255.255',     # Generic broadcast
    '192.168.1.255',       # Home network /24
    '192.168.0.255',       # Router default
    '172.20.10.15',        # iPhone hotspot
    '192.168.43.255',      # Android hotspot
]
```

### 3.3 WebSocket Connection (Port 5000)

After discovery, the phone connects via **WebSocket** for reliable, bidirectional communication:

```
Phone ──── WebSocket (ws://pc_ip:5000) ──── PC

Messages (JSON):
  Phone → PC:
    { "type": "SENSOR_DATA", "data": { "accel": {...}, "gyro": {...} } }
    { "type": "WEBRTC_OFFER", "data": { "sdp": "...", "type": "offer" } }
    { "type": "STATUS", "data": { "battery": 85, "locked": true } }

  PC → Phone:
    { "type": "START_STREAM" }
    { "type": "LOCKDOWN", "data": { "enabled": true } }
    { "type": "WEBRTC_ANSWER", "data": { "sdp": "...", "type": "answer" } }
```

#### Why WebSocket, not HTTP?

| Feature | HTTP | WebSocket |
|---------|------|-----------|
| Direction | Request → Response only | **Bidirectional** |
| Latency | New connection each time | **Persistent connection** |
| Data Overhead | HTTP headers each time (~800 bytes) | **2-10 bytes framing** |
| Real-time? | Polling (wasteful) | **Push-based** |

### 3.4 WebRTC Video/Audio Stream

For **low-latency video/audio** streaming from phone to PC, we use WebRTC:

```
┌──────────┐        SDP Offer/Answer via WebSocket        ┌──────────┐
│  Phone    │────────────────────────────────────────────>│  PC       │
│  Camera   │                                             │  aiortc   │
│           │<────────────────────────────────────────────│           │
│           │                                             │           │
│           │        Direct P2P Video/Audio Stream         │           │
│           │ ═══════════════════════════════════════════>│           │
│           │          (RTP over UDP, ~30fps)              │           │
└──────────┘                                             └──────────┘
```

#### WebRTC Signaling Flow

```
1. Phone creates RTCPeerConnection
2. Phone calls createOffer() → generates SDP (Session Description Protocol)
3. Phone sends SDP Offer via WebSocket to PC
4. PC (aiortc) receives offer, creates answer
5. PC sends SDP Answer back via WebSocket
6. ICE candidates are exchanged (network path negotiation)
7. Direct peer-to-peer connection established
8. Video frames flow: Phone camera → RTP packets → PC
9. PC decodes frames via av library → numpy arrays → OpenCV processing
```

#### Why WebRTC, not MJPEG/WebSocket frames?

| Feature | WebSocket Frames | WebRTC |
|---------|-----------------|--------|
| Latency | 100-500ms (encode + send + decode) | **< 50ms** (hardware codec) |
| Quality | Re-encoded JPEG each frame | **VP8/H.264 codec** (efficient) |
| Audio | Separate implementation needed | **Built-in audio track** |
| Bandwidth | ~2-5 Mbps (raw JPEG) | **0.5-1 Mbps** (compressed) |
| Adaptive | No | **Yes** (adjusts to bandwidth) |

### 3.5 TCP Telemetry (Port 5001)

For **reliable sensor data** (accelerometer, proximity, magnetometer), we use TCP:

```python
# Phone sends newline-delimited JSON over TCP:
{"type": "accelerometer", "x": 0.1, "y": 9.8, "z": 0.3, "ts": 1707000000}
{"type": "proximity",     "near": false, "ts": 1707000001}
{"type": "light",         "lux": 250, "ts": 1707000002}
```

**Why TCP for sensors but WebRTC for video?**
- Sensor readings are small (~100 bytes) and require **guaranteed delivery**
- TCP ensures every reading arrives (no packet loss)
- Video frames can tolerate occasional drops (WebRTC handles this)

---

## 4. Camera & Video Pipeline

### 4.1 Dual Camera Architecture

```
Camera Source 1: PC Webcam                Camera Source 2: Phone Camera
┌─────────────────────┐                   ┌─────────────────────┐
│ cv2.VideoCapture(0)  │                   │ React Native Camera  │
│ - 640x480 @ 30fps    │                   │ - CameraKit          │
│ - BGR numpy array     │                   │ - 640x480 @ 30fps    │
└──────────┬──────────┘                   └──────────┬──────────┘
           │                                          │
           │                                    WebRTC Stream
           │                                          │
           ▼                                          ▼
┌─────────────────────────────────────────────────────────────┐
│                      ProctorThread.run()                     │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  WEBCAM PROCESSING (every frame, ~30fps)             │    │
│  │                                                      │    │
│  │  1. FaceDetector.detect(frame)                       │    │
│  │     → face_count, landmarks, face_bbox               │    │
│  │                                                      │    │
│  │  2. GazeEstimator.estimate(landmarks)                │    │
│  │     → yaw, pitch, gaze_direction                     │    │
│  │                                                      │    │
│  │  3. ObjectDetector.detect(frame)                     │    │
│  │     → [("phone", 0.92), ("book", 0.85)]             │    │
│  │                                                      │    │
│  │  4. LipReading.predict(mouth_roi)                    │    │
│  │     → lip_movement_probability                       │    │
│  │                                                      │    │
│  │  5. ConfidenceEngine.evaluate(all_signals)           │    │
│  │     → status: "SAFE" | "WARNING" | "FLAG"            │    │
│  │     → score: 0.0 - 1.0                               │    │
│  │     → reasons: ["Looking Away (Yaw: 35°)"]           │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  PHONE FRAME PROCESSING                              │    │
│  │                                                      │    │
│  │  - Received via WebRTC (server._on_webrtc_frame)     │    │
│  │  - Additional face detection for multi-face check    │    │
│  │  - Side-angle coverage (catches blind spots)         │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  OUTPUTS (via PyQt Signals)                          │    │
│  │                                                      │    │
│  │  image_update → Dashboard webcam feed                │    │
│  │  phone_update → Dashboard phone feed                 │    │
│  │  gaze_update  → 3D head visualization                │    │
│  │  status_update→ Status cards + violation log         │    │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

### 4.2 Face Detection Pipeline

```
Raw Frame (640x480 BGR)
  │
  ▼
MediaPipe Face Detection
  │
  ├── No face → LOG: "No Face Detected" (violation)
  ├── 1 face  → Continue to landmark extraction
  └── 2+ faces → LOG: "Multiple Faces Detected" (violation)
  │
  ▼
MediaPipe Face Mesh (468 landmarks)
  │
  ├── Landmarks → Head Pose Estimation (solvePnP)
  │                  → yaw (left/right rotation, degrees)
  │                  → pitch (up/down tilt, degrees)
  │
  ├── Eye Landmarks → Eye Aspect Ratio (EAR)
  │                     → eye openness metric
  │                     → drowsiness detection
  │
  └── Mouth Landmarks → Lip Movement Detection
                          → speaking probability
```

### 4.3 Object Detection (YOLOv8)

```
Raw Frame
  │
  ▼
YOLOv8 Nano (yolov8n.pt, 6.5MB)
  │
  ▼
Detected Objects with confidence scores
  │
  ├── Restricted Items (flagged):
  │     - cell phone (class 67)
  │     - book (class 73)
  │     - laptop (class 63) [if count > 1, extra laptop]
  │
  └── Allowed Items (filtered):
        - person (expected)
        - chair, desk (environment)
```

---

## 5. Audio Pipeline

### 5.1 Dual Audio Sources

```
Source 1: PC Microphone               Source 2: Phone Microphone
┌─────────────────────┐              ┌─────────────────────┐
│ PyAudio              │              │ WebRTC Audio Track   │
│ - 16kHz, mono        │              │ - via aiortc         │
│ - 1024 sample chunks │              │ - RMS level calc     │
└──────────┬──────────┘              └──────────┬──────────┘
           │                                     │
           ▼                                     ▼
┌─────────────────────┐              ┌─────────────────────┐
│ Voice Activity       │              │ Volume Comparison    │
│ Detection (VAD)      │              │ PC vol vs Phone vol  │
│ - RMS energy > 0.02  │              │ - Detects if voice   │
│ - Speech Recognition │              │   source is near PC  │
│   (Google API)       │              │   or near phone      │
└──────────┬──────────┘              └──────────┬──────────┘
           │                                     │
           ▼                                     ▼
┌──────────────────────────────────────────────────┐
│          ConfidenceEngine.evaluate()              │
│                                                   │
│  Voice detected + Lip moving    → "User Speaking" │
│  Voice detected + Lip NOT moving → "EXTERNAL      │
│                                     VOICE!" (FLAG)│
│  No voice                       → Normal          │
└──────────────────────────────────────────────────┘
```

### 5.2 Audio Feature Extraction (for ML)

During training, we extract these features from recorded WAV files:

```
WAV File (16kHz, mono)
  │
  ├── RMS Energy    = sqrt(mean(samples²))     → Volume level
  ├── Peak Amp      = max(|samples|)           → Loudest moment
  ├── ZCR           = zero crossings / length  → Speech vs noise
  ├── Duration      = samples / sample_rate    → Length in seconds
  └── Speech Ratio  = (clips with RMS > 0.02) / total_clips
```

---

## 6. AI & Detection Engine

### 6.1 Multi-Layer Detection Architecture

The detection system has three layers, from fastest to deepest:

```
┌──────────────────────────────────────────────────────────────┐
│  LAYER 1: HARD RULES (instant, rule_engine.py)               │
│  ┌──────────────────────────────────────────────────────┐    │
│  │ - No Face > 3 sec           → VIOLATION               │    │
│  │ - Multiple Faces             → VIOLATION               │    │
│  │ - Focus Lost                 → VIOLATION               │    │
│  │ - Restricted Object (YOLO)   → VIOLATION               │    │
│  │ - Head Yaw > 25°            → WARNING                  │    │
│  └──────────────────────────────────────────────────────┘    │
│                                                              │
│  LAYER 2: CONFIDENCE ENGINE (real-time, confidence_engine.py)│
│  ┌──────────────────────────────────────────────────────┐    │
│  │ Fuses multiple signals with weights:                   │    │
│  │   - Audio/VAD:    0.4 weight                          │    │
│  │   - Lip Reading:  0.3 weight                          │    │
│  │   - Head/Gaze:    0.3 weight                          │    │
│  │                                                       │    │
│  │ Score = w_vad * vad_signal                             │    │
│  │       + w_lip * lip_signal                             │    │
│  │       + w_gaze * gaze_signal                           │    │
│  │                                                       │    │
│  │ Output: SAFE (< 0.3) | WARNING (0.3-0.7) | FLAG (>0.7)│    │
│  └──────────────────────────────────────────────────────┘    │
│                                                              │
│  LAYER 3: ML ANOMALY DETECTION (post-session, ml_model.py)   │
│  ┌──────────────────────────────────────────────────────┐    │
│  │ Isolation Forest on aggregated session metrics:        │    │
│  │   - Learns what "normal" behavior looks like           │    │
│  │   - Flags statistical outliers as anomalies            │    │
│  │   - Provides anomaly score + explanation               │    │
│  └──────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────┘
```

### 6.2 Focus Monitoring (OS-Level)

```python
# focus_check.py uses Win32 API directly:

user32 = ctypes.windll.user32

# 1. Get the currently active (foreground) window handle
hwnd = user32.GetForegroundWindow()

# 2. Read its title text
title = user32.GetWindowTextW(hwnd, ...)

# 3. Compare with expected window name
if "Secure Exam Environment" not in title:
    → VIOLATION: Focus Lost → "{title}"
    # e.g., "Focus Lost → Chrome - WhatsApp Web"
```

This detects Alt+Tab, clicking on other windows, Task Manager — any attempt to switch away from the exam.

### 6.3 Network Monitoring

```
┌─────────────────────────────────────┐
│  network_monitor.py                  │
│                                      │
│  Monitors all network connections:   │
│  - Enumerates active TCP/UDP conns   │
│  - Checks against blacklist:         │
│    - WhatsApp, Telegram, Discord     │
│    - Screen share tools              │
│    - VPN applications                │
│  - Detects unusual port usage        │
│  - Monitors DNS queries              │
│                                      │
│  advanced_monitor.py                 │
│  - Deep packet inspection            │
│  - Traffic volume anomaly detection  │
│  - Protocol analysis                 │
└─────────────────────────────────────┘
```

---

## 7. Data Logging & Storage

### 7.1 Event Logger Design

Every event is logged as **structured JSONL** (one JSON object per line) for efficient appending and parsing:

```
data/dataset/{session_id}/
├── events.jsonl              # All events (append-only)
├── images/
│   ├── 1707000001234.jpg     # Violation screenshot (timestamp-named)
│   ├── 1707000005678.jpg
│   └── ...
└── FINAL_REPORT.md           # Generated post-session
```

#### JSONL Format

```json
{"timestamp": "2026-02-14T00:15:30.123456", "session_id": "8f4d69f8", "type": "VIOLATION", "image_path": "images/1707000001234.jpg", "data": "Focus Lost -> Chrome - WhatsApp Web"}
{"timestamp": "2026-02-14T00:15:31.456789", "session_id": "8f4d69f8", "type": "METRICS",  "image_path": null, "data": {"yaw": -15, "pitch": 8, "face_count": 1, "gaze": "forward"}}
{"timestamp": "2026-02-14T00:15:33.789012", "session_id": "8f4d69f8", "type": "VIOLATION", "image_path": "images/1707000003789.jpg", "data": "Looking Away Y:-35 P:12"}
```

### 7.2 Why JSONL?

| Format | Append-friendly | Human-readable | Parsing Speed | Schema flexibility |
|--------|:-:|:-:|:-:|:-:|
| CSV | Yes | Okay | Fast | Rigid schema |
| SQLite | No (locking) | No | Fast | Rigid schema |
| **JSONL** | **Yes** | **Yes** | **Fast** | **Flexible (schema-free)** |
| Full JSON | No (need to rewrite) | Yes | Slow (parse all) | Flexible |

JSONL is ideal because:
1. Each event is just `f.write(json.dumps(record) + "\n")` — no DB overhead
2. Can stream-process line by line for large files
3. Schema evolves freely — new fields don't break old readers
4. Human-readable for debugging and presentations

### 7.3 Image Capture Strategy

Images are captured **only on violations** (not every frame) to save disk space:

```python
def log(self, event_type, details=None, frame=None):
    if frame is not None:
        filename = f"{int(datetime.now().timestamp() * 1000)}.jpg"
        # Millisecond timestamp = guaranteed unique filename
        cv2.imwrite(os.path.join(self.images_dir, filename), frame)
        # Store RELATIVE path for portability
        image_rel_path = os.path.join("images", filename)
```

---

## 8. Secure Browser (UI)

### 8.1 Architecture

The UI is a **PyQt5 QMainWindow with an embedded Chromium browser** (QtWebEngine):

```
┌─────────────────────────────────────────────────┐
│  SafeBrowser (QMainWindow)                       │
│  - Frameless, fullscreen, always-on-top          │
│  - Captures keyboard events (blocks Alt+F4, etc)│
│                                                  │
│  ┌─────────────────────────────────────────────┐ │
│  │  QWebEngineView                              │ │
│  │  - Loads dashboard.html                      │ │
│  │  - Navigation restricted to allowed domains  │ │
│  │  - JavaScript bridge for real-time updates   │ │
│  │                                              │ │
│  │  ┌─────────────────────────────────────────┐ │ │
│  │  │  dashboard.html (Frontend)              │ │ │
│  │  │  - Webcam feed (base64 → <img>)         │ │ │
│  │  │  - Phone feed (base64 → <img>)          │ │ │
│  │  │  - 3D head visualization (Canvas)       │ │ │
│  │  │  - Status cards (gaze, focus, audio)    │ │ │
│  │  │  - Violation timeline                   │ │ │
│  │  │  - Phone connection status              │ │ │
│  │  └─────────────────────────────────────────┘ │ │
│  └─────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────┘
```

### 8.2 Python ↔ JavaScript Bridge

The ProctorThread communicates with the dashboard via `runJavaScript()`:

```python
# Python → JavaScript (ProctorThread → Dashboard)
browser_window.page().runJavaScript(
    f"updateCameraFeed('data:image/jpeg;base64,{base64_frame}')"
)

browser_window.page().runJavaScript(
    f"updateStatus({json.dumps(status_dict)})"
)

browser_window.page().runJavaScript(
    f"updateGaze3D({yaw}, {pitch}, '{direction}', {violation})"
)
```

### 8.3 Security Features

| Feature | Implementation | Purpose |
|---------|---------------|---------|
| **Fullscreen lock** | `setWindowFlags(Qt.FramelessWindowHint)` | Can't resize or move window |
| **Always on top** | `Qt.WindowStaysOnTopHint` | Can't hide behind other windows |
| **Keyboard capture** | `keyPressEvent` override | Blocks Alt+F4, Alt+Tab (partially) |
| **Navigation whitelist** | `SecurePage.acceptNavigationRequest()` | Only allowed domains can load |
| **Focus detection** | `FocusMonitor` (Win32 API) | Detects any window switch |

---

## 9. Session Analysis & Reporting

### 9.1 Post-Session Pipeline

When the exam ends (or the UI is closed):

```
1. ProctorThread.stop()        → Stop all AI processing
2. ProctorServer.stop()        → Close network connections
3. SessionAnalyzer.analyze()   → Generate FINAL_REPORT.md
   │
   ├── Parse events.jsonl
   ├── Build violation statistics
   ├── Run Isolation Forest on session metrics
   ├── Generate anomaly explanations
   ├── Calculate cheating confidence score
   └── Write FINAL_REPORT.md
```

### 9.2 Final Report Structure

```markdown
# Final Proctoring Report
**Session Date:** 2026-02-14 00:15
**Verdict:** SUSPICIOUS (Confidence: 46/100)

## AI Analysis (Isolation Forest Model)
The model found 3 anomalous time windows where behavior deviated
significantly from the learned baseline:
- High gaze deviation (2.1σ above mean)
- Unusual focus switching pattern

## Statistics
- **Duration:** 45 min 30 sec
- **ML Anomalies:** 3
- **Focus Lost Events:** 5
- **Hard Rule Violations:** 8

## Forensic Timeline
- **10:15:30**: Focus Lost → Chrome
- **10:15:45**: (ML Anomaly): High gaze variance, sudden movement
- **10:22:10**: Looking Away Y:-35 P:12
...
```

---

## 10. ML Training Pipeline

### 10.1 Complete Pipeline

See `train_model_concept.py` for the full implementation with 9 steps:

```
Step 1: DATA LOADING
  ├── Scan data/dataset/ and data/dataset.old/
  ├── Parse events.jsonl per session
  ├── Collect image paths and verdict labels
  └── Count: 97 sessions, 17K images, 41 audio clips

Step 2: DATA CLEANING
  ├── Remove events without timestamps
  ├── Validate ISO timestamp format
  ├── Remove empty/null data fields
  ├── Normalize dict-type data to strings
  ├── Deduplicate (same timestamp + data)
  └── Drop sessions with < 3 events

Step 3: EVENT LOG FEATURE EXTRACTION (20 features)
  ├── Violation rates per minute
  ├── Violation proportions
  ├── Head pose statistics (mean, max, std)
  ├── Burst density (rapid violations < 3s apart)
  └── Suspicious app focus switches

Step 4: VISION FEATURE EXTRACTION (17 features)
  ├── MediaPipe FaceMesh (468 landmarks)
  ├── Head pose via solvePnP (yaw, pitch)
  ├── Eye Aspect Ratio (EAR)
  ├── Face size and count
  └── Image brightness statistics

Step 5: AUDIO FEATURE EXTRACTION (8 features)
  ├── RMS energy (volume)
  ├── Zero-Crossing Rate (speech vs noise)
  ├── Peak amplitude
  └── Voice Activity Detection

Step 6: MULTI-MODAL FEATURE FUSION
  └── 45 features = 20 event + 17 vision + 8 audio

Step 7: ISOLATION FOREST TRAINING
  ├── StandardScaler normalization
  ├── 200 trees, contamination=0.15
  ├── Anomaly score computation
  └── Permutation-based feature importance

Step 8: STATISTICAL Z-SCORE ANALYSIS
  └── Per-feature deviation from population baseline

Step 9: EVALUATION & SAVE
  └── Save to models/cheat_model_unsupervised.pkl
```

### 10.2 Why Isolation Forest?

See `docs/Isolation_Forest_Documentation.md` for the complete mathematical explanation.

**Short version:** Isolation Forest isolates anomalies by randomly partitioning data. Anomalous sessions (cheating behavior) are isolated faster (fewer random splits) because they are "far" from normal behavior in the 45-dimensional feature space. No labels needed.

---

## 11. Security Considerations

### 11.1 Anti-Cheating Measures

| Attack Vector | Detection Method |
|--------------|-----------------|
| Alt+Tab to another window | FocusMonitor (Win32 API) |
| Using phone during exam | YOLOv8 object detection |
| Having someone else help | Multi-face detection (MediaPipe) |
| Reading notes (looking away) | Head pose + gaze estimation |
| Someone dictating answers | Audio VAD + lip movement (no lip = external voice) |
| Using messaging apps | Network monitor (process/port scanning) |
| Screen sharing | Network traffic analysis |
| VPN/proxy to hide traffic | DNS query monitoring |
| Covering camera | Brightness analysis + "No Face" detection |

### 11.2 Data Privacy

| Aspect | Implementation |
|--------|---------------|
| **Processing** | 100% local — nothing sent to cloud |
| **Storage** | Session data stored locally in `data/dataset/` |
| **Video** | Only violation frames saved, not continuous recording |
| **Audio** | Chunks stored locally, processed on-device |
| **Network** | Only local communication (PC ↔ Phone on same network) |

---

## 12. Future Plans & Vision

### 12.1 Pre-Exam Room Scanning

**Concept:** Before the exam starts, the student uses the phone camera to **scan their entire room** in 360°. The system builds a 3D understanding of the environment.

```
┌──────────────────────────────────────────────────────┐
│  PRE-EXAM ROOM SCAN (Planned)                         │
│                                                       │
│  1. Student slowly rotates phone camera 360°          │
│  2. Computer vision + SLAM builds 3D room model       │
│  3. System identifies:                                │
│     - Desk location and contents                      │
│     - Nearby screens/devices                          │
│     - Presence of other people                        │
│     - Mirrors or reflective surfaces                  │
│     - Notes/cheat sheets on walls                     │
│  4. Baseline room state saved                         │
│  5. During exam: periodically re-scan to detect       │
│     changes (e.g., someone entered the room)          │
│                                                       │
│  Technologies:                                        │
│  - ARCore/ARKit for 3D mapping                        │
│  - Depth estimation from monocular video              │
│  - Object detection for restricted items              │
└──────────────────────────────────────────────────────┘
```

### 12.2 3D Gaze Triangulation (Multi-Camera Fusion)

**Concept:** Using **both PC webcam and phone camera simultaneously** to precisely determine where the student is looking in 3D space.

```
                    SCREEN
              ┌──────────────────┐
              │                  │
              │   Exam Content   │
              │                  │
              └──────────────────┘
                     ▲  ▲
                     │  │  Gaze rays from BOTH cameras
                     │  │  intersect at a 3D point
                     │  │
    PC Webcam ───────┘  └─────── Phone Camera
    (frontal view)                (side view)
    
    Single camera:   Cone of uncertainty (can't tell exact depth)
    Two cameras:     EXACT point of gaze (triangulation!)
    
    ┌──────────────────────────────────────────────┐
    │  TRIANGULATION MATH                           │
    │                                               │
    │  Camera 1 ray: R₁ = O₁ + t₁ * d₁             │
    │  Camera 2 ray: R₂ = O₂ + t₂ * d₂             │
    │                                               │
    │  Gaze point = closest point between R₁ and R₂ │
    │                                               │
    │  Accuracy: ±2cm at 50cm distance (estimated)  │
    │                                               │
    │  This tells us EXACTLY what the student is     │
    │  looking at: their screen, phone, notes, etc.  │
    └──────────────────────────────────────────────┘
```

**What this enables:**
- Know if student is reading their screen vs. looking at notes
- Detect gaze at a phone screen (even if phone is hidden from webcam)
- Measure reading patterns (normal exam reading vs. scanning for help)
- Detect gaze at another person's screen

### 12.3 Behavioral Pattern Learning

**Concept:** Build a **per-student behavioral profile** during the first 5 minutes of the exam, then detect deviations from their personal baseline.

```
┌────────────────────────────────────────────────────────────────┐
│  BEHAVIORAL BASELINE (First 5 minutes)                         │
│                                                                │
│  Metrics learned per student:                                  │
│  ├── Typical head movement range (yaw ±15°, pitch ±10°)       │
│  ├── Natural blink rate (15-20 blinks/min)                     │
│  ├── Reading speed & saccade pattern                           │
│  ├── Typing rhythm (keydown/keyup intervals)                   │
│  ├── Natural fidget frequency                                  │
│  └── Normal background noise level                             │
│                                                                │
│  During exam:                                                  │
│  ├── "This student normally looks ±15° left/right"             │
│  │    → Student suddenly looking 40° → ANOMALY                 │
│  ├── "This student blinks 18 times/min"                        │
│  │    → Blink rate drops to 5/min → staring (copying?) → FLAG │
│  └── "This student types steadily at 60 WPM"                  │
│       → Sudden burst of 120 WPM → pasting? → FLAG            │
└────────────────────────────────────────────────────────────────┘
```

### 12.4 Continuous Authentication

**Concept:** Verify the student's identity **throughout** the exam, not just at login.

```
Continuous Authentication Pipeline:
                                    
  Exam Start                              Exam End
  │                                           │
  ▼                                           ▼
  ┌─── Face Embedding (FaceNet/ArcFace) ─────┐
  │  Capture reference face at T=0            │
  │  Every 30 sec: compare current → reference│
  │  If similarity < 0.7 → "Is this the same  │
  │  person?" → FLAG                          │
  └───────────────────────────────────────────┘
```

### 12.5 Advanced Audio Intelligence

```
┌────────────────────────────────────────────────┐
│  FUTURE AUDIO FEATURES                          │
│                                                 │
│  1. Speaker Diarization                         │
│     - Separate "Student voice" from "Other"     │
│     - Enroll student voice at exam start        │
│     - If unknown speaker detected → FLAG        │
│                                                 │
│  2. Whisper Detection                           │
│     - Low-energy speech below normal threshold  │
│     - Pattern: short bursts of quiet speech     │
│     - Could indicate receiving whispered help   │
│                                                 │
│  3. Earpiece Detection                          │
│     - One-way audio pattern (student listens,   │
│       doesn't speak back)                       │
│     - Unusual head tilting toward one ear        │
│     - Cross-reference with lip movement (none)  │
│                                                 │
│  4. Environmental Fingerprinting                │
│     - Learn room acoustics at start             │
│     - Changes in reverb → door opened?          │
│     - New background noise sources              │
└────────────────────────────────────────────────┘
```

### 12.6 Phone Lockdown Mode

```
┌────────────────────────────────────────────────┐
│  PHONE LOCKDOWN (Implemented)                   │
│                                                 │
│  When exam starts, PC sends LOCKDOWN command:   │
│  Phone → Restricted mode:                       │
│  ├── Camera streams to PC (required)            │
│  ├── Sensor telemetry active                    │
│  ├── Can't switch apps (detected via sensors)   │
│  ├── Can't turn off phone (accelerometer)       │
│  └── Alerts if phone moved significantly        │
│                                                 │
│  Sensors monitored:                             │
│  ├── Accelerometer → phone picked up/moved?     │
│  ├── Proximity → phone held to ear?             │
│  ├── Light sensor → phone covered/put in pocket?│
│  └── Magnetometer → phone near another device?  │
└────────────────────────────────────────────────┘
```

### 12.7 Multi-Exam Model Evolution

```
Exam 1:  Train Isolation Forest on first cohort
              → Model v1 (cold start, less accurate)
              
Exam 2:  Retrain with accumulated data
              → Model v2 (more data, better boundaries)
              
Exam N:  Model has seen thousands of sessions
              → Model vN (robust, generalizable)
              
Future:  Semi-supervised transfer
              → Use expert-reviewed sessions as weak labels
              → Fine-tune with Gradient Boosting on top
```

---

## Summary

Phone-Proctor is a **multi-modal, AI-driven, privacy-first exam proctoring system** that combines:

| Component | Technology | Status |
|-----------|-----------|--------|
| PC Webcam AI | MediaPipe + YOLOv8 + OpenCV | **Implemented** |
| Phone Camera Stream | WebRTC via aiortc | **Implemented** |
| Network Discovery | UDP Broadcast | **Implemented** |
| Audio Detection | PyAudio + VAD + Lip Reading | **Implemented** |
| Focus Monitoring | Win32 API | **Implemented** |
| Network Monitoring | Raw socket inspection | **Implemented** |
| ML Anomaly Detection | Isolation Forest (Unsupervised) | **Implemented** |
| Multi-modal Training | 45 features (Event+Vision+Audio) | **Implemented** |
| Secure Browser | PyQt5 + QtWebEngine | **Implemented** |
| Session Reports | FINAL_REPORT.md | **Implemented** |
| 3D Gaze Triangulation | Multi-camera fusion | **Planned** |
| Room Scanning | ARCore/SLAM | **Planned** |
| Continuous Authentication | FaceNet embedding | **Planned** |
| Speaker Diarization | Voice fingerprinting | **Planned** |
| Behavioral Baseline | Per-student profiling | **Planned** |

---

*Document generated for Phone-Proctor v1.0*
*Author: Pratyush Mishra*
*Date: February 2026*
