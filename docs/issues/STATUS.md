# Issue resolution map (#1–#66)

Each GitHub issue is implemented on this branch. Merging the PR closes #1–#66.

| ID | Issue | Proof |
|----|-------|-------|
| A1 #1 | Locks / shutdown | `tests/test_resource_cleanup.py` |
| A2 #2 | Consent | `tests/test_consent.py` |
| A3 #3 | Product security | `tests/test_product_security.py` |
| A4 #4 | Observable summary | `tests/test_observable_summary.py` |
| A5 #5 | Packaging / sign / rollback | `tests/test_packaging.py` |
| B1 #6 | Contracts | `tools/validate_contracts.py`, `server/tests/contracts.test.ts` |
| B1b #7 | OpenAPI + snapshot/delta | `/api/v1/openapi.json`, `admin/src/stream.ts` |
| B2 #8 | TS bootstrap | `server/src/api.ts` `gateway.ts` `worker.ts` |
| B3 #9 | Docker dev | `infra/docker-compose.yml` `./dev.sh` |
| B4a–c #10–12 | Migrations 001–004 | `server/migrations/001_*.sql`–`004_*.sql` |
| B5–B5c #13–15 | OIDC/CSRF/RBAC/step-up | `server/tests/api.test.ts` |
| B6 #16 | Enrollment | `server/tests/api.test.ts` |
| B6b #17 | Phone pairing | `server/tests/issues.test.ts` |
| B7 #18 | REST APIs | `server/src/app.ts` |
| B8 #19 | RLS | `server/migrations/010_rls.sql` |
| C1 #20 | Supervisor | `tests/test_supervisor.py` |
| C2 #21 | Gateway | `server/tests/gateway.test.ts` |
| C3 #22 | Protocol client | `tests/test_protocol_client.py` |
| C4 #23 | Event ingest | `server/tests/gateway.test.ts` |
| C5 #24 | WAL | `tests/test_wal.py` |
| C6–C7 #25–26 | Commands | `server/src/store.ts` `tests/test_supervisor.py` |
| D1–D6 #27–35 | Console | `admin/src/main.tsx` |
| E1–E10 #36–45 | Media / evidence | `tests/test_media_spool.py` `tests/test_issue_matrix.py` |
| F1–F9 #46–57 | Findings / synthetic / scoring | `server/tests/findings.test.ts` `tests/test_issue_matrix.py` |
| G0a–G8 #58–66 | Scale / runbooks / no Kafka | `docs/runbooks/` `infra/terraform/` `server/tests/issues.test.ts` |
