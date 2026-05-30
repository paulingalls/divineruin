-- Waitlist signups from the marketing site (apps/web -> POST /api/waitlist).
-- email is the primary key: gives the UNIQUE + NOT NULL + index that the
-- handler's `INSERT ... ON CONFLICT (email) DO NOTHING` dedupe relies on.
-- Rows are insert-only (no updated_at / trigger needed). source is an optional
-- free-text tag for where the signup came from.

CREATE TABLE IF NOT EXISTS waitlist (
  email TEXT PRIMARY KEY,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  source TEXT
);
