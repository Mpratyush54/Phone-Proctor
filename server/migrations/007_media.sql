-- 007 media
CREATE TABLE IF NOT EXISTS media_asset (
  id UUID PRIMARY KEY,
  org_id UUID NOT NULL,
  session_id UUID NOT NULL REFERENCES session(id),
  kind TEXT NOT NULL,
  object_key TEXT NOT NULL UNIQUE,
  content_type TEXT NOT NULL,
  bytes INTEGER NOT NULL,
  sha256 TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending_verification'
);

CREATE TABLE IF NOT EXISTS media_object (
  id UUID PRIMARY KEY,
  asset_id UUID NOT NULL REFERENCES media_asset(id),
  storage_uri TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS media_upload (
  id UUID PRIMARY KEY,
  asset_id UUID NOT NULL REFERENCES media_asset(id),
  expires_at TIMESTAMPTZ NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS evidence_manifest (
  id UUID PRIMARY KEY,
  session_id UUID NOT NULL REFERENCES session(id),
  frozen BOOLEAN NOT NULL DEFAULT FALSE,
  body JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS media_dead_letter (
  id BIGSERIAL PRIMARY KEY,
  asset_id UUID NOT NULL,
  reason TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
