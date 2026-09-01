# Phone-Proctor — Detailed Implementation Plan

**Status:** proposed execution plan  
**Depends on:** `docs/controller-scale-plan.md`  
**Target:** secure 30-candidate remote exam first; 200 and 1,000 only after measured gates  
**Date:** 2026-08-31

This document translates the architecture into implementable work. It defines
the approach, target modules, contracts, database changes, delivery sequence,
tests and release gates.

---

## 1. Delivery approach

### 1.1 Use a strangler migration

Do not rewrite the AI pipeline. Preserve the working local modules:

- `face/`, `gaze/`, `fusion/`, `rules/`;
- camera, object detection and on-device audio/VAD;
- `ProctorThread` processing behavior;
- write-ahead journal concept.

Replace the product shell around them:

- `main.py` becomes an agent bootstrap and session supervisor;
- the Qt page becomes a minimal student exam/status shell;
- the Node scaffold becomes a durable authenticated control plane;
- the static admin page becomes a controller console;
- LAN phone discovery becomes an optional local optimization.

Keep the current local MVP behind an explicit development flag until the remote
vertical slice is complete. Do not maintain two production paths.

### 1.2 Build contracts before screens

The first shared deliverable is a versioned contract package:

```
contracts/
  v1/
    openapi.yaml
    envelope.schema.json
    register.schema.json
    heartbeat.schema.json
    event.schema.json
    ack.schema.json
    nack.schema.json
    command.schema.json
    command-result.schema.json
    media-upload.schema.json
    policy.schema.json
    health.schema.json
    console-snapshot.schema.json
    console-delta.schema.json
    event-payloads/
  registries/
    permissions.json
    errors.json
    lifecycle-transitions.json
  examples/
  compatibility/
```

JSON Schema is the canonical definition.

- Node validates with AJV and exposes generated TypeScript types.
- Python validates with Pydantic models generated or maintained against the same
  fixtures.
- CI runs every example through both validators.
- Unknown major versions are rejected; additive optional fields remain
  compatible within a major version.
- OpenAPI is the canonical REST contract and generates the console client.
- The permission, error, event-type and state-transition registries are
  versioned contracts, not duplicated enums in each application.
- Console snapshots and deltas share an exam stream cursor as defined in §6.6.

### 1.3 Deliver a thin vertical slice first

The first complete flow is:

```
staff login
  -> create exam
  -> add one enrollment
  -> redeem agent token
  -> agent precheck/READY
  -> controller EXAM_START
  -> one durable event + cumulative ACK
  -> heartbeat in live grid
  -> controller EXAM_END
  -> agent completion receipt
```

No phone, live video, ML or Redis is needed to prove this slice. Postgres is
required from the beginning. The temporary controller for this slice may be a
tested API client; the production console arrives in Track D.

### 1.4 Keep the first server as a modular monolith

Use one TypeScript codebase with independently runnable processes:

- `api` — REST, staff sessions, RBAC;
- `gateway` — authenticated agent and console WebSockets;
- `worker` — outbox, health snapshots, retention and media reconciliation;
- `console` — React static build.

They share domain code and Postgres. This avoids premature microservices while
allowing API/gateway/worker replicas to scale separately. The gateway owns
online delivery. The worker owns expiry, retry bookkeeping, retention and
reconciliation; it never assumes it owns a WebSocket.

### 1.5 Buy or reuse high-risk infrastructure

Do not build these:

- identity provider — integrate OIDC authorization-code + PKCE;
- WebRTC SFU/TURN — use LiveKit (managed or self-hosted);
- object storage — use S3-compatible storage;
- database HA — use managed Postgres for production.

Custom code should implement exam policy and evidence workflows, not passwords,
media routing or storage replication.

---

## 2. Target repository layout

```
Phone-Proctor/
  contracts/                   # canonical protocol schemas and fixtures

  agent/
    bootstrap.py               # product entry
    config.py
    supervisor.py              # session state machine
    credentials.py             # OS-protected device credential
    protocol/
      models.py
      client.py                # WSS register/reconnect/read/write
      commands.py
    storage/
      event_wal.py
      command_receipts.py
      media_spool.py
    media/
      snapshots.py
      ring_buffer.py
      livekit_publisher.py
    health.py
    policy.py

  screen/
    proctor_thread.py          # retained edge pipeline
    student_shell.py           # replaces observer/debug dashboard in product

  server/
    src/
      entrypoints/
        api.ts
        gateway.ts
        worker.ts
      config/
      auth/
      db/
        migrations/
        repositories/
        transaction.ts
      domain/
        exams/
        enrollments/
        sessions/
        events/
        commands/
        findings/
        reviews/
        appeals/
        media/
      http/v1/
      gateway/
      outbox/
      presence/
      health/
      media/
      audit/
      observability/
    test/
      unit/
      integration/
      contract/
    Dockerfile

  admin/
    src/
      app/
      auth/
      api/
      realtime/
      pages/
        Login/
        Exams/
        ExamSetup/
        CommandCenter/
        Review/
        Appeals/
        PlatformHealth/
      components/
        LiveGrid/
        AttentionQueue/
        StudentDrawer/
        MediaViewer/
        CommandProgress/
        HealthSummary/
      permissions/
    test/

  data_pipeline/
    schemas/
    normalize/
    features/
    labels/
    manifests/
    training/
    synthetic/

  load/
    fake_agent/
    scenarios/
    media/

  deploy/
    compose/
    migrations/
    dashboards/
    runbooks/
```

Do not move AI modules during the first phases. Import them from their current
paths until the remote lifecycle is stable.

---

## 3. Technology choices

| Area | Choice | Reason |
|---|---|---|
| Server | Node 20+ LTS, TypeScript, Express, `ws` | Retains current stack; adds types without a framework rewrite |
| Validation | JSON Schema + AJV; Pydantic in Python | One protocol contract |
| Database | PostgreSQL | Transactions, constraints, JSONB, outbox, partitioning |
| Migrations | SQL migrations executed in CI/deploy | Reviewable and portable |
| DB access | `pg` with repository functions | Minimal abstraction; explicit transactions |
| Staff auth | OIDC; same-origin secure session cookie | Avoid custom password/auth implementation |
| Agent auth | One-time enrollment exchange → revocable device credential | Reconnect without reusing enrollment token |
| Presence/fanout | Redis after the one-node vertical slice | Not a source of truth |
| Media | S3-compatible object storage + presigned URLs | Bypasses control gateway |
| Live media | LiveKit SFU + TURN | Proven fanout/connectivity |
| Console | React + TypeScript + Vite | Replaces static scaffold |
| Server state | TanStack Query + small realtime reducer | Separate REST truth from WS deltas |
| Tests | Node test runner/Vitest, pytest, Playwright, Testcontainers | Unit, contract, integration and E2E |
| Observability | structured JSON logs + OpenTelemetry + Prometheus-compatible metrics | Correlated diagnosis without high-cardinality metrics |
| Data | immutable Parquet + manifest table | Incremental/reproducible without a lakehouse initially |

