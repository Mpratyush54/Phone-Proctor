# Phone-Proctor — Controller-First Scale Plan

**Status:** proposed (supersedes `docs/battleplan.md` open decisions on auth, roles, and video).  
**Date:** 2026-08-31  
**Audience:** anyone implementing or reviewing the product path.

This document is the plan for turning the current **single-student laptop appliance** into a **controller-run exam system**: one invigilator console that creates exams, starts them, watches a cohort, drills into a student, and retains an audit trail.

It is not a bug-fix list. The prior repository audit covers defects. Those
defects still have to be fixed (Phase 0) or the scaled system will multiply
them.

---

## 1. Verdict

The current architecture cannot scale, even if every bug is fixed.

| Today | Why it does not scale |
|---|---|
| Qt app is exam UI + AI + logger + “dashboard” | There is no controller. Watching N students means N pasted session IDs into a scaffold page. |
| Phone pairs by LAN UDP broadcast | Remote / at-home exams cannot discover the laptop. |
| Node store is an in-memory `Map`, 5 000 events/session, no auth | Restart wipes state. Anyone can join a room. One process is the ceiling. |
| Battleplan streams 5 fps camera + 1 fps screen continuously to the server | ~320 KB/s per student. 200 students ≈ 64 MB/s inbound. One VPS and one browser grid both die. |
| Uplink is one-way (agent → server) | A controller cannot start, warn, request live video, or end a session. |
| AI, lockdown, and “admin” live on the student PC | The student sees proctor internals; the invigilator sees almost nothing. |

**The architectural change:** invert the center of gravity.

- **Today:** the student PC *is* the product; the server is optional telemetry.
- **Target:** the **exam controller** *is* the product. Laptop agent and phone are enrolled sensors. An exam does not begin until the control plane says so.

Keep on-device AI. That part is the correct scale split. Move **orchestration, identity, live observation, commands, and audit** off the laptop.

---

## 2. Target shape (four planes)

```
                    ┌──────────────────────────────────────────┐
                    │  CONTROLLER CONSOLE (React)              │
                    │  exams · roster · command center ·       │
                    │  live grid · student view · review       │
                    └──────────────────┬───────────────────────┘
                                       │ HTTPS + WSS (JWT)
                    ┌──────────────────▼───────────────────────┐
                    │  CONTROL API (stateless replicas)        │
                    │  exam lifecycle · RBAC · policy · audit  │
                    └───────┬───────────────────┬──────────────┘
                            │                   │
             ┌──────────────▼───────┐  ┌────────▼─────────────┐
             │ POSTGRES             │  │ REDIS                │
             │ durable metadata,    │  │ presence, leases,    │
             │ commands and events  │  │ fanout, rate limits  │
             └──────────────────────┘  └────────┬─────────────┘
                                                │
           ┌─────────────────────┬───────────────┴──────────────┐
           │                     │                              │
  ┌────────▼────────┐   ┌────────▼─────────┐       ┌────────────▼──────┐
  │ WS GATEWAYS     │   │ MEDIA PLANE      │       │ OBJECT STORAGE    │
  │ register, event │   │ signaling + SFU  │       │ snapshots/clips   │
  │ commands, ack   │   │ + TURN fallback  │       │ direct presigned  │
  └────────┬────────┘   └────────┬─────────┘       │ uploads           │
           │                     │                 └────────────▲──────┘
    ┌──────▼───────┐      ┌──────▼───────┐                      │
    │ EDGE AGENT   │      │ PHONE APP    │──────────────────────┘
    │ local AI/WAL │      │ camera/sensor│
    │ ring buffer  │      │ pairing token│
    └──────────────┘      └──────────────┘
```

| Plane | Job | Not its job |
|---|---|---|
| **Control** | Identity, exam lifecycle, policy, roster, authorization | Run YOLO / MediaPipe |
| **Realtime** | Presence, live flags, command delivery | Durable history or carrying camera bytes |
| **Media** | SFU live viewing, TURN fallback, direct snapshot/clip upload | Exam state or authorization decisions |
| **Ingest** | Acked event log, gap detection, presigned media metadata | Live grid rendering |
| **Edge** | Cameras, mic, gaze, rules, fusion, local WAL, lockdown | Host the invigilator UI |

**Hard rule:** never move the vision models to the server. N students already paid for N CPUs. The server scales on **events and presence**, not pixels.

---

## 3. Close the open decisions

Battleplan left three decisions open. This plan locks them.

### 3.1 Auth

**Exam-code + one-time agent enrollment token, plus real accounts for staff.**

| Actor | How they authenticate |
|---|---|
| Staff | Email+password or SSO → short-lived access token. Authorization comes from the scoped role templates in §3.2. |
| Student agent | One-time **enrollment token** minted on the roster row (not a guessable 8-char session id). Token is exchanged once at `REGISTER` for a revocable session credential; server binds `session_id` + device fingerprint. |
| Phone | A separate 5-minute pairing token minted after agent registration and shown as QR/short code. It is bound to the same session and cannot register an agent. |

Do **not** let the agent invent `session_id`. The control plane issues it.

### 3.2 Roles

Use permissions internally and expose role templates. A person may have a role
for one organization, one exam, or one support incident; do not encode all
authorization as a single global `role` column.

| Role template | Scope | Main permissions |
|---|---|---|
| `platform_operator` | Entire deployment | Tenant provisioning, service health, incident response. No exam media by default. |
| `org_admin` | One institution | Staff, retention, integrations, policy templates, audit export. |
| `exam_owner` | Assigned exams | Create/configure exam, roster, schedule, assign controllers/reviewers. |
| `controller` | Whole assigned exam | Start/pause/end exam, manage staffing, admit/re-admit, handle overrides and bulk commands. |
| `invigilator` | Assigned candidate group | Monitor, claim/note/resolve/escalate alerts, warn, request clip/live view, and end an assigned session when permitted. |
| `observer` | Live assigned exams | View grid and student feed; no commands. Useful for secondary invigilators. |
| `reviewer` | Completed assigned exams | Review incidents, label evidence, disposition flags; no live commands. |
| `appeals_reviewer` | Assigned appeals | See frozen evidence and original/reviewer decisions; cannot edit the original. |
| `support_engineer` | Time-limited support grant | Device diagnostics and redacted logs; camera/audio denied unless separately approved. |
| `compliance_auditor` | Org/time range | Immutable audit log and retention evidence; read-only. |
| `ml_annotator` | De-identified queues | Label observable events; no identity, roster, or full-session access. |
| `student` | Own enrollment | Pre-check, consent, exam shell, warnings, own completion receipt. No console. |

High-impact commands require explicit permissions such as
`session.live_view`, `session.warn`, `session.terminate`, and `exam.end`.
`exam.end`, policy changes during a live exam, and evidence deletion require
step-up authentication and an audit reason.

Every live exam has explicit staff assignments. A controller assigns candidate
groups to invigilators; alert claims carry owner, note, escalation state and a
renewable lease. Shift handoff transfers unresolved claims and records both
actors. This is required at 200+ seats, not an optional later feature.

