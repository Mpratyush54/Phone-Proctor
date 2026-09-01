# Phone-Proctor 🎯

Control-plane + laptop agent for multi-modal exam proctoring. GitHub issues #1–#66 (tracks A–G) are implemented in this tree.

## Quick start

Laptop agent (existing local mode):

```bash
pip install -r requirements.txt
python main.py
```

Control plane (API, gateway, worker, console). Postgres is required from the first vertical slice:

```bash
./dev.sh                          # Docker Postgres/MinIO/Dex, or local Postgres
export DATABASE_URL=postgres://proctor:proctor@127.0.0.1:5432/proctor
cd server && npm install && npm test && npm run api
# other terminals:
cd server && npm run gateway
cd server && npm run worker
cd admin && npm install && npm run dev
```

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
