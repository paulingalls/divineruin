// Client helper for the marketing site's one server call: the waitlist signup. apps/web is
// otherwise static; the write lives on apps/server (POST /api/waitlist, story-002). Injectable
// (fetch + baseUrl) so it unit-tests with no network, like reveal.ts's env seam.

export interface WaitlistResult {
  ok: boolean;
  error?: string;
}

export interface JoinOpts {
  fetch?: typeof fetch;
  baseUrl?: string;
}

// The dev + e2e server origin. Bun replaces process.env.* at build time; the typeof guard keeps a
// no-process environment safe, and an unset var falls back here. Production's deployed API origin
// is supplied via PUBLIC_API_URL at deploy time — wired in Milestone 6, not here.
const DEFAULT_BASE = "http://localhost:3001";

export function waitlistApiBase(): string {
  const v = typeof process !== "undefined" ? process.env.PUBLIC_API_URL : undefined;
  return v && v.length > 0 ? v : DEFAULT_BASE;
}

// POST the email and map every outcome — success, validation/duplicate rejection, rate limit, or a
// network failure — to a handled WaitlistResult. Never throws, so the form can render a calm state.
export async function joinWaitlist(email: string, opts: JoinOpts = {}): Promise<WaitlistResult> {
  const doFetch = opts.fetch ?? fetch;
  const base = opts.baseUrl ?? waitlistApiBase();
  try {
    const res = await doFetch(`${base}/api/waitlist`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, source: "web" }),
    });
    if (res.ok) return { ok: true };
    if (res.status === 429) {
      return { ok: false, error: "Too many requests — try again in a minute." };
    }
    return { ok: false, error: "That didn't work. Check the address and try again." };
  } catch {
    return { ok: false, error: "Network hiccup — try again." };
  }
}