**Appeals workflow:** the student (through the institution's student portal) or
an `exam_owner` may submit an appeal within the institution's configured
window (default 14 days). Submission freezes the evidence manifest and original
review disposition. An `appeals_reviewer` who did not make the original
decision reviews the frozen evidence, records a reasoned outcome, and notifies
the institution/student. Appeals append decisions; they never overwrite the
original review or audit log.

### 3.3 Video (this is the scale decision)

**Events are guaranteed. Video is on a policy, not “everything always.”**

| Mode | What is uploaded | When to use |
|---|---|---|
| **Presence** (default) | Heartbeat + events + a JPEG snapshot every 5 s (webcam) | Grid of 30–1000 students |
| **Incident** | 5–10 s clip around each `VIOLATION` / `TAMPERED` (webcam ± phone) | Always on |
| **On-watch** | WebRTC through an **SFU**, only while an authorized controller is subscribed | Drill-down; more than one observer does not multiply student upload |
| **Full record** | Continuous 5 fps + 1 fps screen | **Opt-in per exam**, small cohorts, legal hold. Never the default. |

Battleplan’s “binary frames for every session, nothing lost” is rejected as the default. It makes a 200-seat exam a bandwidth and storage product, not a proctoring product.

Rough inbound (one student, JPEG ~30 KB):

| Policy | Steady rate |
|---|---|
| Full record (2 cams @ 5 fps + screen @ 1 fps) | ~320 KB/s |
| Presence snapshots (1 cam @ 0.2 fps) + events | ~8–15 KB/s |
| Events + heartbeat only | ~1–2 KB/s |
| On-watch (one controller viewing one student) | +~150 KB/s for that session only; codec/network dependent |

200 students, presence policy: ~2–3 MB/s. Same cohort, full record: ~64 MB/s. Design the default for the first number.

---

## 4. Controller use cases (the product)

These are the use cases the console must own. If a use case still lives only inside the student’s Qt window, it is not done.

### 4.1 Before the exam

1. Create exam (title, window, duration, policy pack).
2. Import roster (CSV: student id, name, email).
3. Issue agent enrollment tokens (printable / mail merge).
4. Attach exam **content URL** (LMS or hosted paper). The Wikipedia iframe in `assets/dashboard.html` is not exam content.
5. Policy pack: which sensors are required (webcam, phone, mic), hotspot rule, sniffer allowed, video mode, look-away threshold, allowed processes.
6. Watch **pre-check grid**: camera ok, phone paired, consent recorded, agent attested, waiting.

### 4.2 Starting

7. Scheduled start **or** controller presses **Start exam** (all ready agents, or selected rows).
8. Agents receive `EXAM_START`. Lock-down begins. Content URL loads. Scoring starts.
9. Late join: controller admits a waiting student without restarting the room.

### 4.3 During (watch the users)

10. **Live grid** for the exam: one cell per student — name; lifecycle
    (`registered|ready|live|paused|ended|terminated`); connectivity
    (`connected|degraded|disconnected`); attention
    (`normal|flagged|review_pending`); last snapshot, last event and heartbeat
    age.
11. Sort/filter: flagged first, disconnected, never-started.
12. **Student drawer** (one click): timeline of events, live snapshot, optional
    laptop camera + phone camera + screen tabs, agent integrity, process/focus
    flags, network quality, permissions and last command result. Opening live
    media is audited and only starts authorized SFU subscriptions.
13. **Warn** — command to agent; student sees a banner; event logged.
14. **Request clip** — agent uploads last N seconds from local ring buffer (even if video mode is presence-only).
15. **Kick / end session** — agent stops, flushes WAL, unlocks.
16. **Pause exam** (clock + scoring freeze) for a room-wide incident.
17. Multi-controller: two invigilators on the same exam see the same presence
    (Redis pub/sub). A renewable watch lease shows who is handling each alert
    and prevents duplicate warnings; takeover remains possible and audited.

### 4.4 After

18. Exam auto-end at window, or controller **End exam**.
19. Review queue: all sessions with `VIOLATION`/`TAMPERED`, clips, timeline.
20. Export (JSONL + clip index). Retention job deletes blobs after policy days.
21. Integrity report: seq gaps, reconnect count, attestation mismatches.

If the team only builds a prettier student dashboard, none of this exists.

---

## 5. What changes in each existing piece

### 5.1 Keep (edge intelligence)

These stay on the laptop. Do not rewrite them as a cloud CV farm.

- `face/`, `gaze/`, `fusion/`, `rules/` (but **wire `Thresholds`** — policy pack from server overrides YAML).
- `ai/object_detector.py`, `ai/audio.py` (on-device VAD; **disable Google STT** unless the policy explicitly allows off-box transcription).
- `analysis/session_analyzer.py` as a **local** summary; also emit a compact `SESSION_SUMMARY` event so the console does not need the Markdown file.
- `agent/journal.py` WAL concept (fsync, seq, ack, replay). This is the ingest contract.

### 5.2 Change (agent becomes a device, not the product)

| Current | Target |
|---|---|
| `python main.py` launches Qt “safe browser” as the whole UX | Agent starts as a **supervised process**. Student UI is a thin lock-down shell: status, warnings, exam iframe from control plane. All observation UI moves to the console. |
| `--server` optional | Required in product builds. Local-only remains a **dev flag**. |
| Agent sends events if it feels like it | Agent **registers with its one-time enrollment token**, then only runs the exam on `EXAM_START`. |
| Phone: `0.0.0.0:5000` + UDP `PROCTOR_DISCOVER` | Primary: phone registers with **the same control plane**. LAN WebRTC is an optimization when both devices share a network, not the pairing method. |
| Uplink JSON one-way | Bidirectional: `REGISTER`, `HEARTBEAT`, `EVENT`, `CLIP_META`, `ACK`; down: `COMMAND`. |
| `EventLogger` writes `data/dataset/` and maybe uplinks | WAL is the source of truth; local files are cache. Use `utils.paths.writable_data_dir()`. |
| Consent collected, mostly ignored | Each subsystem **fail-closed** on its flag. Policy pack can require a flag (no token → cannot start). |
| Session id = 8-char uuid from the agent | Server-issued `session_id` (UUID). |

**Command set (minimum):** `EXAM_START`, `EXAM_END`, `EXAM_PAUSE`, `EXAM_RESUME`, `WARN`, `REQUEST_LIVE`, `STOP_LIVE`, `REQUEST_CLIP`, `UPDATE_POLICY`, `KICK`.

**Ring buffer on the agent:** keep the last 15–30 s of webcam (and phone if present) in memory or a small disk spool so `REQUEST_CLIP` works without continuous upload.

### 5.3 Replace (central server)

Throw away the idea that `server/src/store.js` “swaps for Mongo later without changing callers.” Callers need a real model.

Replace with:

1. **HTTP API** (authn/z on every route): exams, roster, session list, commands, review.
2. **Two WS paths**, both authenticated:
   - `/agent` — one connection per session.
   - `/console` — one connection per invigilator **per exam** (not per student). Grid events fan in here.
3. **Postgres** as source of truth (exams, users, enrollments, session index).
4. **Append-only events** (Postgres partitioned by day, or a log table keyed `(session_id, seq_no)` unique).
5. **Redis** — `session:{id}` presence hash, `exam:{id}:live` pub/sub for console fanout. Not the audit log.
6. **Object storage** — clip and snapshot bytes. Agent/phone upload using
   short-lived presigned URLs so camera bytes do not traverse Node gateways.
7. **Bind + TLS.** Default listen `127.0.0.1` in dev; production terminates TLS at the load balancer. No `cors()` allow-all.

All APIs are versioned, cursor-paginated and tenant-scoped. Bulk start/pause/end
returns per-session results. Exam/policy edits use optimistic concurrency;
creation, token reissue and commands require idempotency keys. Every
tenant-owned row carries `org_id` directly or uses an enforced composite
foreign key. HTTP, WS, object and SFU authorization are cross-tenant tested.

Do **not** introduce Kafka/Redpanda until a load test shows Redis Streams or a single Postgres writer is the bottleneck. That is Phase 6, not Phase 1.

Fix the static admin path (`server/admin/public` vs repo `admin/public`) by **building the React console into `server/public/`**.

### 5.4 Replace (admin UI)

`admin/public/index.html` (paste session id, dump JSON) is not an invigilator product.

Build a React app with four screens:

1. **Login**
2. **Exam list** (create, roster, policy, start window)
3. **Live** — grid + student drawer + command bar
4. **Review** — post-exam timeline + clips

No live video in the grid. Snapshot + pills only. Video only in the drawer, on subscribe.

### 5.5 Phone app (external repo)

Pairing target: `wss://<api>/signal` with the short-lived phone pairing token
minted after agent registration. Use a WebRTC **SFU**
(managed or self-hosted) for live viewing and TURN as connectivity fallback.
TURN alone is not a scalable media architecture: multiple controllers would
multiply upstream sessions and recording/fanout stays coupled to peers. Empty
`iceServers` (current `webrtc_manager.py`) is LAN-only and must not be the
production path.

Laptop no longer needs to bind `0.0.0.0:5000` for remote exams. That socket, if kept, is localhost or the hotspot interface, and requires a pairing PIN.

### 5.6 Lock-down / exam content

Split “proctor agent” from “exam page”:

- Agent enforces: fullscreen, focus, process blocklist, optional kiosk.
- Content URL comes from the exam record (Moodle, Google Form, your own paper).
- Remove in-shell Wikipedia as the exam.
- Escape-to-exit must require a controller `KICK` or a local override password set by admin — not the student’s Escape key.

### 5.7 Delete or quarantine (do not take to production)

- `network/phone_client_sim.py` (wrong protocol)
- Live path for `ai/cheat_predictor.py` pickle load
- Student-visible full debug overlay as the default UI
- `--skip-consent` in release installers
- Continuous Google Web Speech

---

## 6. Data model (minimum)

```
org
  id, name

user
  id, org_id, email, status

role_assignment
  user_id, role_template, scope_type, scope_id, expires_at

exam_staff_assignment
  org_id, exam_id, user_id, candidate_group_id, role_template,
  starts_at, ends_at

exam
  id, org_id, title, starts_at, ends_at, content_url,
  policy_json, video_mode, status  -- draft | open | live | closed

enrollment
  exam_id, student_external_id, display_name,
  enrollment_token_hash, token_used_at

session
  id, exam_id, enrollment_id,
  agent_fingerprint, integrity_status,
  phone_paired,
  lifecycle_state,      -- registered | ready | live | paused | ended | terminated
  connectivity_state,   -- connected | degraded | disconnected
  attention_state,      -- normal | flagged | review_pending
  last_seq, last_heartbeat_at, started_at, ended_at

event
  org_id, session_id, seq_no, batch_id, schema_version, source,
  type, severity, payload_json, client_wall_ts, client_monotonic_ms,
  server_ts, correlation_id, policy_version, detector_versions
  UNIQUE (session_id, seq_no)

clip
  id, org_id, session_id, event_seq, kind,  -- snapshot | incident | live-segment
  object_key, upload_state, sha256, duration_ms, created_at

command
  id, org_id, session_id, type, payload_json, issued_by, issued_at,
  idempotency_key, status, acked_at, result

review_case
  id, session_id, state, priority, assigned_to, model_version,
  opened_at, decided_at

annotation
  id, case_id, segment_start_ms, segment_end_ms, label, confidence,
  annotator_id, created_at

audit_action
  id, actor_id, action, resource_type, resource_id, reason, ts

appeal
  id, review_case_id, submitted_by, submitted_at, reason,
  evidence_manifest_hash, assigned_to, state, outcome, decided_at

device
  id, org_id, enrollment_id, kind, credential_version,
  agent_version, os, camera_class, revoked_at

consent_record
  id, org_id, enrollment_id, exam_id, policy_version,
  disclosure_version, grants_json, accepted_at

precheck_result
  id, org_id, session_id, capability, required, status, detail, checked_at

status_transition
  id, org_id, session_id, dimension, from_state, to_state, cause, ts
```

Event `type` allowlist (reject unknown at the gateway):  
`SESSION_START`, `SESSION_END`, `HEARTBEAT`, `VIOLATION`, `WARNING`, `NETWORK`, `AUDIO`, `TAMPERED`, `INFO`, `METRICS` (optional, sampled), `PRECHECK`, `PHONE_PAIR`, `CLIP_READY`.

Do not uplink raw process path lists as unbounded `INFO` blobs without a schema.

---

## 7. Protocol (agent ↔ gateway)

Control/events use a versioned JSON envelope:
`{ "v": 1, "op": "...", "session_id": "...", ... }`. Camera bytes never
travel through the control WebSocket. Snapshots/clips use short-lived
presigned object-storage uploads; live tracks use the SFU.

**Agent → server**

| op | Purpose |
|---|---|
| `register` | agent enrollment token, exam code, fingerprint, consent, capabilities, attestation |
| `heartbeat` | monotonic counter, status, last_seq, battery/cpu optional |
| `event` | one WAL batch; server replies `ack` with `batch_id` |
| `media_upload_request` | metadata, size, hash and kind; server returns constrained presigned URL |
| `media_upload_complete` | object key + hash; ingest verifies and links it to the event |

**Server → agent**

| op | Purpose |
|---|---|
| `registered` | server `session_id`, revocable session credential, policy pack, content_url |
| `command` | see command set above |
| `ack` | compact WAL |
| `nack` | temporary: retain/retry; permanent: includes durable rejection id, marks evidence incomplete, and permits cursor advance across that rejected sequence |
| `media_upload_grant` | one object key, content type, size cap and short expiry |
| `error` | auth / policy / rate limit |

Heartbeats every 5 s. Miss 3 → console shows `disconnected`; agent replays WAL
on reconnect. Event ACK is **cumulative through the highest contiguous
`seq_no`**; the agent compacts only that prefix. Gaps stay unacknowledged.
The cursor advances across a permanently rejected sequence only after the agent
receives a terminal `nack` containing the server's durable rejection ID; the
payload is moved to a quarantine log retained with the session audit.
Reconnect retries use exponential backoff with full jitter (1–60 s). Commands
carry an idempotency key, expected session version, precondition and expiry.
Agents retain command idempotency results through exam retention + 30 days.

---

## 8. Scale path (do not skip rungs)

| Rung | Concurrent sessions | Topology |
|---|---|---|
| **A — lab only** | 1 exam, ≤30 students, 1 controller | 1 Node process, 1 Postgres, local disk clips; not approved for remote production |
| **R — remote launch** | 1 exam, ≤30 students, controller + invigilators | Postgres, object storage, durable commands/audit, authenticated gateway, health panel; SFU+TURN when phone/live media is required |
| **B — department** | 5 exams, ≤200 students, several controllers | 2+ stateless WS gateways, Redis pub/sub, S3/R2, load balancer, SFU+TURN |
| **C — campus** | ~1000 sessions | Gateway autoscaling, Redis cluster or sharded presence, event table partitioned, horizontally scaled SFU, no full-record video |

Rung A is a lab integration target only. Rung R is the first shippable
**remote product**. Rung C is a capacity exercise after a load test of B.

**Load-test contract (before calling it B):**  
200 fake agents, 5 s heartbeats, 2 Hz sampled metrics, 0.2 fps snapshots,
5 controllers, 20 concurrent on-watch feeds, reconnect storm of all agents,
and one gateway restart. Budget: p95 command dispatch < 500 ms, no acknowledged
event loss, no duplicate `(session_id, seq_no)`, grid presence stale < 15 s,
and predicted Postgres/object-store growth per exam hour.

---

## 9. Phased work (what to build, in order)

Workstreams can overlap, but **do not build the React grid on top of the in-memory store.**

### Phase 0 — Agent is a trustworthy device (blocker)

Fix what the audit already named. Otherwise you scale garbage.

- Shared `Lock` in `ai/audio.py`; lock `get_latest_frame()`.
- Enforce consent; fail-closed.
- Bind phone WS to localhost or PIN-pair; no open `0.0.0.0` in product.
- `utils.paths` for logger, dashboard, YOLO.
- Webcam/WebRTC release on stop.
- Allowlist process-kill; drop Escape-exits-exam.
- `wss://` only in product.
- Disable Google STT by default.
- Replace the generated `CHEAT DETECTED/CLEAN` verdict with an observable-event
  summary. The current Isolation Forest may remain a diagnostic novelty signal,
  never an adjudication.

### Phase 1 — Control plane

- Postgres schema above; staff auth; one-time agent enrollment tokens.
- REST: create exam, roster import, list sessions, issue `EXAM_START`/`END` as stored commands.
- Delete the unauthenticated `POST /api/exams` and public `GET /api/sessions/:id/events`.

### Phase 2 — Bidirectional agent protocol

- Register with token; server-issued session id.
- Command consumer on the agent; lock-down and scoring **wait** for `EXAM_START`.
- Presence in Redis (or in-process at rung A).
- WAL ack + replay against Postgres unique `(session_id, seq_no)`.

### Phase 3 — Controller console (this is the product)

- Live grid + student drawer + warn/kick/end.
- Low-rate snapshots in grid via object storage. The drawer shows timeline and
  latest snapshots; live-video controls remain disabled until Phase 4.
- Command center with exam, media, storage, gateway and agent readiness.
- Candidate-group assignments plus claim, note, resolve, escalate and shift
  handoff so multiple invigilators do not duplicate or miss work.
- Review screen after `EXAM_END`.

### Phase 4 — Remote phone

- Signaling + SFU + TURN; phone and laptop both clients of the cloud.
- LAN discovery becomes optional fast-path, not required.
- Enable authorized on-watch laptop/phone/screen subscriptions in the student
  drawer, with per-controller and per-organization concurrency quotas.

### Phase 5 — Video policy + ring buffer

- Snapshot cadence and incident clips. Laptop agent keeps a 30 s encrypted ring
  buffer; phone keeps 15 s when the OS permits background buffering. When it
  does not, the UI clearly marks retrospective phone clips unavailable.
- `REQUEST_CLIP` grants one constrained presigned upload; no media traverses
  the control gateway.
- Full-record mode as an exam flag, with a warning in the admin UI about bandwidth.

### Phase 6 — Rung B hardening

- Second gateway + Redis fanout.
- Object storage lifecycle (30/90 day).
- k6/locust fake-agent tests plus media/SFU load test in CI.
- Signed agent builds + shipped integrity manifest (stop first-run bootstrap).

### Explicitly later (not required to “manage everything”)

- Kafka/Redpanda
- Per-student Isolation Forest in the cloud
- 3D room SLAM
- Continuous FaceNet auth
- Keystroke logging (legal/consent landmine; only if a named customer requires it)

---

## 10. Mapping from today’s files

| Today | Fate |
|---|---|
| `main.py` | Split: `agent` service entry + optional `--dev-ui`. Product entry does not start an invigilator dashboard. |
| `screen/proctor_thread.py` | Keep as edge pipeline; start/stop scoring on commands; emit schema’d events. |
| `screen/safe_browser.py` | Thin student shell; commands from server; no `CMD:KILL` of arbitrary PIDs. |
| `network/server.py` | Demote to optional local phone bridge; default off when cloud phone is paired. |
| `agent/uplink.py` + `journal.py` | Become the only server client; add command loop and clip upload. |
| `server/src/index.js` | Split into `api/`, `gateway/`, `jobs/`. Stop treating it as one file. |
| `server/src/store.js` | Replace. Do not “swap Mongo behind Map.” |
| `admin/public/index.html` | Replace with React console. |
| `assets/dashboard.html` | Student shell only, or retire in favor of a small Qt/HTML status view. |
| `pp_platform/` | Keep; **read** every consent field; integrity manifest shipped not bootstrapped. |
| `rules/thresholds.py` | Policy pack from server overlays local YAML. |

---

## 11. What “done” means (acceptance)

A controller can, without SSH and without pasting a session id:

1. Create an exam, import 30 students, start the exam.
2. See 30 cells update within 5 s of each agent heartbeat.
3. Open one student, see a timeline, subscribe to live video, send WARN, see the banner on the student machine, end that session.
4. Restart the server mid-exam; agents reconnect, WAL replays, no duplicate `seq_no`, console recovers the grid.
5. After end, review clips for flagged students only; unflagged students have snapshots + events, not hours of video.

Until those five are true, the system is still the laptop appliance with a sidecar.

---

## 12. Implementation note for other agents

Do not implement this plan as one PR. Suggested first PR after Phase 0:
**Postgres + agent-enrollment-token REGISTER + staff authentication**, with the
existing uplink speaking the new `register` contract and the old HTML page
temporarily using a logged-in cookie. Grid UI is PR two.

Do not add Kafka, a second language on the agent, or cloud-side YOLO in those PRs.

---

## 13. Command center: check the whole exam in one click

The controller's default screen is an **exam command center**, not a video wall.
It must answer three questions without opening a student:

1. Can this exam start safely?
2. Is the cohort healthy now?
3. What needs a human decision?

### 13.1 Top-level exam status

| Group | Required statistics |
|---|---|
| Roster | enrolled, joined, ready, blocked, absent, late |
| Session state | lifecycle counts (`registered/ready/live/paused/ended/terminated`), connectivity counts (`connected/degraded/disconnected`), and attention counts (`normal/flagged/review_pending`) |
| Devices | laptop camera healthy, phone paired, mic available, screen permission, attestation passed |
| Human workload | unassigned alerts, claimed alerts, oldest unreviewed alert, controller-to-live-student ratio |
| Commands | pending, acknowledged, failed, p50/p95 acknowledgement latency |
| Network | agents with poor RTT/loss, reconnects in last 5 min, stale heartbeats, TURN-relayed feeds |
| Media | live subscriptions, failed camera tracks, snapshot age p95, incident clips pending/failed |
| Integrity | sequence gaps, duplicate batches, clock skew, tampered agents, policy mismatch |
| Infrastructure | API, gateway, Redis, Postgres, object storage, SFU/TURN health |
| Capacity | active WS / configured limit, ingest events/s, object uploads/s, DB write latency, media egress |

Show a single derived state:

- **Ready** — all required dependencies healthy; start permitted.
- **Degraded** — exam can continue; named feature is unavailable (for example
  snapshots delayed but event ingest healthy).
- **Blocked** — required consent/device missing before start, event durability
  unavailable, or authorization invalid.
- **Incident** — acknowledged event loss, widespread disconnect, database
  failure, or media/control compromise.

The state must include causes and actions. A green/red dot without an
explanation is not operational tooling.

### 13.2 One-click actions

- **Run readiness check** — validates services, policy, roster tokens, storage,
  SFU capacity, and each joined agent.
- **Start ready students** — starts only sessions that satisfy the exam's
  required capabilities; blocked rows show exact causes.
- **Open attention queue** — sorted by severity, confidence, age and whether a
  controller has claimed it.
- **Export diagnostics** — redacted exam/session IDs, service versions, health,
  command results and gap report. No images/audio unless separately selected
  and authorized.
- **Pause / resume exam** — idempotent command with a progress panel. It must
  show partial success and allow retry for disconnected students.
- **End exam** — step-up auth, reason, confirmation, per-session acknowledgements,
  and automatic close when agents reconnect.

### 13.3 Student detail statistics

The student drawer shows current values and trends, not only violation text:

- heartbeat age, RTT, reconnect count, last acknowledged `seq_no`;
- camera/phone/screen track health and last snapshot time;
- CPU, memory, capture FPS and inference latency (sampled, not every frame);
- face count, no-face seconds, head/gaze-away seconds and longest streak;
- restricted-object detections, focus-loss count/duration, monitor changes;
- audio-activity seconds and cross-device mismatch count (no transcript by
  default);
- current rule/fusion contributions with policy/model versions;
- controller actions and agent acknowledgement;
- incident clips and reviewer disposition.

### 13.4 Platform/operator view

The platform operator needs a separate deployment view. Controllers should not
see cross-tenant capacity or secrets.

- service version and deployment health;
- WS connections by gateway and tenant;
- event ingest, ack latency, retry and dead-letter rate;
- Postgres connections/write p95/replication lag;
- Redis memory/evictions/pub-sub lag;
- object-store error rate and lifecycle backlog;
- SFU participants, packet loss, bitrate and TURN egress;
- authentication failures and authorization denials;
- alerting status and current incidents.

---

## 14. Failure model and minimal-bug rules

Scalability includes predictable degradation. Every operation crossing a
network boundary needs an idempotency key, timeout, retry policy and visible
terminal state.

| Failure | Required behavior |
|---|---|
| Student internet loss | Agent continues local scoring and WAL; UI shows offline; reconnect replays events and pending command receipts. Do not auto-fail. |
| Phone disconnect | If optional, continue degraded. If required, start a default 120 s grace timer, alert the controller, then auto-pause or continue-awaiting-decision according to the policy fixed before start. Never classify this as misconduct. |
| Controller browser closes | Exam continues. Watch leases expire. Reopening reconstructs state from Postgres + presence. |
| WS gateway restarts | Clients reconnect with jitter; any replica accepts them; fresh heartbeats rebuild presence and pending outbox rows resume fanout. No sticky-session dependency. |
| Redis unavailable | Durable writes continue. Cross-gateway live fanout is marked degraded (Redis pub/sub cannot replay); each gateway serves its local clients only. On recovery, console rebuilds state from Postgres plus fresh heartbeats. |
| Postgres unavailable | Agents retain WAL and receive no event ACK. New state-changing controller commands are rejected because they cannot be durably audited; only commands already claimed/dispatched before the outage can complete. Agents keep the current exam locally. |
| Object storage unavailable | Events continue; clips remain in encrypted local spool with retry. Stop snapshots first at 80% media-spool use; preserve incident clips. At 100%, mark evidence incomplete—never silently claim full evidence. |
| SFU/TURN unavailable | Events/snapshots continue; live view shows unavailable. It must not stop the exam. |
| Duplicate/reordered event | Unique `(session_id, seq_no)` makes ingest idempotent; gaps and late arrivals are explicit. |
| Duplicate command | Agent stores `idempotency_key` and returns the prior result; START/END never execute twice. |
| Clock skew | Server records receive time; agent sends monotonic offset and wall time; ordering uses sequence number, not client clock alone. |
| Agent crash/reboot | Signed service restarts, re-registers, restores exam/WAL state, and requests reconciliation. If server lifecycle is `live/paused`, policy requires controller resume or explicitly configured auto-resume; if `ended/terminated`, unlock and flush only. |
| Bad model/policy rollout | Version pinned per exam; canary before exam; no mid-exam change unless explicitly commanded and audited. |
| Regional outage | At campus scale, new sessions route to a healthy region; active agents continue offline and reconnect. Multi-region active-active is later, not launch scope. |

### 14.1 Engineering constraints

- Explicit session state machine; reject invalid transitions.
- Schema-version every protocol message and event.
- At-least-once delivery + idempotent consumers; never pretend WebSocket is a
  queue.
- Transactional outbox for DB change → live fanout, so a committed command or
  alert is not lost between Postgres and Redis.
- Bounded queues, memory, local spool and media upload concurrency.
- Backpressure: reduce snapshots first; never drop command receipts or
  violation events.
- Reserve 512 MB per active session for the event WAL and 2 GB for media.
  At 80% event-WAL use, stop sampled `METRICS`; at 95%, stop noncritical
  `INFO`. Violation, integrity and command-receipt events retain priority.
  “No event loss” is guaranteed only inside the tested 24-hour offline
  envelope; exceeding storage is an explicit `EVIDENCE_INCOMPLETE` incident,
  not a hidden success.
- Structured logs with `org_id`, `exam_id`, `session_id`, `request_id` and
  `model_version`; redact student content.
- Feature flags and canaries for agent, server policy and model releases.
- Database migrations are backwards-compatible with the previous agent/server
  protocol version.

### 14.2 Service objectives

Initial targets to validate in load tests:

| Capability | Target |
|---|---|
| Agent/control availability during an exam | 99.9% monthly; exam-local WAL covers transient outage |
| Acknowledged event durability | No loss in fault-injection tests |
| Presence freshness | 99% of connected sessions updated within 15 s |
| Command dispatch | p95 < 500 ms; acknowledgement p95 < 5 s on healthy agents |
| Attention alert fanout | p95 < 2 s after durable ingest |
| Command-center initial load | p95 < 3 s for 1000-session exam using pagination/virtualization |
| Snapshot freshness | p95 < 15 s in presence mode |
| Recovery | Gateway loss < 60 s reconnect; no manual state repair |

These are product SLOs, not promises until measured by the fake-agent and
fault-injection suites.

---

## 15. ML for post-exam review

### 15.1 What the current data can and cannot do

Current runtime `METRICS` rows contain:

`gaze_h`, `gaze_v`, `head_yaw`, `head_pitch`, `yaw_diff`, `pitch_diff`,
`face_count`, `phone_face`, `phone_yaw`, `phone_pitch`, `gaze_direction`,
`screen_region`, `on_screen`, `looking_at_phone`, `phone_distance_cm`,
`vad_prob`, `lip_prob`, `fused_score`, `fused_status`, `head_away`,
`gaze_away`, and `is_looking_away`.

There are currently **no real session logs under `data/` in this checkout**.
The tracked model was trained from generated or previously external data whose
provenance is not recorded here.

Before collecting training data, version the telemetry schema and record a
stable pseudonymous candidate group, exam/institution split key, device/camera
class, OS/agent version, detector/model versions, policy version, calibration
quality, modality availability and missingness reason. Keep direct identity in
a separately protected system; training tables receive only pseudonymous join
keys.

The existing pipelines are useful as simulators and baselines, but they are
not a valid cheating model:

- `generate_synthetic_data.py` assigns `CLEAN/SUSPICIOUS/CHEATING` from the
  simulator profile that also generates the features. It proves pipeline
  behavior; it does not provide real-world truth.
- `is_looking_away`, `head_away`, `gaze_away`, `fused_score` and
  `fused_status` are outputs of the same current rules. Training on them to
  predict a report produced by those rules is **target leakage**.
- `AdvancedAnomalyDetector` fits one Isolation Forest to the same student's
  session with `contamination=0.1`. It will mark roughly a fixed tail as
  anomalous even in a clean session and its score is not a cheating
  probability.
- Frame rows are autocorrelated. Random row splitting puts adjacent frames from
  the same person/exam in train and test, producing misleading scores.
- A session verdict (`CLEAN/CHEATING`) is too coarse and cannot identify which
  10-second interval a reviewer should inspect.

**Therefore:** ML must rank reviewable time windows and explain observable
signals. It must not automatically convict a student.

### 15.2 Prediction unit and labels

Use a **10-second window with 5-second stride**, grouped into incidents.
Store raw detector outputs at 2 Hz and aggregate:

- mean/max/std and percentiles of head/gaze angles and detector confidence;
- seconds and longest consecutive streak for no-face, multi-face, head-away,
  gaze-away and audio mismatch;
- object detections by class/confidence;
- focus-loss duration, process/network/hardware events;
- phone/screen/camera availability, packet loss and missing-data masks;
- changes from the candidate's first-five-minute baseline;
- time in exam and question/page context only when the exam platform legally
  provides it.

Label **observable events**, not intent:

| Label | Meaning |
|---|---|
| `no_issue` | No reviewable event in the window |
| `face_absent`, `multiple_people` | Camera evidence |
| `restricted_object`, `phone_use` | Object/phone evidence |
| `sustained_look_away` | Attention evidence; not cheating by itself |
| `focus_or_app_switch` | Desktop evidence |
| `audio_other_speaker` | Audio detector/evidence; no transcript required |
| `device_or_feed_tamper` | Integrity evidence |
| `technical_failure` | Network/camera/model failure, explicitly not misconduct |
| `insufficient_evidence` | Reviewer cannot decide |

Separately record a reviewer **disposition**:
`dismissed`, `needs_more_review`, `policy_violation_confirmed`, or
`technical_issue`. Do not use “cheating” as a training label unless the
institution has a formal adjudicated outcome and appeal process.

### 15.3 Annotation workflow

1. Rules create candidate windows plus a random sample of apparently clean
   windows. Sampling clean windows is required to estimate false positives.
   Persist each sampling probability so evaluation can correct verification
   bias and recover natural prevalence.
2. Annotation UI shows only the minimum clip, synchronized telemetry, policy
   and detector explanation.
3. Annotators are initially blinded to machine verdict/score to reduce
   anchoring. Two independent reviewers label high-severity and
   model-disagreement windows. A third adjudicates disagreements.
4. Capture label, confidence, reason codes, evidence sufficiency and technical
   quality. Never silently convert the current generated report into ground
   truth.
5. Measure inter-annotator agreement per label. Ambiguous labels are merged or
   clarified before training.
6. Keep an immutable link from every label to annotation guideline version and
   evidence hash.

ML annotators receive de-identified segments and cannot browse the roster or
full session.

Before submitting a label, an annotation reviewer cannot see the live
invigilator's action, label, note or identity; the alert-selection reason; the
current rule/model score; or another reviewer's answer. They may see the
applicable exam policy, synchronized raw evidence, sensor health and missingness.
Two independent reviews are mandatory for high-severity evidence, model/rule
disagreements, gold-test candidates and any consequential disposition.
Agreement produces `verified`; disagreement produces `needs_adjudication`; an
independent senior reviewer appends the `gold` revision.

### 15.4 Model sequence

**Stage 0 — no learned enforcement:** deterministic rules + human review.
Instrument missingness and create labels.

**Stage 1 — review ranker:** calibrated gradient-boosted trees over window
aggregates. This is preferred over a neural sequence model initially because
the dataset will be small, mixed numeric/categorical, and explanations matter.
Train one-vs-rest event heads or a multi-label classifier, then a separate
priority ranker from those probabilities plus policy severity.

Also train/evaluate an **evidence-quality head** (`reviewable` vs
`insufficient_evidence`) and perform deterministic temporal incident grouping.
Session prioritization may aggregate confirmed-window probabilities, but is
never a misconduct probability.

Do not feed `fused_score`, `fused_status`, rule-generated labels, session
verdict, reviewer assignment, or post-event controller action into the model.
They are leakage or policy, not independent evidence. Raw detector confidences
may be used only if versioned.

**Stage 2 — temporal model:** after enough reviewed windows across exams and
devices, compare the tree baseline against a temporal convolution/transformer
using sequences plus missing-data masks. Ship it only if it materially improves
held-out precision/recall and calibration.

**Stage 3 — multimodal specialist models:** improve individual detectors
(phone/object, multiple people, speaker presence) with consented clips. Their
outputs remain evidence for the review ranker. Avoid one opaque
video-to-“cheating” model.

Synthetic data is suitable for unit tests, rare sensor-state augmentation and
pretraining detector robustness. It must be capped in supervised batches and
never appear in production validation or headline metrics.

### 15.5 Splits, metrics and release gates

Split at the **exam and identity-connected-component level**, never frame:

- all sessions from one exam remain in one split;
- within pre-cutoff data, sessions linked by the same pseudonymous candidate or
  device are a connected component and stay together;
- validation contains disjoint components and exams;
- temporal test contains whole exams after a fixed cutoff. Repeated
  candidates/devices are reported as a separate slice; headline
  generalization uses unseen candidates/devices;
- keep a separate unseen-institution/device-domain holdout when sample size
  permits;
- persist split assignments. Appending data never reassigns an existing
  component;
- after repeated model-selection cycles, retire the old test set to
  retrospective monitoring and seal a newer time-based test set before further
  tuning;
- final shadow evaluation uses complete later exams not used for threshold
  tuning.

Version and stratify by camera quality, skin-tone/lighting bins where law and
consent permit, glasses/head coverings, device class, bandwidth, accommodation
status, exam type and institution. Fairness evaluation must not expose these
attributes to controllers.

Primary metrics:

- precision@K and confirmed incidents per 100 reviewed windows;
- recall of adjudicated observable events;
- false alerts per student-hour and median reviewer minutes per exam;
- area under precision-recall curve (class imbalance);
- calibration (Brier score / expected calibration error);
- per-label confusion and technical-failure false-positive rate;
- subgroup false-positive/false-negative gaps with confidence intervals;
- percentage of incidents with sufficient evidence;
- operational lift over the existing rules at the **same review budget**.

Release only when:

1. it beats the rule baseline on a locked test set and review-budget metric;
2. calibration threshold is selected on validation, not test;
3. subgroup limits and minimum sample requirements pass;
4. model artifact, feature schema, detector versions, data snapshot and code
   commit are registered;
5. shadow mode shows no unacceptable drift for at least one exam cycle;
6. rollback is one config change and old models remain reproducible.

### 15.6 Model serving and review UX

Run window feature extraction on the edge or ingest worker, then score
asynchronously after durable event ingest. The live exam must not depend on the
review model. Store:

- `model_name`, `model_version`, `feature_schema_version`;
- calibrated per-label probabilities;
- top contributing observable signals;
- threshold/policy version;
- missing modalities and evidence references.

The review queue sorts by expected review value, not a red “cheating score”.
Reviewers see “phone-use evidence 0.82; phone visible 6.2 s; clip available”,
not “82% cheater”. Their disposition is written back as future training data,
subject to quality checks.

### 15.7 Data governance and drift

- Consent and policy define whether images/audio may be retained for model
  improvement separately from exam evidence.
- Encrypt media; restrict annotation access; log every view; delete on the
  shorter of legal/exam/model-retention policy.
- Keep derived features only when their retention purpose is documented.
- Monitor detector missingness, feature distributions, alert rate, reviewer
  acceptance and calibration by model/detector/policy version.
- Retrain on a schedule only after label quality and drift review. More data is
  not automatically better.

---

## 16. Revised delivery gates

| Gate | Must be true before proceeding |
|---|---|
| **G0 trustworthy edge** | Phase 0 audit bugs fixed; consent enforced; deterministic shutdown/recovery tests |
| **G1 remote exam MVP** | RBAC, agent enrollment + phone pairing tokens, durable events, bidirectional commands, readiness check, 30-agent fault test |
| **G2 controller product** | Command center, grid/drawer, watch leases, audit actions, review queue |
| **G3 media scale** | SFU+TURN, direct object uploads, ring buffer, 20 simultaneous view test |
| **G4 200-seat release** | 200-agent reconnect storm, gateway restart, dependency fault injection, SLO dashboard |
| **G5 ML shadow** | Human annotation set, leakage-free group/time test, calibrated ranker in shadow only |
| **G6 assisted review** | Measured review-time lift, subgroup gates, model registry and instant rollback |

This ordering keeps live exam execution independent of ML and live media. A
failure in the reviewer model or SFU must degrade observation, not terminate an
exam or lose the event audit trail.

---

## 17. Resolved architecture decisions

These choices are normative so separate teams do not implement incompatible
interpretations.

### 17.1 Health ownership and precedence

- Each service owns an authenticated `/health/live` and `/health/ready`.
- A health aggregator polls dependencies every 10 s, keeps an in-process
  snapshot, writes live state to Redis with 30 s TTL, and persists a
  last-known snapshot to Postgres every minute. The command center normally
  receives `/console` updates; if Redis/fanout fails, it polls the aggregator
  directly through the authenticated Control API. This path can report Redis
  itself as failed.
- Precedence is `Incident > Blocked > Degraded > Ready`.
- **Ready:** all exam-required prechecks pass, durable ingest and command audit
  are ready, at least one controller is assigned, and capacity quotas remain.
- **Blocked:** before start, any required device/consent/policy check fails or
  Postgres/durable ingest is unavailable.
- **Degraded:** an optional modality or live-view/media function is unavailable,
  or <5% of live sessions are disconnected, while durable events continue.
- **Incident:** acknowledged event loss/evidence overflow, security compromise,
  durable store unavailable during a live exam, or ≥5% of live sessions
  disconnected for 60 s. Thresholds are policy/config values and changes are
  audited.

### 17.2 Media quotas and security

- Laptop, screen and phone each publish a separate SFU track. The student
  drawer subscribes only to selected tracks.
- Rung B acceptance tests 20 simultaneous watched students. Initial product
  quota: one watched student per controller and 20 per organization; admin can
  raise it only after capacity validation.
- Presigned uploads permit one generated object key, exact content type,
  declared hash, maximum size and ≤5-minute expiry. Completion verifies size
  and hash before linking evidence.
- Media is encrypted in transit and at rest. Tenant/object prefixes are
  authorization boundaries, never trusted identifiers from clients.
- Staff access tokens are short-lived; refresh sessions, agent credentials and
  phone pairing tokens are independently revocable. Re-enrollment invalidates
  the previous device credential.
- Support access requires an org-admin grant, ticket/reason and expiry; media
  access requires a second explicit grant.
- CI includes cross-tenant object, API, WebSocket and SFU subscription tests.

### 17.3 Database recovery and fanout

- Rung B uses managed Multi-AZ Postgres with point-in-time recovery and daily
  restore verification. Initial recovery objectives: transaction RPO near zero
  for zonal failover, backup RPO ≤5 min, service RTO ≤30 min. These remain
  targets until restore drills prove them.
- An outbox worker claims rows with leases and publishes to Redis. If Redis is
  down, rows remain pending. Pub/sub itself is not replayable.
- Outbox command/fanout rows retry with exponential jitter until their command
  expiry (or 24 h for non-command notifications), then become durably `failed`
  with an operator-visible reason.
- A transient event-ingest failure receives no ACK and remains in the agent
  WAL. A permanently invalid event is recorded in an `event_rejection` table
  with session, sequence, payload hash and reason; the server sends a terminal
  NACK, the agent quarantines it, and the session is marked
  `EVIDENCE_INCOMPLETE`. The contiguous cursor may advance across only such
  durably recorded rejections.
- Media completion retries stop after 10 attempts or 24 h and enter a durable
  dead-letter table. No path silently discards evidence.
- Object-store inventory and DB media index are reconciled daily.

### 17.4 Retention defaults

Institution policy and law may shorten these. Product defaults:

| Data | Default |
|---|---|
| Presence snapshots | 7 days, unless referenced by a review case; referenced evidence is retained through the appeal deadline |
| Raw sampled telemetry | 30 days |
| Incident clips and exam events | 90 days |
| Review dispositions / derived case features | 180 days |
| Security and administrative audit actions | 1 year |
| Acknowledged local agent spool | delete within 24 h |
| Consented de-identified training windows | 1 year, then re-approve or delete |

When an original review disposition is issued, its evidence manifest is frozen
through the appeal deadline (default 14 days), even if a normal snapshot TTL
would expire sooner. A submitted appeal extends that freeze through resolution.
Data-subject export/deletion requests respect institutional records obligations
and preserve non-content security audit entries where legally required.

### 17.5 ML approval gates

The ML owner trains and documents a candidate; a reviewer-operations owner and
privacy/fairness approver authorize shadow deployment. Only the exam product
owner may enable assisted ranking. Platform operators may rollback immediately.

Initial gates for each major shipped label:

- locked test set has at least 500 adjudicated positive and 1,000 negative
  windows; otherwise the label stays experimental;
- at the same review volume, precision@K improves ≥10% relative to rules while
  recall is no worse by more than 2 percentage points;
- expected calibration error ≤0.05;
- each reported subgroup has at least 200 positive and 500 negative adjudicated
  windows. The upper 95% confidence bound must keep the absolute false-positive
  gap ≤3 percentage points and false-negative gap ≤5 percentage points against
  the overall population. Insufficient samples block claims and automatic
  thresholds for that group;
- metrics are prevalence-weighted to the intended exam population, not the
  annotation queue's enriched alert rate;
- annotators are blinded to current rule/model score and identity where
  possible, but see evidence quality and the applicable policy.

These numerical gates are starting governance thresholds, not proof of
fairness. Revisit them with real prevalence, legal review and reviewer capacity.

---

## 18. Human findings → reusable training data

### 18.1 Two kinds of human signal

A live invigilator sees rule/model alerts, operates under time pressure, and may
not inspect full context. Their finding is valuable but **not automatically
ground truth**.

| Source | Training status | Reason |
|---|---|---|
| Live invigilator finding | `provisional` | Fast operational judgment; exposed to current alert score |
| Post-exam reviewer label | `reviewed` | More context, but may still be one person's interpretation |
| Two-reviewer agreement | `verified` | Suitable for most supervised training |
| Adjudicator / completed appeal | `gold` | Highest-trust outcome; preserve prior labels rather than overwrite |
| Student/system report | `reported` | Useful for sampling and technical diagnosis, not a target |

The model trains only on label states allowed by the dataset policy. Initial
production training uses `verified` and `gold`; `provisional` findings drive
sampling and active learning.

### 18.2 Finding capture in the live controller

When an invigilator watches a candidate, the UI provides structured actions:

- `confirm_observable`, `dismiss`, `technical_issue`, `permitted_context`,
  `insufficient_evidence`, `escalate`;
- observable label(s), start/end time, severity, confidence and reason code;
- free-text note as supporting context, never the model target;
- synchronized evidence references (laptop camera, phone, screen, telemetry);
- rule/model/policy/detector versions visible when the finding was created;
- whether the finding originated from an alert, random quality-control window,
  or human observation without an alert.

Creating a finding automatically freezes the minimal evidence segment and
creates a post-exam review case. Edits append label revisions; they never
replace history.

```
live observation
  -> provisional finding
  -> post-exam blinded review
  -> second review when required
  -> adjudication / appeal
  -> immutable label revision
  -> eligible dataset snapshot
```

### 18.3 Annotation entities

Extend the data model:

```
finding
  id, org_id, exam_id, session_id, source, created_by,
  window_start_ms, window_end_ms, observable_labels,
  action, confidence, reason_codes, note,
  evidence_manifest_hash, policy_version, detector_versions,
  controlling_command_id, post_intervention, created_at

label_revision
  id, finding_id, parent_revision_id, state,
  labels, disposition, evidence_quality, annotator_id,
  actor_role, guideline_version, queue_source, selection_probability,
  selecting_rule_version, selecting_model_version,
  score_was_visible, identity_was_visible, modalities_viewed,
  review_started_at, submitted_at, confidence, reason_codes, created_at

review_assignment
  id, finding_id, reviewer_id, assignment_reason,
  blinded, status, assigned_at, completed_at
```

Training exports exclude direct identity, free-text notes, controller identity
and current model/rule scores. Those remain available only for audit and bias
analysis under stricter access.

### 18.4 Prevent feedback poisoning

- Never treat “controller clicked confirm” as a final label.
- Measure reviewers' agreement and per-guideline confusion, not reviewer
  productivity by confirmation rate.
- Send uncertain, novel, model/rule-disagreement and random-negative windows to
  review. Random negatives prevent a dataset containing only existing alerts.
- Keep a stable random 5–10% quality-control stream that ranking models cannot
  suppress.
- Separate the model that selected a sample from the label; persist selection
  probability and reason so evaluation can correct selection bias.
- Do not train on an exam until its review/appeal cutoff or explicitly mark the
  dataset snapshot as pre-adjudication.
- Quarantine labels from compromised accounts, policy incidents or abnormal
  confirmation patterns until audited.
- Maintain reverse lineage from every label revision to dataset manifests and
  model releases. Quarantining a used label marks those releases `tainted`,
  suspends their production alias, rolls back to the last clean model, and
  triggers impact analysis. Retrain only when the removed labels materially
  affect the released dataset or metrics.

### 18.5 Active learning and delayed outcomes

Initial annotation-batch mix:

- 40% model uncertainty or model/rule disagreement;
- 20% rare labels and underrepresented device/environment domains;
- 20% diversity samples across feature clusters;
- 20% uniform random windows for prevalence and false-positive estimation.

Apply per-exam, candidate, institution and device caps so one noisy source
cannot dominate. Hidden gold windows measure reviewer consistency. Windows
after a `WARN`, pause or other intervention are marked `post_intervention` and
excluded from ordinary observational training unless the model explicitly
accounts for the intervention.

Freeze the selector model for batch N; only eligible labels from N may train
N+1. Pending/appealed findings are censored, not treated as negative. Monitor
time-to-adjudication by label, score, subgroup and queue source because
difficult cases mature later and otherwise bias recent training snapshots.

---

## 19. Incremental data platform (no full reprocessing for every exam)

The operational Postgres database is not the training dataset. Build an
append-only analytical path:

```
Agent events / media
       |
       v
RAW (immutable)             object storage JSONL/media, partitioned by date/exam
       |
       v  incremental normalizer, checkpoint = server ingest_offset
CURATED EVENTS              typed Parquet, schema_version preserved
       |
       v  window feature job only for new/changed partitions
FEATURES                    one row per 10 s window + feature_schema_version
       +----------------------------+
       |                            |
       v                            v
LABEL REVISIONS             DATASET MANIFEST
append-only Postgres/Parquet exact feature partitions + eligible label revisions
                                    |
                                    v
                              TRAIN / VALIDATE
```

### 19.1 Storage layers

| Layer | Contents | Mutation rule |
|---|---|---|
| Raw | Original versioned event envelopes and consented evidence | Immutable; append new session partitions |
| Curated | Typed, deduplicated events; missingness retained | New output partition per normalizer version |
| Feature | 10-second window aggregates keyed by session/window/schema | Copy-on-write partition generation; never modify an object pinned by a manifest |
| Label | Findings and label revisions | Append-only revision graph |
| Dataset | Manifest of exact feature files, labels, filters and split assignments | Immutable once used for an experiment/release |
| Model registry | Artifact, calibration, code commit, manifest ID and metrics | Immutable versions; aliases move |

Start with compressed Parquet files and a manifest table. Adopt Iceberg/Delta
only when concurrent writers, large-scale time travel or partition management
actually require it.

### 19.2 Incremental processing

- A session closes with a durable `SESSION_END`; normal finalization waits for
  a 24-hour allowed-lateness period. Urgent review may use a preliminary
  generation clearly marked non-final.
- Raw ingest assigns an immutable server `ingest_offset`. The normalizer
  consumes offsets after its checkpoint, not only `seq > last_seq`, so a late
  arrival below the prior sequence watermark is still observed.
- `(session_id, seq_no, payload_hash)` is immutable. A correction is a new
  record with `supersedes_event_id`; deletion is a tombstone. Neither overwrites
  raw history.
- Feature jobs record source partition hashes and
  `feature_schema_version`. A new exam computes only its own windows.
- A late/corrected event expands invalidation through all overlapping
  10-second windows and adjacent incident-grouping context. If it changes
  calibration or the first-five-minute baseline, all dependent windows in that
  session receive a new feature generation.
- Changing feature logic creates a new feature version. Rebuild only when a
  model requests that version; write new immutable physical objects and never
  overwrite objects referenced by old manifests.
- A label change does **not** recompute features. A new dataset manifest joins
  the existing feature partition to the latest eligible label revision.
- Split assignment is persisted by pseudonymous candidate/exam/institution.
  Adding new data cannot move old test sessions into training.
- Every job is idempotent, content-hashed and restartable. Failed partitions
  are visible; “partially processed” is never silently promoted.

This means the next exam contributes new raw, curated, feature and label
partitions. Retraining scans the selected feature partitions, not camera media
or all historical JSONL.

### 19.3 Dataset manifest

Every training run must pin:

- snapshot ID, parent snapshot and label/adjudication cutoff;
- raw/curated/feature schema and generator versions;
- exact partition/object hashes and row counts;
- window size/stride, canonical null semantics and categorical vocabularies;
- latest eligible label revision IDs and guideline versions;
- natural-prevalence and selection weights;
- real/synthetic source and synthetic scenario/seed;
- group/time split assignment;
- included exams/sessions, exclusion reasons, prevalence, missingness and
  subgroup coverage;
- consent/retention eligibility timestamp;
- code commit and dependency lock hash.

If any input is not reproducible from the manifest, the model cannot be
promoted.

### 19.4 Fresh-exam workflow

1. During the exam, events append to raw storage and provisional findings are
   captured.
2. At session close, incremental normalization and window features run once.
3. Active-learning policy selects alerts, uncertain windows and random
   negatives for post-exam review.
4. Review/adjudication appends label revisions.
5. The training scheduler checks minimum new verified labels, drift and
   consent. It does **not** retrain after every exam automatically.
6. When triggered, create a new dataset manifest referencing old unchanged
   feature partitions plus the new exam partitions.
7. Train challenger, evaluate on locked temporal test, then shadow/canary.

### 19.5 Schema governance

- Event and feature schemas live in a reviewed registry with an owner,
  canonical types/units, required/optional fields and compatibility tests.
- Feature versions use semantic rules: patch = implementation correction with
  identical meaning; minor = additive compatible fields; major = changed
  windowing, normalization, missingness or semantics.
- Additive optional fields are backward compatible. Unit/type changes require a
  new major schema and normalizer.
- Unsupported schema versions are quarantined with a terminal ingest finding;
  they are not coerced silently.
- Ordering uses server ingest offset and session sequence. Durations use client
  monotonic time when valid; wall time is display metadata and clock skew is a
  feature/quality signal.
- Every normalizer/feature generation pins source code commit, dependency lock
  and container/environment digest so an old generation can be reproduced.

### 19.6 Retention versus reproducibility

Privacy deletion overrides model reproducibility. A promoted tabular model pins
lawfully retained de-identified feature/label snapshots, not raw identity or
media. Each release records `rebuildable_until`. If consent withdrawal or
retention deletes required inputs, lineage marks the release non-rebuildable
and the owner must retire or retrain it by policy. Cryptographic manifests and
model cards remain for audit, but they do not justify retaining personal data.

---

## 20. Improving the synthetic-data generator

### 20.1 Current strengths

- deterministic sessions and seeds;
- resumable generation with `.done`;
- temporal trajectories rather than independent random rows;
- production geometry, smoothing, triangulation and fusion are exercised;
- metrics schema is close to the runtime schema;
- optional images/audio can test evidence plumbing.

Keep these properties.

### 20.2 Current weaknesses

The current `CLEAN`, `SUSPICIOUS` and `CHEATING` profiles jointly control head
trajectories, face visibility, phone events, audio, apps, room changes and the
final verdict. This creates separable stereotypes instead of realistic
behavior. In particular:

- `CLEAN` has only a near-neutral head state while legitimate candidates also
  read, think, stretch, speak, use permitted scratch paper and briefly leave
  frame;
- “cheating” profiles automatically receive more of almost every violation,
  so a model can classify the profile from event volume;
- thresholds generate both features and labels (`head_away`,
  `is_looking_away`, `fused_score`), producing leakage;
- `train_frame_model.py` explicitly includes `fused_score`, discards missing or
  `-1` rows, randomly samples autocorrelated frames, and evaluates on its
  training rows;
- profile-specific duration ranges leak the generated verdict;
- each Ornstein-Uhlenbeck segment restarts pose from zero, creating
  discontinuities at behavior-state boundaries; gaze is mostly independent
  Gaussian noise plus one-frame saccades rather than reading trajectories;
- profile fields such as `phone_turn_prob`, `phone_miss_prob`,
  `multi_face_run_s` and `external_voice_prob` are declared but not consumed by
  the current trajectory/generation path, so configuration implies variation
  that is not present;
- one nominal head geometry, camera model and simple office background
  underrepresent real devices, lighting, compression and appearance;
- fast geometry metrics come from projected landmarks rather than running the
  actual face/gaze/object detectors on rendered pixels. Object violations are
  also not consistently connected to the fusion input;
- frame drops, clock drift, reconnects, detector outages, calibration failure
  and correlated missing data are mostly absent;
- synthetic reports assign session verdict/confidence without human evidence;
- `.done` is keyed by seed/index rather than a full configuration/code hash, so
  changed generator settings can silently reuse stale sessions;
- rich rendering is selected with `index < rich_sessions`, coupling the visual
  domain to early synthetic timestamps/session IDs;
- generated evaluation on the same simulator validates the simulator, not
  production accuracy.

### 20.3 Factorized scenario design

Replace verdict profiles with independent latent components:

1. **Behavior timeline** — reading, thinking, typing, stretching, looking at
   permitted materials, phone attention, second person, absence.
2. **Environment** — lighting, background motion/noise, room layout and
   permitted/prohibited objects.
3. **Device domain** — resolution, FPS, focal length/FOV, camera placement,
   compression, blur, rolling shutter, exposure and microphone response.
4. **Transport/health** — packet loss, latency, reconnect, duplicated/reordered
   events, dropped frames, sensor permission loss and clock skew.
5. **Detector observation model** — misses, false positives, confidence
   calibration, version-specific bias and modality missingness.
6. **Policy context** — whether scratch paper, reading aloud, phone presence or
   a second person/accommodation is permitted.
7. **Observable truth timeline** — event labels and exact intervals, independent
   of current rules.

Do not generate a `CHEATING` label. Generate observable truths and technical
conditions. Policy disposition can be computed separately for workflow tests,
never used as ML ground truth.

Write two separate streams:

- `latent_truth.jsonl` — exact observable intervals, causal state, uncertainty
  and evidence availability;
- `events.jsonl` — noisy detector measurements and rule outputs.

This separation measures detector false positives/negatives instead of teaching
a model to reproduce its own thresholds.

A scenario constraint validator rejects impossible combinations and records the
accepted component/domain versions. Examples: a phone-camera truth requires a
configured phone source; a detector output cannot exist while that detector is
offline; policy changes affect disposition but never observable truth.

Use semi-Markov observable-event arrivals with empirical duration
distributions. Preserve pose and velocity across state boundaries. Model
reading scan paths, writing/desk glances, fatigue and accessibility behavior.
Phone interaction should have correlated phases—object/hand presence, eye
shift, head shift, interaction and recovery—rather than independent flags.

### 20.4 Counterfactual and hard-negative generation

Generate paired sessions where only one factor changes:

- same head movement with phone present vs absent;
- same gaze trajectory toward permitted paper vs prohibited phone;
- face absent because candidate left vs camera froze;
- speech from candidate vs another speaker;
- multiple people vs a poster/video/reflection false positive;
- focus loss from intentional app switch vs OS permission/update dialog;
- normal dark skin/low light/glasses glare vs camera obstruction;
- network spike from exam upload/update vs prohibited remote-control traffic.

These pairs force models to use relevant evidence rather than event count or
profile identity. Every pair has a stable `pair_id`, changed-factor declaration
and common base seed. All members of a pair remain in the same train/validation
split.

### 20.5 Realism and domain randomization

- Fit dwell times, transitions, noise/autocorrelation and missingness from
  consented real telemetry, stratified by device domain—not from final
  dispositions.
- Randomize camera intrinsics/extrinsics, placement, resolution, FPS, JPEG/video
  compression, lighting direction/color, blur, occlusion and head geometry.
- Include calibration drift, glasses/head coverings, skin-tone/lighting
  combinations and mobility/accommodation behaviors. Synthetic diversity is
  not a substitute for real subgroup evaluation.
- Model detector versions explicitly so synthetic rows contain realistic
  confidence and failure distributions.
- Simulate missing-at-random and event-correlated missingness; never discard
  incomplete rows from training.
- Add burst/reconnect tests, clip boundaries and pre/post-roll alignment so
  synthetic data validates the complete evidence pipeline.
- Choose rich/closed-loop rendering independently from session index/date so
  image availability cannot become a temporal shortcut.
- Provide two explicit modes: `geometry_fast` for pipeline/load regression and
  `closed_loop_rendered` where actual production detectors process rendered
  pixels/audio. Only closed-loop examples may train pixel/audio detector
  models.

Use licensed/consented source assets or procedurally generated identities.
Never build synthetic faces from retained candidate biometrics without a
separate lawful purpose and consent.

### 20.6 Validation against reality

Maintain a versioned synthetic quality report:

- real vs synthetic feature distributions and missingness;
- autocorrelation, dwell-time and event-duration distributions;
- detector confidence/reliability by condition;
- a classifier's ability to distinguish real from synthetic (high accuracy
  means the domain gap remains large);
