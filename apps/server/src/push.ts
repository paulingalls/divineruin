import { sql } from "./db.ts";
import { logError } from "./env.ts";
import { parseJsonBody } from "./middleware.ts";

const EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send";

export async function handleStorePushToken(req: Request, playerId: string): Promise<Response> {
  try {
    const body = await parseJsonBody<{ token?: string; platform?: string }>(req);
    if (!body) {
      return Response.json({ error: "Invalid Content-Type" }, { status: 415 });
    }

    if (!body.token) {
      return Response.json({ error: "token is required" }, { status: 400 });
    }

    const token = body.token;
    const platform = body.platform ?? "unknown";

    // Validate Expo push token format
    if (!token.startsWith("ExponentPushToken[") && !token.startsWith("ExpoPushToken[")) {
      return Response.json({ error: "Invalid push token format" }, { status: 400 });
    }

    await sql`
      INSERT INTO push_tokens (player_id, token, platform)
      VALUES (${playerId}, ${token}, ${platform})
      ON CONFLICT (player_id, token) DO NOTHING
    `;

    return Response.json({ ok: true });
  } catch (err) {
    logError("[push] store token failed:", err);
    return Response.json({ error: "Internal server error" }, { status: 500 });
  }
}

export async function sendPushNotification(
  playerId: string,
  title: string,
  body: string,
  data?: Record<string, unknown>,
): Promise<void> {
  const rows: { token: string }[] = await sql`
    SELECT token FROM push_tokens WHERE player_id = ${playerId}
  `;

  if (rows.length === 0) return;

  const messages = rows.map((row) => ({
    to: row.token,
    sound: "default",
    title,
    body,
    data: data ?? {},
  }));

  try {
    const res = await fetch(EXPO_PUSH_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(messages),
    });

    if (!res.ok) {
      console.error(`[push] Expo push API returned ${res.status}`);
    }
  } catch (err) {
    logError("[push] send failed:", err);
  }
}

const INTERNAL_SECRET = Bun.env.INTERNAL_SECRET ?? "";
if (!INTERNAL_SECRET && process.env.NODE_ENV === "production") {
  throw new Error("[security] INTERNAL_SECRET must be set in production");
}
if (!INTERNAL_SECRET) {
  console.warn("[push] INTERNAL_SECRET not set — internal push endpoint will reject all requests");
}

export async function handleInternalPush(req: Request): Promise<Response> {
  // Internal endpoint called by the Python agent
  const secret = req.headers.get("X-Internal-Secret");
  if (!INTERNAL_SECRET || secret !== INTERNAL_SECRET) {
    return Response.json({ error: "Unauthorized" }, { status: 401 });
  }

  try {
    const body = await parseJsonBody<{
      player_id?: string;
      title?: string;
      body?: string;
      data?: Record<string, unknown>;
    }>(req);
    if (!body) {
      return Response.json({ error: "Invalid Content-Type" }, { status: 415 });
    }

    if (!body.player_id || !body.title || !body.body) {
      return Response.json({ error: "player_id, title, and body are required" }, { status: 400 });
    }

    await sendPushNotification(body.player_id, body.title, body.body, body.data);
    return Response.json({ ok: true });
  } catch (err) {
    logError("[push] internal push failed:", err);
    return Response.json({ error: "Internal server error" }, { status: 500 });
  }
}
