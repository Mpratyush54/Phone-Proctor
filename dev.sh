#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT/infra"

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  docker compose up -d postgres minio oidc
  echo "Postgres :5432  MinIO :9000  Dex :5556 (Docker)"
else
  echo "Docker not available; using local Postgres."
  if command -v pg_ctlcluster >/dev/null 2>&1; then
    sudo pg_ctlcluster 16 main start 2>/dev/null || true
  fi
  export PGPASSWORD="${PGPASSWORD:-proctor}"
  if command -v psql >/dev/null 2>&1; then
    psql -h 127.0.0.1 -U proctor -d proctor -c "SELECT 1" >/dev/null
    echo "Postgres :5432 database proctor is up"
    if [[ "${APPLY_MIGRATIONS:-1}" == "1" ]]; then
      for f in $(ls "$ROOT/server/migrations"/*.sql | sort); do
        psql -h 127.0.0.1 -U proctor -d proctor -v ON_ERROR_STOP=1 -f "$f" >/dev/null
      done
      echo "Applied server/migrations/*.sql"
    fi
  else
    echo "Install PostgreSQL 16 or Docker to activate the control plane." >&2
    exit 1
  fi
fi

export DATABASE_URL="${DATABASE_URL:-postgres://proctor:proctor@127.0.0.1:5432/proctor}"
echo "DATABASE_URL=$DATABASE_URL"
echo "Next: (cd server && npm install && npm run api)  (gateway + worker in other terminals)"
echo "      (cd admin && npm install && npm run dev)"