Pin exact production dependency versions through lockfiles. Upgrade in isolated
dependency PRs with contract/integration tests.

---

## 4. State machines

### 4.1 Exam lifecycle

```
DRAFT -> SCHEDULED -> OPEN -> LIVE <-> PAUSED -> ENDED
  |         |          |       |
  +-------> CANCELLED <-+-------+
```

Rules:

- only `exam_owner/controller` can perform configured transitions;
- expected exam version is required for every mutation;
- `END` is terminal; reopening creates a new attempt, not state rollback;
- scheduled jobs use the same command service as humans.

### 4.2 Agent session lifecycle

```
UNENROLLED
  -> ENROLLING
  -> REGISTERED
  -> PRECHECK
  -> READY
  -> STARTING
  -> LIVE <-> PAUSED
  -> ENDING
  -> ENDED
```

Additional terminal/error states:

- `BLOCKED` — required consent/capability/policy failed before start;
- `TERMINATED` — controller ended this candidate;
- `RECOVERING` — agent restarted and is reconciling state;
- `ERROR` — unrecoverable local fault, with explicit reason.

Connectivity and attention are separate dimensions:

- connectivity: `connected|degraded|disconnected`;
- attention: `normal|flagged|review_pending`.

The supervisor is the only code allowed to transition lifecycle. AI threads
emit observations; they do not decide exam state.

Persist two lifecycle values:

- `desired_lifecycle_state` — authoritative control-plane intent;
- `observed_lifecycle_state` — last state durably reported by the agent.

Each desired-state change increments `control_generation`. Agent results include
that generation. The UI shows transitions such as `starting` while desired is
`LIVE` and observed is still `READY`; it must not claim the candidate is live
until the agent reports it. On reconnect, the server sends desired state and
generation. An older command result cannot overwrite a newer generation.

Recovery rules:

- desired `ENDED|TERMINATED` always causes local stop/unlock/flush;
- desired `PAUSED` restores the shell and scoring to paused;
- desired `LIVE` after an agent reboot enters `RECOVERING`; default policy
  requires a controller resume, while an exam may explicitly allow auto-resume;
- connection takeover increments `connection_generation`; messages from the
  displaced connection are rejected.

### 4.3 Command lifecycle

```
PENDING -> DISPATCHED -> RECEIVED -> RUNNING -> SUCCEEDED
    |          |            |          |
    +-------> EXPIRED / FAILED / CANCELLED
```

Each command contains:

- `command_id`, `idempotency_key`, schema version;
- `exam_id`, optional `session_id`;
- issuer, reason and audit context;
- expected exam/session generation and allowed source states;
- issue/expiry timestamps;
- payload and policy version.

Receipt and completion are separate acknowledgements. The agent stores the
result by idempotency key and returns the previous result on duplicate delivery.

---

## 5. Database implementation

### 5.1 Migration order

Do not create the entire final schema in one migration.

#### Migration 001 — tenancy and staff

- `organization`
- `user_account`
- `organization_membership`
- `org_role_assignment`
- `staff_auth_session`
- `oidc_login_transaction`
- `support_grant`
- `audit_action`

Constraints:

- normalized unique email/issuer subject;
- role assignment scope type/id and expiry;
- auth sessions store only hashed refresh/session material, key version, expiry
  and revocation/replay state;
- OIDC state, nonce and PKCE transactions are one-use and short-lived;
- all audit records append-only.

#### Migration 002 — exams and policy

- `exam`
- `policy_version`
- `candidate_group`
- `exam_staff_assignment`
- `candidate_group_staff_assignment`

Constraints:

- unique exam code per organization;
- immutable policy version after an exam becomes `OPEN`;
- optimistic `version` on exam;
- staff assignment references the same organization and exam;
- support grants carry ticket/reason/expiry and a separate media permission.

Do not implement a physical polymorphic `scope_type/scope_id` foreign key.
`role_assignment` remains a logical API concept backed by enforceable
organization, exam and candidate-group assignment tables.

#### Migration 003 — roster and enrollment

- `enrollment`
- `enrollment_token`
- `device`
- `device_credential_family`
- `device_refresh_token`
- `consent_record`

Constraints:

- unique `(exam_id, student_external_id)`;
- token stores peppered hash, expiry, use count and revocation—not plaintext;
- enrollment redemption is one transaction;
- rotating refresh tokens detect replay and revoke the credential family;
- signing/key version and last rotation are recorded;
- device credential version supports revocation.

#### Migration 004 — sessions and prechecks

- `session`
- `session_attempt`
- `precheck_result`
- `status_transition`

Constraints:

- server UUID session IDs;
- one active attempt per enrollment;
- partial unique index enforces one non-terminal attempt per enrollment;
- desired state, observed state, control generation, connection generation,
  connectivity and attention are separate columns;
- state-transition rows are append-only.

#### Migration 005 — durable events

- `event`
- `event_rejection`
- `ingest_cursor`

Indexes/constraints:

- unique `(session_id, seq_no)`;
- unique `batch_id`;
- payload hash persisted;
- indexes `(exam_id, server_ts)`, `(session_id, type, server_ts)`;
- partition by server date only after measured table growth warrants it.

#### Migration 006 — commands and outbox

- `command`
- `command_delivery`
- `outbox`
- `exam_stream`

Constraints:

- unique `(org_id, idempotency_key)`;
- expected generation and expiry required;
- outbox row created in the same transaction as command/state change;
- `exam_stream` has a monotonically increasing per-exam cursor and retained
  replay payload for console recovery;
- workers claim with `FOR UPDATE SKIP LOCKED`.

#### Migration 007 — media

- `media_asset`
- `media_upload`
- `evidence_manifest`
- `media_dead_letter`

