-- 006 commands / outbox / exam_stream
CREATE TABLE IF NOT EXISTS command (
  id UUID PRIMARY KEY,
  org_id UUID NOT NULL,
  session_id UUID NOT NULL REFERENCES session(id),
  command_type TEXT NOT NULL,
  idempotency_key TEXT NOT NULL,
  body JSONB NOT NULL,
  status TEXT NOT NULL DEFAULT 'accepted',
  result JSONB,
  UNIQUE (session_id, idempotency_key)
);

CREATE TABLE IF NOT EXISTS command_delivery (
  id BIGSERIAL PRIMARY KEY,
  command_id UUID NOT NULL REFERENCES command(id),
  attempt INTEGER NOT NULL,
  delivered_at TIMESTAMPTZ,
  ack_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS outbox (
  id BIGSERIAL PRIMARY KEY,
  topic TEXT NOT NULL,
  payload JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  published_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS exam_stream (
  id BIGSERIAL PRIMARY KEY,
  exam_id UUID NOT NULL,
  stream_seq BIGINT NOT NULL,
  payload JSONB NOT NULL,
  UNIQUE (exam_id, stream_seq)
);
