-- 009 raw/normalized immutable partitions + outbox
CREATE TABLE IF NOT EXISTS raw_export_outbox (
  id BIGSERIAL PRIMARY KEY,
  event_id BIGINT NOT NULL,
  ingest_offset BIGINT NOT NULL,
  payload JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS normalized_partition (
  partition_id TEXT PRIMARY KEY,
  ingest_offset BIGINT NOT NULL,
  body JSONB NOT NULL,
  superseded_by TEXT
);

CREATE TABLE IF NOT EXISTS dataset_manifest (
  id UUID PRIMARY KEY,
  name TEXT NOT NULL,
  split JSONB NOT NULL,
  feature_partition TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS model_registry (
  alias TEXT PRIMARY KEY,
  version TEXT NOT NULL,
  body JSONB NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