Constraints:

- object key generated server-side;
- unique content hash within tenant where allowed;
- explicit upload state;
- expiry/retention/legal-hold fields.

#### Migration 008 — review and appeals

- `finding`
- `label_revision`
- `review_assignment`
- `review_case`
- `appeal`

Constraints:

- labels append revisions;
- two reviewers cannot be the same actor;
- appeal reviewer cannot be original decision maker;
- evidence-manifest hash freezes reviewed evidence.

#### Migration 009 — analytical lineage

- `data_partition`
- `feature_generation`
- `dataset_manifest`
- `dataset_manifest_item`
- `model_release`
- `model_lineage`

Migration ownership:

- B4a–B4c own 001–004;
- C4 owns 005;
- C6 owns 006;
- E1 owns 007;
- F1 owns 008;
- F3 owns 009.

Tenant foreign keys use composite `(org_id, id)` references where a child has
both values. RLS policies are introduced and tested in B8. Connection-pool code
must execute `SET LOCAL app.org_id` inside the same transaction as tenant
queries and reset on release; no session-wide setting may leak between pooled
requests.

### 5.2 Tenant isolation

Every tenant record includes `org_id`. Repository methods require an
`AuthContext` and always include organization scope.

Before remote release:

- enable PostgreSQL row-level security as defense-in-depth;
- set `app.org_id` inside each transaction;
- prohibit unscoped repository methods outside platform operations;
- test every REST, WS, object and LiveKit token path for cross-tenant access;
- never use candidate/session IDs as authorization.

### 5.3 Audit behavior

Audit:

- staff login/logout/session revocation;
- roster/token actions;
- every sensitive media read;
- every command and bulk command;
- policy changes/overrides;
- finding/review/appeal revisions;
- exports, deletion, support grants and model promotions.

Audit writes occur in the same transaction as the action where possible.
Database permissions and triggers deny update/delete of audit rows outside the
explicit retention job.

---

## 6. Server implementation

### 6.1 Configuration and bootstrap

Implement validated environment configuration:

- database/Redis/object-store/LiveKit URLs;
- OIDC issuer/audience/client;
- cookie and token keys;
- origin/CORS allowlist;
- limits (message size, upload size, connections, commands);
- retention and health thresholds.

The process refuses to start on missing production configuration. Development
defaults bind to `127.0.0.1`.

### 6.2 Staff authentication

Flow:

1. React redirects to OIDC authorization-code + PKCE.
2. API completes callback and creates encrypted, HttpOnly, Secure, SameSite
   session cookie.
3. API resolves issuer subject to organization memberships.
4. Authorization service checks permission + resource scope.
5. Console WebSocket authenticates via same-origin session and origin check.

Do not store access tokens in browser local storage.
All state-changing HTTP requests require a session-bound CSRF token and exact
allowed origin. WebSocket upgrades validate `Origin` and cannot substitute for
CSRF protection on REST routes.

High-impact actions use OIDC step-up:

- server starts a new authorization request with configured `acr_values` and
  `max_age`;
- callback verifies issuer, subject, nonce and returned authentication context;
- server records a short-lived recent-auth proof on the staff session;
- sensitive endpoints enforce that proof server-side;
- unsupported or failed step-up denies the action without creating a command.

### 6.3 Agent enrollment

1. Exam owner creates enrollment.
2. API creates high-entropy one-time enrollment token; database stores only
   peppered hash.
3. Agent posts token, capabilities, consent disclosure version and attestation.
4. Transaction validates exam window/token/policy, consumes token, creates
   session/device attempt, and returns:
   - server session ID;
   - short-lived access credential;
   - refresh credential stored only as hash server-side;
   - policy and content URL.
5. Agent stores refresh credential in OS-protected storage.
6. Re-enrollment/token reissue revokes old device credential.

Device fingerprint is diagnostic metadata, never authentication.

Phone pairing-token issuance and redemption is an early control-plane
capability independent of media. It creates a phone device attempt and
short-lived credential but does not require snapshot or LiveKit support.

### 6.4 REST API v1

Minimum endpoints:

```
GET    /api/v1/me
GET    /api/v1/permissions

POST   /api/v1/exams
GET    /api/v1/exams
GET    /api/v1/exams/:examId
PATCH  /api/v1/exams/:examId
POST   /api/v1/exams/:examId/roster:import
POST   /api/v1/exams/:examId/enrollments/:id/token:reissue
POST   /api/v1/exams/:examId/staff

GET    /api/v1/exams/:examId/readiness
GET    /api/v1/exams/:examId/sessions
GET    /api/v1/sessions/:sessionId
GET    /api/v1/sessions/:sessionId/events

POST   /api/v1/exams/:examId/commands
POST   /api/v1/sessions/:sessionId/commands
GET    /api/v1/commands/:commandId

POST   /api/v1/media/uploads
POST   /api/v1/media/uploads/:id:complete
POST   /api/v1/sessions/:sessionId/live-token

GET    /api/v1/exams/:examId/findings
POST   /api/v1/findings
POST   /api/v1/findings/:id/labels
POST   /api/v1/reviews/:id:submit
POST   /api/v1/appeals

GET    /api/v1/health/exams/:examId
GET    /api/v1/platform/health
```

Requirements:

- cursor pagination on lists;
- request/response schema validation;
- idempotency keys on create/import/command/upload grant;
- optimistic versions on exam/policy/review assignment;
- per-row result for bulk actions;
- stable typed error codes.

### 6.5 Agent WebSocket

Connection:

- WSS only in production;
- authenticate device access credential before upgrade;
- validate origin/header rules independently from browser WS;
- enforce one active connection generation per session;
- close replaced connection with explicit takeover reason;
- bounded message/frame size and per-session rate limits.

Message order:

1. `hello` with protocol versions;
2. `resume` with session generation, last event ACK and command receipt cursor;
3. server `resumed` with authoritative state/policy/pending commands;
4. heartbeats/events/results.

Before Redis, each gateway checks pending delivery rows for its connected
sessions on connect and by bounded polling. PostgreSQL `LISTEN/NOTIFY` is only a
wake-up hint; polling is the recovery mechanism. After Redis is introduced,
Redis provides the wake-up/routing hint, but undelivered commands remain in
Postgres and are still reconciled by polling. Workers mark expiry and retries;
only the gateway writes to live WebSockets.

Events:

