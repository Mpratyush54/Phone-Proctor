#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/infra"
docker compose up -d postgres minio oidc
echo "Postgres :5432  MinIO :9000  Dex :5556"
echo "Next: (cd ../server && npm install && npm run api)"
