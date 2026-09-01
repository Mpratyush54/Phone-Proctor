-- 004 session
CREATE TABLE IF NOT EXISTS session (
  id UUID PRIMARY KEY,
  org_id UUID NOT NULL,
  exam_id UUID NOT NULL,
  enrollment_id UUID NOT NULL REFERENCES enrollment(id),
  desired_lifecycle_state TEXT NOT NULL DEFAULT 'NEW',
  observed_lifecycle_state TEXT NOT NULL DEFAULT 'NEW',
  control_generation INTEGER NOT NULL DEFAULT 0,
  connection_generation INTEGER NOT NULL DEFAULT 0,
  connectivity TEXT NOT NULL DEFAULT 'offline',
  attention TEXT NOT NULL DEFAULT 'unknown',
  FOREIGN KEY (org_id, exam_id) REFERENCES exam(org_id, id)
);

CREATE TABLE IF NOT EXISTS session_attempt (
  id UUID PRIMARY KEY,
  session_id UUID NOT NULL REFERENCES session(id),
  enrollment_id UUID NOT NULL REFERENCES enrollment(id),
  terminal BOOLEAN NOT NULL DEFAULT FALSE,
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  ended_at TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS one_active_attempt
  ON session_attempt (enrollment_id) WHERE terminal = FALSE;

CREATE TABLE IF NOT EXISTS precheck_result (
  id UUID PRIMARY KEY,
  session_id UUID NOT NULL REFERENCES session(id),
  body JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS status_transition (
  id BIGSERIAL PRIMARY KEY,
  session_id UUID NOT NULL REFERENCES session(id),
  from_state TEXT,
  to_state TEXT NOT NULL,
  desired BOOLEAN NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