- validate envelope and typed payload;
- insert idempotently;
- update contiguous cursor transactionally;
- create alert/outbox rows in same transaction;
- send cumulative ACK only after commit;
- invalid permanent payload creates `event_rejection` + terminal NACK.

### 6.6 Console WebSocket

One connection subscribes to an exam, not individual candidates.

Server emits:

- presence snapshots/deltas;
- lifecycle/connectivity/attention changes;
- finding/command state changes;
- exam health changes;
- media availability, not media bytes.

Every console-visible transaction appends one row to `exam_stream` with a
monotonic per-exam `stream_seq`. Rows are retained long enough for browser and
gateway recovery; Redis only wakes replicas.

Snapshot/delta protocol:

1. console requests an exam REST snapshot;
2. API builds the snapshot and reads its `stream_seq` watermark in one
   repeatable-read transaction;
3. console subscribes with `after_seq=<watermark>`;
4. gateway replays durable `exam_stream` rows greater than that watermark, then
   follows new rows;
5. every delta includes `stream_seq`; duplicates are ignored;
6. a gap, expired replay window or schema mismatch forces a fresh snapshot.

Gateway replica changes therefore do not lose state. Redis pub/sub never serves
as replay storage.

### 6.7 Command service

Creating a command:

1. authorize permission and resource scope;
2. validate lifecycle precondition;
3. insert command, audit and outbox in one transaction;
4. gateway discovers the durable delivery row and dispatches it to the active
   session generation;
5. agent persists receipt before execution;
6. agent sends `received`, then terminal result;
7. server updates delivery/command and fans out state.

Disconnected agents receive pending non-expired commands after resume. Exam end
is represented by authoritative server lifecycle as well as a command, so an
agent reconnecting after expiry still learns that the exam ended.

State-changing command completion compares both control and connection
generation. The desired state is committed when the command is accepted;
observed state changes only from the matching agent result. Timeout leaves the
two values visibly different and eligible for retry/reconciliation.

### 6.8 Presence and health

Postgres stores durable last heartbeat. Redis stores:

- connection owner/gateway;
- heartbeat/presence with TTL;
- watch leases;
- exam live-summary counters;
- fanout channels.

Metrics never use session/candidate IDs as labels.

Health aggregator calculates `Ready|Degraded|Blocked|Incident` from:

- dependency probes;
- exam-required prechecks;
- heartbeat/snapshot distributions;
- event gaps/WAL status;
- command failures;
- media/SFU capacity.

---

## 7. Python agent implementation

### 7.1 Fix the edge before connecting it

Complete these first:

- persistent shared audio lock;
- lock phone-frame/audio reads;
- deterministic camera, WebRTC, detector and thread shutdown;
- enforce every consent field;
- frozen-safe logger/dashboard/model paths;
- remove arbitrary PID termination and Escape exit;
- product mode requires `wss://`;
- disable Google transcription by default;
- replace automatic `CHEAT DETECTED` report with observable summary.

Add regression tests for each issue.

### 7.2 Introduce `AgentSupervisor`

Responsibilities:

- own lifecycle state;
- load product configuration and credential;
- connect/enroll/resume;
- run prechecks;
- start/pause/stop `ProctorThread`;
- forward policy versions into `Thresholds`;
- coordinate student shell;
- drain WAL and media spool;
- recover after restart.

`main.py` becomes:

1. parse product/dev configuration;
2. initialize logging and crash handling;
3. start `AgentSupervisor`;
4. start Qt event loop;
5. supervisor performs ordered shutdown.

No AI thread starts until authoritative `EXAM_START`.

Add a narrow `ObservationSink` adapter between retained code and the new
runtime. `ProctorThread` and loggers emit typed observations to the sink; the
sink validates and appends them to the WAL. A feature flag selects
`legacy_local` or `remote_managed` bootstrap, but both use the same observation
adapter. Retire direct `EventLogger -> AgentUplink` sending after C5 and remove
the production legacy path after the 30-seat release. Sampled `METRICS` must
also pass through this sink; the current selective uplink behavior cannot remain
the centralized feature-data source.

### 7.3 Replace `AgentUplink`

Implement these components:

- `ConnectionManager` — WSS, registration barrier, reconnect jitter;
- `ProtocolReader` — validation and dispatch;
- `ProtocolWriter` — bounded priority queue;
- `EventSender` — ordered WAL replay;
- `CommandReceiver` — persist-before-execute;
- `HeartbeatPublisher`;
- `CredentialRefresher`.

Priority:

1. command receipt/result;
2. integrity/violation events;
3. lifecycle/precheck;
4. regular events;
5. sampled metrics/snapshots.

Never silently drop from the queue. Low-priority items remain in WAL or are
explicitly suppressed under spool policy.

### 7.4 Upgrade the event WAL

Current per-batch rewrite is acceptable only for tests. Replace it with an
append-only SQLite WAL or segmented files with:

- sequence, batch ID, schema version and payload hash;
- status `pending|acked|rejected`;
- cumulative contiguous ACK cursor;
- quarantine record for terminal NACK;
- size/age accounting and priority;
- crash-safe compaction;
- migration from existing JSONL where possible.

SQLite is preferred for indexing and atomic cursor updates. Keep media in
separate files; do not put images in SQLite.

### 7.5 Durable command receipts

Persist:

- command envelope;
- received/started/completed timestamps;
- result/error;
- idempotency key and server session generation.

Execution maps commands to supervisor actions. Unknown or invalid-state
commands return typed failures without changing state.

Crash recovery is command-specific:

- `EXAM_START/RESUME` check persisted supervisor generation and whether capture
  workers already run before starting anything;
- `EXAM_PAUSE/END/KICK` are convergence operations and may safely repeat stop,
  flush and shell transitions;
- `WARN` stores banner ID/expiry, so replay updates the same banner;
- `REQUEST_CLIP` uses a deterministic evidence-bundle ID, so replay resumes the
  same upload;
- `UPDATE_POLICY` installs an immutable version and returns the already-active
  result on replay.

Persist `started` before invoking side effects and persist a recovery marker
after each irreversible step. On restart, reconcile incomplete receipts
against local supervisor state before reporting a terminal result.

### 7.6 Policy and consent

Server policy overlays bundled defaults but cannot enable a capability the
student did not consent to.

Precheck output contains:

