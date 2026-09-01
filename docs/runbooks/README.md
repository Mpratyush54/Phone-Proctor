# Runbooks (G5)

These runbooks are required before remote launch. Live exams continue on degraded observation; media unavailability must be explicit.

## Postgres outage / restore
1. API `/health/ready` reports postgres down.
2. Restore from PITR (RPO ≤ 5 min target). See `infra/terraform`.
3. Replay WAL from agents (cumulative ACK). Do not rebuild Redis first.

## Redis rebuild
Durable writes continue without Redis. Mark fanout degraded. Consoles rebuild from Postgres `exam_stream` + heartbeats. Two gateways must not require sticky sessions.

## Gateway drain
Stop accepting new WS; wait for in-flight ACK; start replacement. Agents resume with device credential.

## Object-store backlog
Snapshots pause first (agent media spool). After 10 attempts or 24h, dead-letter. Never silent discard.

## LiveKit / TURN
Live failure never stops event ingest. `STOP_LIVE` when no viewer remains.

## OIDC
Failed step-up denies the action without creating a command.

## Reconnect storm
Rate-limit hello/resume. One connection generation per session.

## Agent disk full
Protected WAL events (violations, receipts) are never dropped. Snapshots stop first.

## Accidental exam end
`EXAM_END` requires step-up. Audit the actor. Sessions already ENDED stay ended.

## Credential compromise
Revoke device credential family; refresh replay already revokes family.

## Model rollback
`PUT /api/v1/models/live` with previous version. Scoring failure must not stop the exam.

## Fault suite
- Kill gateway after commit before ACK → agent replays, no duplicate.
- Redis independently unavailable → degraded fanout.
- Postgres unavailable → ready=false; agents spool.
- Object store unavailable → quarantine / dead-letter.
- SFU unavailable → observation degraded.
