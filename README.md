# Phone-Proctor 🎯

Control-plane + laptop agent for multi-modal exam proctoring. GitHub issues #1–#66 (tracks A–G) are implemented in this tree.

## Quick start

### Student desktop (staff-controlled)

Install Python 3.12 and the Qt desktop dependencies. On Linux, run from a graphical session. Open the student desktop from the repository root:

```bash
python -m pip install "websockets>=14" opencv-python PyQt6 PyQt6-WebEngine
python -m agent
```

Start the shared control plane and staff console first. In the console, create and open an exam, import the roster, and issue an enrollment token. The candidate pastes the token into the desktop and chooses whether to allow the webcam availability check. Start, pause, resume, warn, and end are available from the candidate session in Monitoring. The desktop shows the observed exam state and reports a command receipt back to staff. Set the HTTPS exam website in Exam setup before the first candidate enrolls. The website opens inside the student workspace after staff select Start. Pause hides the exam, Resume restores the same page, and End closes it. The exam provider still owns its login and submission flow.

The default local API and gateway ports are 8080 and 8081. When Metro uses 8081, run `GATEWAY_PORT=8083 npm run control-plane` in `server` and launch the student app with `python -m agent --gateway ws://127.0.0.1:8083`. The desktop's Connection settings also allow staff-provided API and gateway addresses. Remote endpoints require HTTPS and WSS. For local development, the exam website can use HTTP on loopback.

For a local test without webcam hardware, clear **Require a desktop camera check before starting** when creating the exam. The desktop reports connection, camera availability and exam activity. Webcam frames are discarded locally. The separate local app below handles legacy phone streaming.

### Legacy local app

```bash
pip install -r requirements.txt
python main.py
```

Control plane (API, gateway, worker, console). Start the local PostgreSQL 16
service first (for example, `docker compose -f infra/docker-compose.yml up -d --wait postgres`),
then run the migrations and start the shared control plane:

```bash
export DATABASE_URL=postgres://proctor:proctor@127.0.0.1:5432/proctor
cd server
npm ci
npm run migrate
npm run control-plane
```

In a separate terminal from the repository root, start the staff console:

```bash
cd admin
npm ci
npm run dev
```

Use the console address shown by Vite and the local development sign-in.
Set `GATEWAY_PORT=8083` when React Native Metro uses the default gateway port
8081. Pass the same gateway port to agent clients.

The shared control-plane command starts the API, gateway, and worker in one
process so they can share exam, agent, command, and staff session state.
Postgres records persisted rows, but the current store does not reload all
runtime state on restart or share it across separately started processes.
The standalone `api`, `gateway`, and `worker` commands are for isolated
development and troubleshooting.

The first demonstrable milestone is one authenticated controller starting one
authenticated agent, receiving one durably acknowledged event, and ending the
session after both processes have been restarted once
(`docs/controller-implementation-plan.md` §17).

Product mode (`PHONE_PROCTOR_MODE=product`) requires `wss://`, binds leftover LAN sockets to localhost, disables Google STT, and ignores Escape / `CMD:KILL`. Session reports are observable evidence only — never `CHEAT DETECTED`.

See `docs/controller-implementation-plan.md`, `docs/feature-flags.md`, and `docs/runbooks/`.

---

A distributed AI-powered exam proctoring backend that ingests multi-modal data from mobile clients in real time, runs computer vision and sensor fusion analysis, and triggers automated supervision events when anomalous behavior is detected.

Built as the core analysis pipeline for a phone-based proctoring system where the mobile device *is* the sensor — no dedicated webcam or hardware required.

---

## The Problem

Traditional proctoring tools require dedicated webcams and run on desktops. This locks out students in low-resource environments. Phone-Proctor turns a standard Android/iOS device into a full monitoring station by fusing its camera, accelerometer, and gyroscope into a unified behavioral analysis pipeline.

---

## Architecture

```
Mobile Client (exam-protector-mobile)
        │
        │  WebSocket / HTTP stream
        ▼
┌─────────────────────────┐
│   Ingestion Layer       │  Receives camera frames + sensor telemetry
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│   Sensor Fusion Engine  │  Correlates motion data with visual events
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│   Vision Pipeline       │  Real-time frame analysis (face, gaze, motion)
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│   Rule-Based Decision   │  Flags violations, triggers supervision events
│   Engine                │
└─────────────────────────┘
```

---

## Core Features

### Multi-Modal Sensing
- Ingests live camera frames from connected mobile clients
- Receives accelerometer and gyroscope telemetry in real time
- Synchronizes visual and motion streams by timestamp for accurate correlation

### Computer Vision Pipeline
- Real-time face detection and presence validation
- Gaze and head pose estimation to detect looking away
- Motion classification using frame differencing and optical flow

### Sensor Fusion
- Correlates sudden device motion (accelerometer spike) with visual anomalies
- Reduces false positives by requiring multi-signal agreement before flagging

### Rule-Based Decision Engine
- Configurable rule set: face absent > N seconds, repeated head turns, device movement, etc.
- Emits structured supervision events with timestamp, session ID, and evidence snapshot
- Designed for human-in-the-loop review — flags incidents, does not auto-fail candidates

### Session Management
- Tracks multiple concurrent exam sessions
- Per-session event log with severity levels

---

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python |
| Computer Vision | OpenCV |
| Real-time Communication | WebSocket |
| Sensor Processing | NumPy |
| Mobile Client | [exam-protector-mobile](https://github.com/Mpratyush54/exam-protector-mobile) |

---

## Getting Started

### Prerequisites
- Python 3.9+
- OpenCV (`pip install opencv-python`)
- NumPy (`pip install numpy`)

### Installation

```bash
git clone https://github.com/Mpratyush54/Phone-Proctor.git
cd Phone-Proctor
pip install -r requirements.txt
```

### Run

```bash
python main.py
```

Connect the mobile client (exam-protector-mobile) to the server address shown in the terminal.

---

## Related

- **Mobile Client:** [exam-protector-mobile](https://github.com/Mpratyush54/exam-protector-mobile) — Flutter app that streams camera and sensor data to this backend

---

## License

ISC
