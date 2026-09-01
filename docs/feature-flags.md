# Feature flags and rollback

| Flag | Default | Rollback |
|------|---------|----------|
| `PHONE_PROCTOR_MODE` | `local` | set `local` |
| `PHONE_PROCTOR_WAIT_EXAM_START` | `0` | `0` restores previous AI-on-launch |
| `PHONE_PROCTOR_GOOGLE_STT` | `0` | keep `0` in product |
| `REDIS_URL` | unset | omit; fanout degrades |
| `LIVEKIT_URL` | unset | live view unavailable, ingest continues |
| model alias `live` | rules baseline | `PUT /api/v1/models/live` previous version |

PII/secrets are redacted from structured logs (`email`, `token`, `cookie`, `authorization`).
Metric labels never include names, emails, session IDs, or object keys.
