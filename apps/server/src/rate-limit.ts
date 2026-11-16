import { isIP } from "node:net";
import { requireEnv } from "./env.ts";
import { withCors } from "./middleware.ts";

const RATE_LIMITS: Record<string, number> = {
  "/api/livekit/token": 10,
  "/api/livekit/invite": 10,
  "/api/livekit/redeem": 10,
  "/api/auth/request-code": 3,
  "/api/auth/verify-code": 5,
  "/api/waitlist": 5,
  "/api/push-token": 5,
  "/api/activities": 10,
  "/api/internal/push": 30,
  "/api/images/generate": 10,
};
const DEFAULT_RATE_LIMIT = 30;
const WINDOW_MS = 60_000;

const rawHops = process.env.TRUSTED_PROXY_HOPS;
const hops = rawHops === undefined ? 0 : Number(rawHops);
if (
  rawHops !== undefined &&
  (!/^[0-9]+$/.test(rawHops) || !Number.isSafeInteger(hops) || hops <= 0)
) {
  throw new Error("TRUSTED_PROXY_HOPS must be a positive safe integer");
}
if (process.env.RATE_LIMIT_BYPASS === "1" && Bun.env.NODE_ENV === "production") {
  throw new Error("[security] RATE_LIMIT_BYPASS must not be set in production.");
}

export function clientIP(req: Request, peer: string): string {
  const header = req.headers.get("X-Forwarded-For");
  // No header is a direct caller (the agent and worker reach the server without the proxy).
  if (!hops || header === null) return peer;
  const parts = header.split(",").map((part) => part.trim());
  const suffix = parts.slice(-hops);
  const reason =
    parts.length < hops ? "short" : suffix.some((part) => !isIP(part)) ? "malformed" : null;
  if (reason) {
    console.warn(`[rate-limit] client IP fallback: ${reason} trusted proxy header`);
    return peer;
  }
  return parts[parts.length - hops]!;
}

// One script prevents an interrupted first hit from leaving a counter without expiry.
const HIT = `
local count = redis.call('INCR', KEYS[1])
if count == 1 then redis.call('PEXPIRE', KEYS[1], ARGV[1]) end
return {count, redis.call('PTTL', KEYS[1])}
`;
export async function checkRateLimit(
  kind: "player" | "ip",
  identity: string,
  path: string,
): Promise<Response | null> {
  if (process.env.RATE_LIMIT_BYPASS === "1") return null;
  requireEnv("REDIS_URL");
  const key = `rate-limit:${JSON.stringify([kind, identity, path])}`;
  const [count, ttl] = (await Bun.redis.send("EVAL", [
    HIT,
    "1",
    key,
    String(WINDOW_MS),
  ])) as number[];
  if (count! <= (RATE_LIMITS[path] ?? DEFAULT_RATE_LIMIT)) return null;
  return withCors(
    Response.json(
      { error: "Too many requests" },
      {
        status: 429,
        headers: { "Retry-After": String(Math.ceil(ttl! / 1000)) },
      },
    ),
  );
}
