-- 002 exam / policy
CREATE TABLE IF NOT EXISTS exam (
  id UUID PRIMARY KEY,
  org_id UUID NOT NULL REFERENCES organization(id),
  code TEXT NOT NULL,
  title TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'DRAFT',
  version INTEGER NOT NULL DEFAULT 1,
  starts_at TIMESTAMPTZ,
  ends_at TIMESTAMPTZ,
  UNIQUE (org_id, code)
);

-- composite identity for tenant FKs (must exist before policy_version FK)
CREATE UNIQUE INDEX IF NOT EXISTS exam_org_id_idx ON exam(org_id, id);

CREATE TABLE IF NOT EXISTS policy_version (
  id UUID PRIMARY KEY,
  org_id UUID NOT NULL REFERENCES organization(id),
  exam_id UUID NOT NULL,
  version INTEGER NOT NULL,
  body JSONB NOT NULL,
  immutable BOOLEAN NOT NULL DEFAULT FALSE,
  UNIQUE (exam_id, version),
  FOREIGN KEY (org_id, exam_id) REFERENCES exam(org_id, id)
);

CREATE TABLE IF NOT EXISTS candidate_group (
  id UUID PRIMARY KEY,
  org_id UUID NOT NULL,
  exam_id UUID NOT NULL,
  name TEXT NOT NULL,
  FOREIGN KEY (org_id, exam_id) REFERENCES exam(org_id, id)
);

CREATE TABLE IF NOT EXISTS exam_staff_assignment (
  org_id UUID NOT NULL,
  exam_id UUID NOT NULL,
  user_id UUID NOT NULL,
  role TEXT NOT NULL,
  PRIMARY KEY (org_id, exam_id, user_id),
  FOREIGN KEY (org_id, exam_id) REFERENCES exam(org_id, id),
  FOREIGN KEY (org_id, user_id) REFERENCES organization_membership(org_id, user_id)
);

CREATE TABLE IF NOT EXISTS candidate_group_staff_assignment (
  org_id UUID NOT NULL,
  group_id UUID NOT NULL REFERENCES candidate_group(id),
  user_id UUID NOT NULL,
  PRIMARY KEY (org_id, group_id, user_id),
  FOREIGN KEY (org_id, user_id) REFERENCES organization_membership(org_id, user_id)
);
