CREATE TABLE signin_allowlist (
    email TEXT PRIMARY KEY,
    added_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
