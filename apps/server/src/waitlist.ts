import { sql } from "./db.ts";
import { parseJsonBody } from "./middleware.ts";
import { normalizeEmail } from "./email.ts";

interface WaitlistBody {
  email?: string;
  source?: string;
}

// Cap the optional free-text source tag so a client can't store an unbounded blob.
const MAX_SOURCE_LENGTH = 64;

// POST /api/waitlist — unauthenticated marketing-site signup. Validates + normalizes
// the email server-side (never trusts the client), then dedupe-inserts via the
// email primary key. ON CONFLICT DO NOTHING makes a repeat signup idempotent: it
// returns the same {ok:true} without creating a second row and without revealing
// whether the address was already on the list.
export async function handleJoinWaitlist(req: Request): Promise<Response> {
  const body = await parseJsonBody<WaitlistBody>(req);
  if (!body) {
    return Response.json({ error: "Invalid Content-Type" }, { status: 415 });
  }

  const email = normalizeEmail(body.email);
  if (!email) {
    return Response.json({ error: "A valid email address is required" }, { status: 400 });
  }

  // Coerce a missing, non-string, or empty source to null (absent tag) — only a
  // non-empty string is stored, capped at MAX_SOURCE_LENGTH.
  const source =
    typeof body.source === "string" && body.source ? body.source.slice(0, MAX_SOURCE_LENGTH) : null;

  await sql`
    INSERT INTO waitlist (email, source) VALUES (${email}, ${source})
    ON CONFLICT (email) DO NOTHING
  `;

  return Response.json({ ok: true });
}
