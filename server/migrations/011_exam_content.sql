-- 011 exam content: banks, groups, variants, options, versions, candidate access
CREATE TABLE IF NOT EXISTS question_bank (
  id UUID PRIMARY KEY,
  org_id UUID NOT NULL REFERENCES organization(id),
  name TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS question_group (
  id UUID PRIMARY KEY,
  org_id UUID NOT NULL,
  bank_id UUID NOT NULL REFERENCES question_bank(id),
  position INTEGER NOT NULL DEFAULT 0,
  title TEXT NOT NULL,
  marks NUMERIC NOT NULL DEFAULT 1,
  negative_marks NUMERIC NOT NULL DEFAULT 0,
  rubric TEXT NOT NULL DEFAULT '',
  UNIQUE (bank_id, position)
);

CREATE TABLE IF NOT EXISTS content_version (
  id UUID PRIMARY KEY,
  org_id UUID NOT NULL,
  bank_id UUID NOT NULL REFERENCES question_bank(id),
  version INTEGER NOT NULL,
  frozen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (bank_id, version)
);

CREATE TABLE IF NOT EXISTS question_variant (
  id UUID PRIMARY KEY,
  org_id UUID NOT NULL,
  group_id UUID NOT NULL REFERENCES question_group(id),
  content_version_id UUID REFERENCES content_version(id),
  position INTEGER NOT NULL DEFAULT 0,
  stem TEXT NOT NULL,
  qtype TEXT NOT NULL DEFAULT 'mcq_single' CHECK (qtype IN ('mcq_single', 'mcq_multi', 'short_text', 'long_text')),
  per_question_s INTEGER,
  deprecated BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS question_option (
  id UUID PRIMARY KEY,
  org_id UUID NOT NULL,
  variant_id UUID NOT NULL REFERENCES question_variant(id),
  position INTEGER NOT NULL DEFAULT 0,
  label TEXT NOT NULL,
  correct BOOLEAN NOT NULL DEFAULT FALSE,
  UNIQUE (variant_id, position)
);

ALTER TABLE exam ADD COLUMN IF NOT EXISTS content_version_id UUID REFERENCES content_version(id);
ALTER TABLE exam ADD COLUMN IF NOT EXISTS allow_back_navigation BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE exam ADD COLUMN IF NOT EXISTS duration_s INTEGER;
ALTER TABLE session ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS candidate_login_code (
  id UUID PRIMARY KEY,
  enrollment_id UUID NOT NULL REFERENCES enrollment(id),
  code_hash TEXT NOT NULL UNIQUE,
  expires_at TIMESTAMPTZ NOT NULL,
  redeemed_at TIMESTAMPTZ,
  max_uses INTEGER NOT NULL DEFAULT 1,
  uses INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS candidate_session (
  id UUID PRIMARY KEY,
  session_id UUID NOT NULL REFERENCES session(id),
  enrollment_id UUID NOT NULL REFERENCES enrollment(id),
  token_hash TEXT NOT NULL UNIQUE,
  csrf_secret TEXT NOT NULL DEFAULT '',
  expires_at TIMESTAMPTZ NOT NULL,
  revoked_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS candidate_item_assignment (
  session_id UUID NOT NULL REFERENCES session(id),
  group_id UUID NOT NULL REFERENCES question_group(id),
  variant_id UUID NOT NULL REFERENCES question_variant(id),
  option_seed BIGINT NOT NULL,
  position INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (session_id, group_id)
);

CREATE TABLE IF NOT EXISTS candidate_answer (
  id UUID PRIMARY KEY,
  session_id UUID NOT NULL REFERENCES session(id),
  variant_id UUID NOT NULL REFERENCES question_variant(id),
  option_ids JSONB NOT NULL DEFAULT '[]',
  text_answer TEXT NOT NULL DEFAULT '',
  correct BOOLEAN,
  score NUMERIC,
  submitted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (session_id, variant_id)
);
