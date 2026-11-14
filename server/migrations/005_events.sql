-- 005 events
CREATE TABLE IF NOT EXISTS event (
  id BIGSERIAL PRIMARY KEY,
  org_id UUID NOT NULL,
  session_id UUID NOT NULL REFERENCES session(id),
  seq_no BIGINT NOT NULL,
  batch_id TEXT NOT NULL,
  payload_hash TEXT NOT NULL,
  payload JSONB NOT NULL,
  UNIQUE (session_id, seq_no),
  UNIQUE (batch_id)
);

CREATE TABLE IF NOT EXISTS event_rejection (
  id BIGSERIAL PRIMARY KEY,
  session_id UUID NOT NULL,
  seq_no BIGINT NOT NULL,
  code TEXT NOT NULL,
  detail TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ingest_cursor (
  session_id UUID PRIMARY KEY REFERENCES session(id),
  acked_through BIGINT NOT NULL DEFAULT 0
);