- consent disclosure/grants;
- camera/mic/screen/phone availability;
- model/assets versions;
- storage free space and WAL/spool capacity;
- agent signature/manifest result;
- OS capability and permission;
- content URL reachability.

Required failure → `BLOCKED`. Optional failure → `READY` with degraded detail.

### 7.7 Student shell

Product UI contains only:

- enrollment/pairing flow;
- consent and prechecks;
- exam content;
- connection/camera/phone status;
- controller warnings;
- pause/end/completion state;
- support code and emergency exit process.

Remove AI debug scores, process lists and invigilator controls.

### 7.8 Agent health

Heartbeat samples:

- lifecycle/connectivity;
- last produced/acked event sequence;
- WAL/media spool size;
- capture/inference FPS and p95 inference time;
- CPU/memory/disk;
- modality and permission health;
- current policy/model/detector versions;
- clock offset estimate.

Use bounded sampling; do not send per-frame system metrics.

---

## 8. Controller console implementation

### 8.1 Application foundation

- React/TypeScript/Vite;
- same-origin OIDC session;
- generated API types;
- route-level permission guards;
- accessible component primitives;
- REST queries cached by resource/version;
- realtime reducer applies deltas after snapshot cursor;
- virtualized lists/grids for 1,000 candidates.

### 8.2 Screens in build order

#### Screen 1 — Login and organization context

- OIDC login/logout;
- active organization selector when applicable;
- session expiry/re-auth;
- permission diagnostics.

#### Screen 2 — Exam setup

- create/edit/schedule exam;
- immutable policy versions;
- roster CSV import with validation preview;
- token issue/reissue/revoke;
- staff and candidate-group assignment;
- readiness checklist.

#### Screen 3 — Command center

Top summary:

- roster/session/device counts;
- health state and named causes;
- attention workload and assignment;
- command failures/latency;
- connectivity/media/integrity;
- infrastructure/capacity visible by permission.

Actions:

- run readiness;
- start ready candidates;
- pause/resume/end with step-up confirmation;
- export redacted diagnostics;
- open attention queue.

Bulk actions show per-session state, partial failures and retry.

#### Screen 4 — Live grid

Each cell:

- display name/identifier;
- lifecycle, connectivity and attention;
- latest signed thumbnail;
- heartbeat/snapshot age;
- last observable event;
- invigilator claim/assignment.

No autoplay live video. Flagged/stale rows sort first.

#### Screen 5 — Student drawer

Tabs:

- overview/prechecks;
- synchronized timeline;
- laptop/phone/screen media;
- device/network health;
- command history;
- findings/review status.

Opening media creates an audit record and obtains a short-lived view token.

#### Screen 6 — Review and annotation

- one merged incident per card;
- synchronized evidence and telemetry;
- structured finding actions;
- blinded annotation mode;
- claim/assignment/double-review/adjudication;
- immutable revisions;
- appeals evidence freeze.

### 8.3 Multi-controller correctness

- watch/alert leases have TTL and explicit takeover;
- every mutation uses optimistic version;
- realtime conflicts refresh affected resource;
- notes append; they are not last-write-wins blobs;
- shift handoff transfers unresolved assignments transactionally.

---

## 9. Media implementation

### 9.1 Snapshots

1. Agent captures low-rate JPEG according to policy.
2. Request presigned upload grant with size/hash/type.
3. Upload directly to object storage.
4. Complete upload; server verifies metadata and records asset.
5. Console receives availability and requests signed thumbnail URL.

Stop snapshots first under bandwidth/storage backpressure.

Uploads remain `pending_verification` until object metadata, size, declared
hash and decodability are checked. Completion is idempotent and tolerates object
visibility delay. Invalid or malicious media is quarantined and never rendered
inline. Object keys are server-generated and tenant-prefixed.

### 9.2 Incident ring buffer

Initial implementation:

- keep JPEG frames in bounded encrypted local segments at policy FPS;
- laptop buffer 30 seconds; phone buffer 15 seconds when platform permits;
- on event/request, freeze pre/post-roll frame references;
- upload evidence bundle + manifest;
- media worker creates review-friendly MP4/HLS asynchronously;
- original frame hashes remain in evidence manifest.

This is easier to make deterministic than embedding FFmpeg into the first agent
release. Optimize encoding only after measuring CPU/disk cost.

E8 implements laptop evidence independently of phone or LiveKit. Phone
retrospective evidence is E9 and is required at launch only when exam policy
requires it. E10 implements retention, legal holds, dead-letter handling and
daily database/object inventory reconciliation.

### 9.3 Live view

- API authorizes `session.live_view`;
- API mints short-lived LiveKit room/track token;
- agent/phone publish only requested tracks;
- controller subscribes through SFU;
- one student per controller and organization quota enforced initially;
- start/stop/access are audited;
- live failure never stops event ingest or exam lifecycle.

### 9.4 Phone

Phone implementation order:

1. redeem short-lived pairing token;
2. register capabilities/consent;
3. heartbeat and sensor telemetry;
4. snapshot upload;
5. LiveKit camera publication;
6. local incident ring buffer;
7. reconnect/background/permission-loss handling.

LAN path stays disabled by default in product mode until authenticated pairing
and interface binding are implemented.

---

## 10. Data and ML implementation

### 10.1 Data path

Implement independently runnable, idempotent jobs:

1. `raw_export` — durable events → immutable object partitions;
2. `normalize` — typed Parquet by ingest offset/session revision;
3. `window_features` — 10-second/5-second stride copy-on-write partitions;
4. `label_export` — eligible immutable label revisions;
5. `dataset_manifest` — exact feature/label/split snapshot;
6. `train_challenger`;
7. `evaluate`;
8. `register_model`;
9. `shadow_score`.

Do not introduce an online feature store. Review scoring is asynchronous.

Raw export assigns immutable `ingest_offset` and stores corrections as
`supersedes_event_id` or tombstones; it never overwrites. Normalizer checkpoints
by ingest offset so late lower-sequence events are processed. Every job filters
by consent/retention eligibility, records source object hashes and writes
copy-on-write generations. Checkpoint advancement and partition registration
are transactional; partial objects are not promoted.

The event-ingest transaction also creates a raw-export outbox row. Exporters
claim offset ranges idempotently, upload compressed objects, verify hash/row
count, then register the object and advance the checkpoint. Do not dual-write
directly from the gateway to Postgres and object storage.

### 10.2 Human feedback

