# Phone-Proctor controller implementation plan (index)

Sequenced GitHub issues #1–#66 implement tracks A–G.

Local development (one command):

```bash
cd infra && docker compose up -d postgres minio oidc
cd ../server && npm install && npm run api
# other terminals:
npm run gateway
npm run worker
cd ../admin && npm install && npm run dev
```

Python laptop agent remains usable:

```bash
pip install -r requirements.txt
python main.py
```

Feature flags:
- `PHONE_PROCTOR_MODE=local|product`
- `PHONE_PROCTOR_WAIT_EXAM_START=1` (C1 gate)
- `PHONE_PROCTOR_GOOGLE_STT=1` (local only)
- Redis is optional until Track G (`REDIS_URL`)

Rollback: agent packaging rollback via `agent.packaging.rollback_release`; model rollback is `PUT /api/v1/models/live`.
