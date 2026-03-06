const CORS_ORIGIN = Bun.env.CORS_ORIGIN ?? "*";

const CORS_HEADERS: Record<string, string> = {
  "Access-Control-Allow-Origin": CORS_ORIGIN,
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, Authorization",
};

export function handlePreflight(): Response {
  return new Response(null, { status: 204, headers: CORS_HEADERS });
}

export function withCors(response: Response): Response {
  for (const [key, value] of Object.entries(CORS_HEADERS)) {
    response.headers.set(key, value);
  }
  return response;
}

// --- Rate Limiter ---

interface RateBucket {
  count: number;
  resetAt: number;
}

const buckets = new Map<string, RateBucket>();

const RATE_LIMITS: Record<string, number> = {
  "/api/livekit/token": 10,
  "/api/auth/request-code": 3,
  "/api/auth/verify-code": 5,
};
const DEFAULT_RATE_LIMIT = 60;
const WINDOW_MS = 60_000;

// Purge stale entries every 5 minutes
let purgeInterval: ReturnType<typeof setInterval> | null = setInterval(() => {
  const now = Date.now();
  for (const [key, bucket] of buckets) {
    if (bucket.resetAt <= now) {
      buckets.delete(key);
    }
  }
}, 5 * 60_000);

export function checkRateLimit(ip: string, path: string): Response | null {
  const limit = RATE_LIMITS[path] ?? DEFAULT_RATE_LIMIT;
  const key = `${ip}:${path}`;
  const now = Date.now();

  let bucket = buckets.get(key);
  if (!bucket || bucket.resetAt <= now) {
    bucket = { count: 0, resetAt: now + WINDOW_MS };
    buckets.set(key, bucket);
  }

  bucket.count++;
  if (bucket.count > limit) {
    const retryAfter = Math.ceil((bucket.resetAt - now) / 1000);
    return withCors(
      new Response(JSON.stringify({ error: "Too many requests" }), {
        status: 429,
        headers: {
          "Content-Type": "application/json",
          "Retry-After": String(retryAfter),
        },
      }),
    );
  }
  return null;
}

/** Reset all rate limit state (for testing). */
export function _resetRateLimits(): void {
  buckets.clear();
  if (purgeInterval) {
    clearInterval(purgeInterval);
    purgeInterval = null;
  }
}