- train-synthetic/test-real and train-real/test-real comparisons;
- performance on counterfactual pairs and known hard negatives.

Initial CI gates (recalibrate after enough real data):

- Jensen-Shannon divergence ≤0.10 for each core normalized feature;
- absolute missingness-rate difference ≤5 percentage points per modality;
- median event-duration relative error ≤20%;
- first-10-lag autocorrelation mean absolute error ≤0.10;
- real-vs-synthetic classifier AUROC ≤0.75 on held-out source groups;
- adding synthetic data may reduce real-only validation PR-AUC by at most
  1 percentage point and should improve targeted rare-condition recall by at
  least 5 percentage points.

Failure means the synthetic version remains valid for load/regression tests but
is ineligible for supervised model training.

No synthetic row appears in the locked real production test set.

### 20.7 Mixing policy

- Use synthetic data freely for schema, load, regression and rare-state tests.
- For supervised models, start with real data as the majority and cap synthetic
  windows at 20% of a training batch; tune downward/upward only on real
  validation.
- Weight by source/scenario and report metrics with synthetic removed.
- Match source/domain sampling to the intended real population; intentional
  rare-scenario oversampling records an inverse-probability weight.
- Keep generator version, seed group and `pair_id` together in one development
  split. Synthetic data never determines real validation/test thresholds.
- Pretrain low-level specialist detectors on synthetic/rich renders, then
  calibrate and fine-tune on consented real data.
- Never use synthetic session verdicts, generated report confidence or current
  fusion/rule outputs as targets.

### 20.8 Implementation order

1. Introduce `scenario_manifest.json` with component seeds, domains, observable
   truth intervals, pair IDs, configuration hash, code commit, dependency lock
   and generator version. A `.done` cache hit is valid only when that full hash
   matches.
2. Replace verdict profiles with factorized behavior/environment/device/policy
   components while retaining old profiles only as regression fixtures.
3. Add missingness, sensor failures, reconnect/clock and detector observation
   models.
4. Produce counterfactual pairs and hard-negative suites.
5. Export typed Parquet windows with source, scenario and truth metadata.
6. Add `closed_loop_rendered` detector execution and connect generated objects
   to actual detector/fusion outputs.
7. Build the real-vs-synthetic quality report and enforce the numeric CI gates.
8. Only then use synthetic windows as a controlled fraction of review-model
   training.
