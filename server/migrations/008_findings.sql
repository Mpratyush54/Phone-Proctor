-- 008 findings / review / appeal
CREATE TABLE IF NOT EXISTS finding (
  id UUID PRIMARY KEY,
  org_id UUID NOT NULL,
  session_id UUID NOT NULL REFERENCES session(id),
  event_seq BIGINT,
  label TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'provisional',
  actor_id UUID,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS label_revision (
  id BIGSERIAL PRIMARY KEY,
  finding_id UUID NOT NULL REFERENCES finding(id),
  actor_id UUID NOT NULL,
  label TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS review_assignment (
  id UUID PRIMARY KEY,
  finding_id UUID NOT NULL REFERENCES finding(id),
  reviewer_id UUID NOT NULL,
  UNIQUE (finding_id, reviewer_id)
);

CREATE TABLE IF NOT EXISTS review_case (
  id UUID PRIMARY KEY,
  finding_id UUID NOT NULL REFERENCES finding(id),
  guideline_version TEXT NOT NULL,
  selection_probability DOUBLE PRECISION,
  modalities_viewed JSONB,
  post_intervention BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS appeal (
  id UUID PRIMARY KEY,
  finding_id UUID NOT NULL REFERENCES finding(id),
  appellant TEXT,
  frozen_manifest_id UUID,
  outcome TEXT,
  original_reviewer_id UUID,
  appeal_reviewer_id UUID,
  CHECK (original_reviewer_id IS DISTINCT FROM appeal_reviewer_id)
);
