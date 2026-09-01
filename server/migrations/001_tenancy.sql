-- 001 tenancy / staff
CREATE TABLE IF NOT EXISTS organization (
  id UUID PRIMARY KEY,
  name TEXT NOT NULL,
  slug TEXT NOT NULL UNIQUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS user_account (
  id UUID PRIMARY KEY,
  email_normalized TEXT NOT NULL,
  issuer TEXT NOT NULL,
  subject TEXT NOT NULL,
  display_name TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (email_normalized),
  UNIQUE (issuer, subject)
);

CREATE TABLE IF NOT EXISTS organization_membership (
  org_id UUID NOT NULL REFERENCES organization(id),
  user_id UUID NOT NULL REFERENCES user_account(id),
  status TEXT NOT NULL DEFAULT 'active',
  PRIMARY KEY (org_id, user_id)
);

CREATE TABLE IF NOT EXISTS org_role_assignment (
  org_id UUID NOT NULL,
  user_id UUID NOT NULL,
  role TEXT NOT NULL,
  exam_id UUID,
  group_id UUID,
  PRIMARY KEY (org_id, user_id, role, COALESCE(exam_id, '00000000-0000-0000-0000-000000000000'), COALESCE(group_id, '00000000-0000-0000-0000-000000000000')),
  FOREIGN KEY (org_id, user_id) REFERENCES organization_membership(org_id, user_id)
);

CREATE TABLE IF NOT EXISTS staff_auth_session (
  id UUID PRIMARY KEY,
  org_id UUID NOT NULL REFERENCES organization(id),
  user_id UUID NOT NULL REFERENCES user_account(id),
  session_hash TEXT NOT NULL,
  refresh_hash TEXT NOT NULL,
  key_version INTEGER NOT NULL DEFAULT 1,
  expires_at TIMESTAMPTZ NOT NULL,
  revoked_at TIMESTAMPTZ,
  replay_seen BOOLEAN NOT NULL DEFAULT FALSE,
  step_up_until TIMESTAMPTZ,
  csrf_secret TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS oidc_login_transaction (
  state TEXT PRIMARY KEY,
  nonce TEXT NOT NULL UNIQUE,
  pkce_verifier_hash TEXT NOT NULL,
  used_at TIMESTAMPTZ,
  expires_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS support_grant (
  id UUID PRIMARY KEY,
  org_id UUID NOT NULL REFERENCES organization(id),
  user_id UUID NOT NULL REFERENCES user_account(id),
  reason TEXT NOT NULL,
  expires_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_action (
  id BIGSERIAL PRIMARY KEY,
  org_id UUID NOT NULL,
  actor_id UUID,
  action TEXT NOT NULL,
  payload JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE OR REPLACE FUNCTION audit_append_only() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'UPDATE' OR TG_OP = 'DELETE' THEN
    IF current_setting('app.retention_job', true) IS DISTINCT FROM '1' THEN
      RAISE EXCEPTION 'audit_action is append-only';
    END IF;
  END IF;
  IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS audit_action_append_only ON audit_action;
CREATE TRIGGER audit_action_append_only
  BEFORE UPDATE OR DELETE ON audit_action
  FOR EACH ROW EXECUTE FUNCTION audit_append_only();
