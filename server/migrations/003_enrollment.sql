-- 003 enrollment
CREATE TABLE IF NOT EXISTS enrollment (
  id UUID PRIMARY KEY,
  org_id UUID NOT NULL,
  exam_id UUID NOT NULL,
  student_external_id TEXT NOT NULL,
  display_name TEXT NOT NULL,
  UNIQUE (exam_id, student_external_id),
  FOREIGN KEY (org_id, exam_id) REFERENCES exam(org_id, id)
);

CREATE TABLE IF NOT EXISTS enrollment_token (
  id UUID PRIMARY KEY,
  enrollment_id UUID NOT NULL REFERENCES enrollment(id),
  token_hash TEXT NOT NULL UNIQUE,
  expires_at TIMESTAMPTZ NOT NULL,
  redeemed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS device (
  id UUID PRIMARY KEY,
  org_id UUID NOT NULL,
  enrollment_id UUID NOT NULL REFERENCES enrollment(id),
  kind TEXT NOT NULL CHECK (kind IN ('laptop', 'phone')),
  fingerprint TEXT
);

CREATE TABLE IF NOT EXISTS device_credential_family (
  id UUID PRIMARY KEY,
  device_id UUID NOT NULL REFERENCES device(id),
  revoked_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS device_refresh_token (
  id UUID PRIMARY KEY,
  family_id UUID NOT NULL REFERENCES device_credential_family(id),
  token_hash TEXT NOT NULL UNIQUE,
  replaced_by UUID,
  used_at TIMESTAMPTZ,
  expires_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS consent_record (
  id UUID PRIMARY KEY,
  enrollment_id UUID NOT NULL REFERENCES enrollment(id),
  body JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