Live invigilator actions create provisional findings. Training uses verified or
gold labels only.

The annotation implementation must persist:

- queue source and selection probability;
- whether score/identity was visible;
- evidence modalities viewed;
- review duration and guideline version;
- post-intervention/command relation;
- parent/superseding revision;
- evidence hash.

Active-learning scheduler uses the documented 40/20/20/20 mixture and keeps
fixed random-quality-control sampling.

### 10.3 Synthetic generator refactor

Implement as separate PRs:

1. scenario manifest/hash and valid cache;
2. latent truth stream separate from noisy events;
3. factorized behavior/environment/device/transport/policy;
4. continuous semi-Markov trajectories;
5. missingness/failure/detector observation models;
6. counterfactual pair generation;
7. closed-loop rendered detector execution;
8. real-vs-synthetic quality report;
9. controlled synthetic mixing.

Old verdict profiles remain only as regression fixtures.

### 10.4 First review model

Input:

- versioned 10-second window aggregates;
- raw detector confidence and missingness;
- no `fused_score`, rule labels, session verdict or reviewer action.

Models:

- transparent rules baseline;
- regularized logistic baseline;
- calibrated gradient-boosted multi-label event heads;
- evidence-quality classifier;
- deterministic incident grouping;
- priority ranker from calibrated event probabilities + policy severity.

Output:

- observable-event probabilities;
- evidence-quality probability;
- top evidence contributions;
- missing modality warnings;
- model/feature/policy versions.

Never output a cheating probability.

### 10.5 Deployment

1. offline evaluation;
2. shadow score later complete exams;
3. compare against blinded reviewer results;
4. reviewer-assist experiment;
5. limited queue ranking;
6. monitored rollout with one-config rollback.

Live exam operation never depends on ML service availability.

---

## 11. Observability and operations

### 11.1 Logs

Structured fields:

- service/version/environment;
- request/trace ID;
- organization/exam/session IDs in logs only, never metric labels;
- command/event/media IDs;
- protocol/policy/model versions;
- error code and retry state.

Redact tokens, free-text student content, transcripts and process paths.

### 11.2 Metrics

Service:

- HTTP/WS connections, rate, errors and latency;
- event ingest/ACK/gap/rejection;
- command dispatch/receipt/completion;
- outbox depth/age/retries;
- Postgres/Redis/object/LiveKit dependency health;
- snapshot/clip upload and processing;
- reconnect and stale-presence rates.

Product:

- invited/joined/ready/blocked/started/completed;
- lifecycle/connectivity/attention counts;
- unclaimed/claimed/resolved findings;
- response/review duration;
- technical failures and evidence availability.

### 11.3 Runbooks

Create before remote launch:

- Postgres outage/restore;
- Redis outage/rebuild;
- gateway drain/restart;
- object-storage failure/backlog;
- LiveKit/TURN failure;
- OIDC outage;
- reconnect storm;
- agent disk full/WAL recovery;
- accidental exam end/pause;
- credential compromise/revocation;
- model rollback and tainted-label response.

---

## 12. Testing strategy

### 12.1 Test pyramid

**Contract tests**

- every JSON fixture validated in Python and TypeScript;
- forward/backward compatibility;
- max-size/unknown-version/invalid-state cases.

**Unit tests**

- state transitions;
- RBAC permission resolution;
- event cursor and terminal rejection;
- command idempotency/preconditions/expiry;
- policy/consent merge;
- feature windows/split assignment.

**Database integration**

- migrations up/down on clean DB;
- constraints and cross-tenant denial;
- concurrent token redemption;
- duplicate events/commands;
- outbox transaction/retry;
- review double-assignment/adjudication.

**Agent integration**

- crash at every WAL/ACK point;
- reconnect and cumulative compaction;
- duplicate command effects = zero;
- restart/reconciliation;
- resource cleanup and permission loss.

**End-to-end**

- OIDC test provider → exam creation → enrollment → fake/real agent → start →
  event → finding → end → review;
- two controllers with assignment/takeover;
- browser refresh and gateway restart;
- media access audit and expiry.

**Load/fault**

- 30-seat full-duration soak;
- 200 agents, five controllers, 20 watched sessions;
- simultaneous start/end;
- reconnect, alert and clip bursts;
- slow clients and packet loss;
- gateway termination;
- Redis/Postgres/object/LiveKit degradation;
- agent disk-full simulation;
- real encoded media for SFU tests.

### 12.2 CI lanes

On every PR:

- formatting/lint/type checks;
- Python and Node unit tests;
- contract compatibility;
- migration validation;
- dependency/security scan;
- changed-component integration tests.

Nightly:

- full integration;
- Playwright controller flows;
- package/frozen-agent smoke;
- synthetic property tests;
- 30-agent short load.

Release candidate:

- exam-duration soak;
- fault injection;
- backup restore;
- cross-tenant security suite;
- signed installer update/rollback;
- SLO report attached to release.

---

## 13. Sequenced PR plan

Each PR must be independently reviewable, keep tests green and avoid mixing
refactors with behavior changes.

### Track A — edge stabilization

| PR | Work | Depends on | Exit |
|---|---|---|---|
| A1 | Locks and deterministic shutdown | none | Race/resource regression tests |
| A2 | Consent enforcement and safe paths | A1 | Declined capabilities never start |
| A3 | Remove PID kill/insecure exit/Google STT; WSS product guard | A2 | Security tests |
| A4 | Observable session summary; remove automatic guilt verdict | A2 | Reports contain evidence only |
| A5 | Frozen packaging smoke, signed release/update/rollback pipeline | A1–A4 | Install, update and rollback evidence |

### Track B — contracts and server foundation

