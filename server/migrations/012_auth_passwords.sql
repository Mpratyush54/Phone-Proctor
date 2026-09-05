-- 012 staff password hashes for the embedded development IdP
-- Production uses an external issuer; this column stays NULL there.
ALTER TABLE user_account ADD COLUMN IF NOT EXISTS password_hash TEXT;
