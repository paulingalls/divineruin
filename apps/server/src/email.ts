// Shared email validation for the unauthenticated endpoints (auth, waitlist) so
// they accept exactly the same set of addresses. Extracted from auth.ts; keep this
// the single source — a second copy of a security-relevant validator can drift.

export const MAX_EMAIL_LENGTH = 254;

export const EMAIL_RE =
  /^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)+$/;

// Trim + lowercase, then validate. Returns the normalized address, or null when
// it is missing, over the length cap, or malformed — callers turn null into 400.
export function normalizeEmail(raw: string | undefined): string | null {
  const email = raw?.trim().toLowerCase();
  if (!email || email.length > MAX_EMAIL_LENGTH || !EMAIL_RE.test(email)) return null;
  return email;
}