| PR | Work | Depends on | Exit |
|---|---|---|---|
| B1 | Protocol schemas, event/state/permission/error registries | none | Python/TS compatibility CI |
| B1b | OpenAPI and console snapshot/delta contracts | B1 | Generated client and cursor fixtures |
| B2 | TypeScript server bootstrap/config/logging | B1 | API/gateway/worker start separately |
| B3 | Docker dev: Postgres, object store, OIDC test provider | B2 | One-command local environment |
| B4a | Migration 001 + tenancy/staff repositories | B3 | Tenant/auth-session constraint tests |
| B4b | Migration 002 + exam/policy repositories | B4a | Policy/version constraint tests |
| B4c | Migrations 003–004 + enrollment/session repositories | B4b | Redemption/active-attempt constraint tests |
| B5 | OIDC staff sessions + CSRF/origin enforcement | B4a | State/nonce/PKCE/logout/replay/CSRF tests |
| B5b | Scoped RBAC + audit middleware | B5, B4b | Cross-tenant route tests |
| B5c | OIDC step-up proof and sensitive-action enforcement | B5b | `acr`/recent-auth denial and expiry tests |
| B6 | Enrollment exchange + device credentials | B4c, B5b | One-time/concurrent redemption tests |
| B6b | Phone pairing-token/device-credential flow | B6 | Pair/revoke/replay tests without media |
| B7 | Exam, roster, readiness and session REST APIs | B6, B1b | API-client vertical-slice setup |
| B8 | Composite tenant FKs, RLS and pooled-connection hardening | B7 | Data-layer cross-tenant suite |

### Track C — remote vertical slice

| PR | Work | Depends on | Exit |
|---|---|---|---|
| C1 | Agent supervisor/state machine skeleton | A1, B1 | AI does not start before command |
| C2 | Gateway register/resume/heartbeat | B6, B1b | Authenticated READY session |
| C3 | Agent protocol client/credential store | C1, C2 | Restart resumes credential/session |
| C4 | Migration 005 + durable event ingest/ACK/NACK | C2 | Zero duplicate/lost acknowledged event |
| C5 | SQLite/segmented WAL + ordered sender | C3, C4 | Crash/replay test matrix |
| C6 | Migration 006 + desired-state command service | B7, C4 | Durable dispatch/retry |
| C7 | Agent command receipts/execution | C5, C6 | START/PAUSE/END idempotent |

**Vertical-slice gate:** one real agent completes the flow in §1.3 through a
tested staff API client. D1/D2 replace that client with the product UI.

### Track D — controller product

| PR | Work | Depends on | Exit |
|---|---|---|---|
| D1 | React shell, login, permissions, API client | B5 | Authenticated routes |
| D2 | Exam/policy setup | B7, D1 | Versioned exam/policy can be created |
| D2b | Roster import/token/staff assignment | D2 | Readiness inputs can be created |
| D3 | Console WS snapshot+delta reducer | C6, D1 | Refresh/reconnect consistent |
| D4 | Readiness/health summary | C7, D2b, D3 | Blocked/degraded causes visible |
| D4b | Bulk command progress and step-up actions | B5c, D4 | Partial failures/retry visible |
| D5a | Assignment, claim, handoff and lease service/APIs | D2b, G1 | Concurrent takeover/expiry tests |
| D5b | Virtualized live grid + assignment UI | D3, D5a | 1,000 synthetic rows responsive |
| D6 | Student drawer/timeline/health/command history | D5b | One-click complete session view |

### Track E — media and phone

| PR | Work | Depends on | Exit |
|---|---|---|---|
| E1 | Migration 007 + constrained object uploads | C4 | Hash/size/type/access tests |
| E2 | Agent snapshots + media spool | E1, C5 | Backpressure/expiry tested |
| E3 | Signed thumbnails in grid/drawer | E2, D5b | No bytes through control WS |
| E4 | LiveKit auth/rooms/quotas/audit | D6 | Authorized test publisher/viewer |
| E5 | Agent laptop/screen publisher | E4 | Start/stop track audited |
| E6 | Phone heartbeat + snapshot using pairing credential | B6b, E1 | Remote phone precheck |
| E7 | Phone LiveKit track + reconnect | E4, E6 | Remote phone live view |
| E8 | Laptop ring buffer/evidence bundle/transcode | E1, C5 | Pre/post-roll laptop evidence |
| E9 | Phone ring buffer/evidence bundle | E6, E8 | Phone retrospective evidence when supported |
| E10 | Retention, legal hold, dead letter and inventory reconcile | E1, E8 | No silent media loss/orphans |

### Track F — review and ML data

| PR | Work | Depends on | Exit |
|---|---|---|---|
| F1 | Migration 008 + event-only finding/revision APIs | C4 | Append-only/double-review tests |
| F2 | Event-first review/annotation console | F1, D1 | Blinding and revision tests |
| F2b | Appeals and evidence freeze; media added progressively | F2, E8 | Independent appeal/freeze tests |
| F3 | Migration 009 + raw/normalized immutable partitions | C4, E1 | Offset/correction/consent tests |
| F4 | Copy-on-write window features + manifests | F1, F3 | New labels do not recompute features |
| F5 | Synthetic manifest/truth split/cache fix | B1 | Deterministic valid cache |
| F6 | Factorized behavior/environment/device/policy | F5 | Scenario constraint/property tests |
| F6b | Missingness, transport, detector and counterfactual models | F6 | Pair and failure-distribution tests |
| F7 | Closed-loop rendered mode | F6b | Actual detectors produce observations |
| F8 | Rules/logistic baselines + evidence-quality head | F4 | Leakage-safe locked evaluation |
| F8b | Calibrated event heads + priority ranker | F8 | Equal-budget challenger report |
| F9 | Shadow scoring/model registry/rollback | F8b | No live decision dependency |

### Track G — scale and operations

| PR | Work | Depends on | Exit |
|---|---|---|---|
| G0a | Production IaC, TLS/secrets, managed DB/object storage and restore automation | B3 | Staging deploy and restore evidence |
| G1 | Redis presence/fanout and distributed lease primitives | C6, D3 | Two gateways consistent |
| G2 | Health aggregator and platform view | G1, E4 | Redis failure still visible |
| G3 | Metrics, traces, dashboards and alert routing | B2, G2 | SLOs observable without PII labels |
| G4 | Fake-agent/controller/media load harness | C7, D5b, E5 | Reproducible normative workloads |
| G5 | Dependency fault suite and focused runbooks | G2, G3, G4 | Recovery procedures exercised |
| G6 | 30-seat soak + release-readiness aggregate | A5, B6b, B8, D4b, D5b, D6, E3, E8, E10, F2, G0a, G5 | All G0–G3 evidence + launch SLO report |
| G7 | 200-seat/two-gateway reconnect and media test | G6 | Department gate passes |
| G8 | Partitioning/autoscale only if measurements require | G7 | Evidence-based optimization |

---

## 14. Parallel work and critical path

Can start immediately in parallel:

