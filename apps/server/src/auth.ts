import { SignJWT, jwtVerify } from "jose";
import { sql } from "./db.ts";
import { parseJsonBody } from "./middleware.ts";

const JWT_SECRET_HEX = Bun.env.JWT_SECRET ?? "";
const RESEND_API_KEY = Bun.env.RESEND_API_KEY ?? "";
const RESEND_FROM_EMAIL = Bun.env.RESEND_FROM_EMAIL ?? "auth@divineruin.com";

const JWT_EXPIRY = "30d";
const CODE_EXPIRY_MINUTES = 10;

function getJwtSecret(): Uint8Array {
  if (!JWT_SECRET_HEX) throw new Error("JWT_SECRET is not set");
  return Buffer.from(JWT_SECRET_HEX, "hex");
}

export async function signJwt(payload: { accountId: string; playerId: string }): Promise<string> {
  return new SignJWT({ sub: payload.accountId, pid: payload.playerId })
    .setProtectedHeader({ alg: "HS256" })
    .setIssuedAt()
    .setExpirationTime(JWT_EXPIRY)
    .sign(getJwtSecret());
}

export async function verifyJwt(
  token: string,
): Promise<{ accountId: string; playerId: string } | null> {
  try {
    const { payload } = await jwtVerify(token, getJwtSecret());
    const accountId = payload.sub;
    const playerId = payload.pid as string | undefined;
    if (!accountId || !playerId) return null;
    return { accountId, playerId };
  } catch {
    return null;
  }
}

export async function requireAuth(
  req: Request,
): Promise<{ accountId: string; playerId: string } | Response> {
  const auth = req.headers.get("Authorization");
  if (!auth?.startsWith("Bearer ")) {
    return Response.json({ error: "Unauthorized" }, { status: 401 });
  }
  const token = auth.slice(7);
  const claims = await verifyJwt(token);
  if (!claims) {
    return Response.json({ error: "Unauthorized" }, { status: 401 });
  }
  return claims;
}

function generateCode(): string {
  const arr = new Uint32Array(1);
  crypto.getRandomValues(arr);
  return String(arr[0]! % 1_000_000).padStart(6, "0");
}

const EMAIL_RE =
  /^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)+$/;
const MAX_EMAIL_LENGTH = 254;

