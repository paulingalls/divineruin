// Outbound verification-email edge seam. The ONLY place that calls the real
// Resend API, so a single switch decides mock vs real — no caller (and no env
// like the e2e harness's NODE_ENV=development) can route a test run to the live
// API by accident. Transport selection, in priority order:
//   EMAIL_TRANSPORT=mock     -> never send (e2e harness sets this)
//   EMAIL_TRANSPORT=resend   -> send IFF a key is present (prod opt-in; also
//                               lets unit tests exercise the real branch)
//   (unset)                  -> mock under any test runner or when unconfigured,
//                               real otherwise
import { IS_TEST_ENV, isDev } from "./env.ts";

const RESEND_URL = "https://api.resend.com/emails";
const DEFAULT_FROM_EMAIL = "auth@divineruin.com";

function resolveTransport(): "mock" | "resend" {
  const explicit = Bun.env.EMAIL_TRANSPORT;
  if (explicit === "mock") return "mock";
  const hasKey = !!Bun.env.RESEND_API_KEY;
  if (explicit === "resend") return hasKey ? "resend" : "mock";
  if (IS_TEST_ENV || !hasKey) return "mock";
  return "resend";
}

// Send the verification code to `to`. expiryMinutes comes from the caller (auth.ts
// owns the DB code expiry) so the email text never drifts from the real TTL.
export async function sendVerificationEmail(
  to: string,
  code: string,
  expiryMinutes: number,
): Promise<void> {
  if (resolveTransport() === "mock") {
    if (isDev) {
      console.log(`[email] DEV CODE for ${to}: ${code}`);
    }
    return;
  }

  const apiKey = Bun.env.RESEND_API_KEY ?? "";
  const from = Bun.env.RESEND_FROM_EMAIL ?? DEFAULT_FROM_EMAIL;
  try {
    const res = await fetch(RESEND_URL, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${apiKey}`,
      },
      body: JSON.stringify({
        from,
        to,
        subject: "Divine Ruin - Your verification code",
        text: `Your verification code is: ${code}\n\nThis code expires in ${expiryMinutes} minutes.`,
      }),
      signal: AbortSignal.timeout(5000),
    });
    // A non-2xx (bad key, 422 invalid payload, rate-limit) means the code never
    // reached the user — surface it rather than letting handleRequestCode return
    // {ok:true} silently. Mirrors push.ts's res.ok check on the Expo edge.
    if (!res.ok) {
      console.error(`[email] Resend API returned ${res.status}`);
    }
  } catch (e) {
    console.error("[email] Failed to send email:", e instanceof Error ? e.message : e);
  }
}