- Track A edge fixes;
- B1 contracts;
- D1 console design system/auth shell mock;
- F5 synthetic manifest redesign;
- deployment/runbook skeleton.

Critical path:

```
B1 -> B1b -> B2/B3/B4 -> B5/B6/B7
                          |
                          v
                C1/C2/C3 -> C4/C5 -> C6/C7
                                      |
                          +-----------+-----------+
                          v                       v
                     D1/D2/D3                 G1 leases
                          |                       |
                          +--------> D4/D5a/D5b/D6
                                      |
                                      v
                         E1/E8/E10 + G2/G3
                                      |
                                      v
                              G4/G5 -> G6 remote launch
```

ML/review work may start after event schemas stabilize, but model deployment is
not on the remote-exam critical path.

### Recommended ownership

| Lane | Primary ownership | Mandatory cross-review |
|---|---|---|
| Architecture/contracts | schemas, state machines, compatibility, ADRs | server + agent + console leads |
| Server | API, Postgres, auth/RBAC, gateway, commands | security and platform |
| Agent | supervisor, WAL, policy, packaging, laptop media | server protocol owner |
| Console/product | setup, command center, grid, review UX | accessibility and operations |
| Mobile/media | phone, LiveKit, object/evidence processing | security/privacy and agent |
| Platform/SRE | environments, observability, load/fault, backup/restore | server and product owner |
| Data/ML/review ops | labels, partitions, synthetic, evaluation, registry | privacy/fairness and reviewer operations |

One person may cover multiple lanes at small team size, but protocol, security
and release evidence must not be self-approved by their only implementer.

---

## 15. Release gates

These names and numbers intentionally match `controller-scale-plan.md` §16.
The single-session vertical slice is an internal milestone inside G1, not a
separate architecture gate. The 1,000-seat exercise is a later capacity
milestone after G4.

### Gate 0 — trustworthy edge

- audit blocker fixes merged;
- no automatic misconduct verdict;
- consent and shutdown tests pass;
- frozen development-package smoke resolves all assets.

### Gate 1 — remote exam MVP

- single-session vertical slice passes first;
- RBAC, staff auth, agent enrollment and phone pairing tokens;
- server-issued session IDs and desired/observed state reconciliation;
- readiness check and durable bidirectional commands;
- event committed before ACK; restart/replay without duplicates;
- 30 fake-agent fault test with command/presence SLOs.

### Gate 2 — controller product

- exam setup/readiness/command center/live grid/student drawer;
- controller/invigilator assignment;
- candidate grouping, claims, notes, escalation and shift handoff;
- event-first findings and post-exam review queue;
- REST snapshot + durable console-delta recovery;
- multi-controller conflict/reconnect tests.

### Gate 3 — media scale

- object storage, constrained uploads and audited media access;
- laptop incident ring buffer; phone ring buffer when supported/required;
- SFU+TURN and track-level authorization;
- 20 simultaneous watched-session media test;
- retention/legal hold/dead-letter/reconciliation jobs;
- complete 30-seat exam-duration soak, dependency fault tests, signed installer
  rollback, dashboards, runbooks and backup restore before remote launch.

### Gate 4 — 200-seat release

- one or more concurrent exams totaling 200 agents, with a required five-exam
  scenario;
- five controllers, 20 watched sessions and tenant quotas;
- two gateways behind a load balancer and Redis fanout;
- all-agent reconnect storm plus gateway restart;
- managed Multi-AZ Postgres, PITR and restore evidence;
- command/event/media SLOs, database/object growth and noisy-neighbor controls;
- no acknowledged event loss.

### Gate 5 — ML shadow

- verified/gold labels;
- immutable manifest and leakage-safe splits;
- synthetic quality gates;
- model registry/lineage/rollback;
- shadow only.

### Gate 6 — reviewer assistance

- improvement at equal review budget;
- calibration/fairness/reviewer-time gates;
- reviewer and privacy approval;
- queue ranking only; no automated punishment.

### Capacity milestone — 1,000 seats

- admission control and explicit capacity;
- virtualized command center validated at 1,000 rows;
- partition/retention jobs proven from measured growth;
- gateway/SFU autoscaling and regional recovery exercise;
- full recording remains non-default.

### Normative load profiles

**G1, 30-agent fault test:** 30 agents and two staff consoles for at least 30
minutes, 5-second heartbeats, 0.2 snapshots/s where enabled, sampled metrics,
simultaneous start and end, one gateway restart and a reconnect of all agents.
Pass when p95
dispatch is under 500 ms, p95 healthy-agent completion acknowledgement is
under 5 s, connected presence is under 15 s stale, and no acknowledged event
is lost or duplicated.

**Remote-launch soak after G3:** 30 agents for the maximum supported exam
duration plus 30 minutes, controller refresh/reconnect, gateway restart,
temporary Redis/object/SFU outage, 24-hour-equivalent WAL pressure and signed
installer rollback. Event durability follows the tested offline envelope;
unavailable media must be explicit, never silent.

**G4, 200-seat profile:** five exams, 200 total agents, 5-second heartbeats,
2 Hz sampled metrics, 0.2 fps snapshots, five controllers, 20 simultaneous
watched sessions, all-agent reconnect and one gateway restart. Report event and
media throughput, DB/object growth per exam-hour, command/presence SLOs and
per-tenant fairness.

---

## 16. Definition of done for every PR

- behavior and failure mode documented;
- tests cover happy path, denial, duplicate, timeout and retry;
- schemas/migrations backwards compatible;
- authorization checked at service and data layer;
- structured logs/metrics added without high-cardinality labels;
- secrets/PII redacted;
- feature flag and rollback documented;
- relevant runbook updated;
- no unrelated refactor;
- current local development mode remains usable unless the PR explicitly
  retires it.

---

## 17. First implementation batch

Start with exactly these PRs:

1. **A1 — locks and shutdown**
2. **B1 — contracts v1**
3. **B2 — TypeScript server bootstrap**
4. **B3 — local Postgres/object-store/OIDC environment**
5. **B4a–B4c — tenancy/exam/enrollment/session migrations**
6. **C1 — agent supervisor skeleton**

Do not start the live grid or media integration before B1–B4. Their API and
state assumptions would otherwise be rebuilt.

The first demonstrable milestone is not a dashboard mock. It is one
authenticated controller starting one authenticated agent, receiving one
durably acknowledged event, and ending the session after both processes have
been restarted once.