export async function handleRequestCode(req: Request): Promise<Response> {
  const body = await parseJsonBody<{ email?: string }>(req);
  if (!body) {
    return Response.json({ error: "Invalid Content-Type" }, { status: 415 });
  }

  const rawEmail = body.email?.trim().toLowerCase();
  if (!rawEmail || rawEmail.length > MAX_EMAIL_LENGTH || !EMAIL_RE.test(rawEmail)) {
    return Response.json({ error: "A valid email address is required" }, { status: 400 });
  }

  // Find-or-create account
  await sql`
    INSERT INTO accounts (email) VALUES (${rawEmail})
    ON CONFLICT (email) DO NOTHING
  `;
  const accounts: { id: string }[] = await sql`
    SELECT id FROM accounts WHERE email = ${rawEmail}
  `;
  const account = accounts[0];
  if (!account) {
    return Response.json({ ok: true });
  }

  // Invalidate old unused codes
  await sql`
    UPDATE auth_codes SET used = TRUE
    WHERE account_id = ${account.id} AND used = FALSE
  `;

  // Generate new code
  const code = generateCode();
  const expiresAt = new Date(Date.now() + CODE_EXPIRY_MINUTES * 60_000);

  await sql`
    INSERT INTO auth_codes (account_id, code, expires_at)
    VALUES (${account.id}, ${code}, ${expiresAt})
  `;

  // Send email via Resend
  if (RESEND_API_KEY) {
    try {
      await fetch("https://api.resend.com/emails", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${RESEND_API_KEY}`,
        },
        body: JSON.stringify({
          from: RESEND_FROM_EMAIL,
          to: rawEmail,
          subject: "Divine Ruin - Your verification code",
          text: `Your verification code is: ${code}\n\nThis code expires in ${CODE_EXPIRY_MINUTES} minutes.`,
        }),
        signal: AbortSignal.timeout(5000),
      });
    } catch (e) {
      console.error("[auth] Failed to send email:", e instanceof Error ? e.message : e);
    }
  } else if (process.env.NODE_ENV !== "production") {
    console.log(`[auth] DEV CODE for ${rawEmail}: ${code}`);
  }

  return Response.json({ ok: true });
}

export async function handleVerifyCode(req: Request): Promise<Response> {
  const body = await parseJsonBody<{ email?: string; code?: string }>(req);
  if (!body) {
    return Response.json({ error: "Invalid Content-Type" }, { status: 415 });
  }

  const rawEmail = body.email?.trim().toLowerCase();
  const rawCode = body.code?.trim();
  if (!rawEmail || !rawCode) {
    return Response.json({ error: "Email and code are required" }, { status: 400 });
  }

  // Look up account
  const accounts: { id: string }[] = await sql`
    SELECT id FROM accounts WHERE email = ${rawEmail}
  `;
  const account = accounts[0];
  if (!account) {
    return Response.json({ error: "Invalid code" }, { status: 401 });
  }

  // Look up active code for account (don't match submitted code in SQL)
  const codes: { id: string; code: string; failed_attempts: number }[] = await sql`
    SELECT id, code, failed_attempts FROM auth_codes
    WHERE account_id = ${account.id}
      AND used = FALSE
      AND expires_at > NOW()
    ORDER BY created_at DESC
    LIMIT 1
  `;
  const authCode = codes[0];
  if (!authCode) {
    return Response.json({ error: "Invalid code" }, { status: 401 });
  }

  // Check if locked out
  if (authCode.failed_attempts >= 5) {
    await sql`UPDATE auth_codes SET used = TRUE WHERE id = ${authCode.id}`;
    return Response.json({ error: "Invalid code" }, { status: 401 });
  }

  // Check submitted code
  if (authCode.code !== rawCode) {
    const newAttempts = authCode.failed_attempts + 1;
    if (newAttempts >= 5) {
      await sql`UPDATE auth_codes SET used = TRUE, failed_attempts = ${newAttempts} WHERE id = ${authCode.id}`;
    } else {
      await sql`UPDATE auth_codes SET failed_attempts = ${newAttempts} WHERE id = ${authCode.id}`;
    }
    return Response.json({ error: "Invalid code" }, { status: 401 });
  }

  // Mark code used, update last_login
  await sql`UPDATE auth_codes SET used = TRUE WHERE id = ${authCode.id}`;
  await sql`UPDATE accounts SET last_login_at = NOW() WHERE id = ${account.id}`;

  // Find-or-create player for this account
  const playerId = `player_${account.id.slice(0, 8)}`;
  const existingPlayers: { player_id: string }[] = await sql`
    SELECT player_id FROM players WHERE account_id = ${account.id}
  `;

  if (existingPlayers.length === 0) {
    await sql`
      INSERT INTO players (player_id, account_id, data)
      VALUES (${playerId}, ${account.id}, ${{}}::jsonb)
    `;
  }

  const finalPlayerId = existingPlayers[0]?.player_id ?? playerId;
  const token = await signJwt({
    accountId: account.id,
    playerId: finalPlayerId,
  });

  return Response.json({
    token,
    account_id: account.id,
    player_id: finalPlayerId,
  });
}

export async function handleGetMe(req: Request): Promise<Response> {
  const auth = await requireAuth(req);
  if (auth instanceof Response) return auth;

  const accounts: { email: string; created_at: string }[] = await sql`
    SELECT email, created_at FROM accounts WHERE id = ${auth.accountId}
  `;
  const account = accounts[0];
  if (!account) {
    return Response.json({ error: "Account not found" }, { status: 404 });
  }

  return Response.json({
    account_id: auth.accountId,
    player_id: auth.playerId,
    email: account.email,
    created_at: account.created_at,
  });
}
