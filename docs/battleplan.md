# Phone-Proctor — Roadmap (locked 2026-08-12)

> Status: **IMPLEMENTATION STARTED** (2026-08-26). Dual-camera on one phone is **out of scope**.
> Goal: standalone installers (Win / Linux / macOS) with **bundled assets** and **minimal optional deps**.

## Out of scope

- Simultaneous front+rear camera on a single phone. Product uses **laptop webcam + phone camera** (switchable), not dual concurrent phone cameras.

## 3-app architecture

| App | Stack | Packaging |
|---|---|---|
| **Laptop Agent** | Python (QtWebEngine dashboard) + AI + uplink | **PyInstaller** one-folder / one-file; OS installers |
| **Central Server** | Node.js + Express + `ws` + Mongo + Redis | Docker / single Node deploy on VPS |
| **Admin Website** | React (static, served by Node) | Bundled with server |

Phone app remains a separate RN client; pairs to **exam session** (not dual-cam).

## Standalone / minimal dependency rules

- Agent ships with **bundled** models + `dashboard.html` + config (`sys._MEIPASS` / `utils.paths`).
- **scapy / Npcap** = optional. Agent runs without packet sniff; probe + consent gate before enabling.
- **torch / torchaudio** = CPU wheels only (`2.5.1+cpu`), never CUDA wheels in the product agent.
- No hard requirement on system Python packages after install — installer embeds the runtime.
- Server is the only always-on shared dependency (DB + object storage).

## Transport (final)

- **Agent <-> Node:** WebSocket (WSS) — JSON envelopes for control/events, **binary frames** for camera (5 fps) + screen (1 fps) + input blobs. No gRPC.
- **Node -> browser:** WebSocket relay rooms (per session).
- **Backpressure:** adaptive bitrate via send-queue depth (drops to 3 fps / flags `LOW_BANDWIDTH`).

## Streaming & durability ("nothing lost, smallest to biggest")

- **Write-ahead journal** on agent (fsync before send; `session_id, seq_no, batch_id`).
- Node **acks batches**; agent **replays unacked** on reconnect.
- Ingest piggybacks on durable bus (**Redis Streams** now -> **Kafka/Redpanda** at 100k+).
- **Gap detector** reconciles seqs vs Mongo; auto-replay; per-session integrity hash.
- **Storage:**
  - Mongo = full durable audit (events, AI logs, keystrokes, clicks, telemetry, frame indexes)
  - Redis = live-only (presence, current violation; NOT source of truth)
  - object storage (S3/OSS) = frame video blobs

## Input & screen (new)

- **Keystrokes:** full key-by-key (all keys + modifiers + timestamps), consent-gated.
- **Clicks:** every click (pos/button/time).
- **Screen:** fixed 1 fps captures; streamed as binary JPEG tagged `SCREEN`.

## Platform prerequisites (installed w/ app + consent, strictly enforced)

- **Windows:** Npcap silent install (Inno Setup consent checkbox); runtime probe, refuse **sniff features** without it (core proctoring still runs).
- **Ubuntu:** no driver; `.deb` post-install `setcap cap_net_raw,cap_net_admin+eip` only if sniff enabled.
- **macOS:** `.pkg` enables Developer Mode; elevated only when sniff/consent requires it.
- Lazy scapy -> optional import (no hard dependency).

## Anti-tamper (flag-only)

- Build-time SHA-256 manifest -> agent self-attestation at register -> mismatch flags `TAMPERED` + forensic trail + alert admin.
- Heartbeat every 5 s w/ monotonic counter.
- Device fingerprint bound to session.

## Build & CI

- torch `2.5.1+cpu` + `torchaudio 2.5.1+cpu` (pinned; ~250 MB vs multi-GB CUDA).
- Offline assets bundled: Silero VAD (when present), `yolov8n.pt`, dashboard HTML, config; frozen-path helper (`sys._MEIPASS`).
- PyInstaller per-OS; **Inno Setup** (Win) / `.deb` (Ubuntu) / `.pkg` (macOS); **GitHub Actions** 3-OS matrix.

## Perf

- Rate-limit face/mesh/pose/gaze to **every 2-3 frames** in `proctor_thread.py` (pose kept for overlays).

## Phases

| # | Item | Status |
|---|---|---|
| 0 | torchaudio CPU pin (`torch/torchaudio 2.5.1+cpu`) | in progress |
| 1 | offline assets + lazy scapy + consent gates | in progress |
| 2 | `pp_platform/` layer (consent, attestation, capability probes) | in progress |
| 3 | agent WS uplink + write-ahead journal + replay + input/screen | in progress (scaffold) |
| 4 | Node server (WSS, bus, Mongo/Redis/object-store, JWT, relay, REST) | in progress (scaffold) |
| 5 | React site (login, live grid, dual-video + screen + timeline, flags) | pending |
| 6 | installers + CI matrix | in progress (PyInstaller stub) |
| 7 | perf rate-limit | pending |

## Open decisions

- [ ] Auth model: exam-code + student-ID (rec.) vs admin-created accounts?
- [ ] Roles: admin + student only, or + read-only proctor/invigilator?
- [ ] Frames at ~1000 sessions (~TB/day): full to S3/OSS (video also "nothing lost") vs downsample (events guaranteed, video "as configured")?
