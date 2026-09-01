-- 010 RLS + pooled connection hardening
ALTER DATABASE proctor SET row_security = on;

CREATE OR REPLACE FUNCTION app_org_id() RETURNS uuid AS $$
BEGIN
  RETURN NULLIF(current_setting('app.org_id', true), '')::uuid;
END;
$$ LANGUAGE plpgsql STABLE;

DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['exam','enrollment','session','event','command','media_asset','finding']
  LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %I', t);
    EXECUTE format(
      'CREATE POLICY tenant_isolation ON %I USING (org_id = app_org_id()) WITH CHECK (org_id = app_org_id())',
      t
    );
  END LOOP;
END $$;
