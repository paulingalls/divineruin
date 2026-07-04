import { test, expect, describe } from "bun:test";
import { randomUUID } from "crypto";

const { putInvite, getInvite } = await import("./invite-store.ts");

// Real-Valkey round-trip guarding the Bun.redis wiring. Mirrors db.test.ts:
// the env-free unit lane has no REDIS_URL (apps/server has no .env), so
// Bun.redis would default to :6379 and hang. Skip when REDIS_URL is unset to
// keep that lane green; the provisioned server lane (scripts/test-env.sh exports
// REDIS_URL) runs it for real under REQUIRE_REDIS=1.
const hasRedis = Boolean(process.env.REDIS_URL);

// Anti-silent-skip sentinel: the server lane sets REQUIRE_REDIS=1, so a
// REDIS_URL drift that would make the live-Valkey describe below silently skip
// fails loud here instead of quietly not running the wiring guard.
test("REDIS_URL present when the lane requires it (REQUIRE_REDIS sentinel)", () => {
  if (process.env.REQUIRE_REDIS === "1") {
    expect(hasRedis).toBe(true);
  }
});

describe.skipIf(!hasRedis)("invite-store", () => {
  test("round-trips a put invite", async () => {
    const code = `test-${randomUUID()}`;
    await putInvite(code, "room-abc", 30);
    try {
      const room = await getInvite(code);
      expect(room).toBe("room-abc");
    } finally {
      await Bun.redis.del(`invite:${code}`);
    }
  });

  test("returns null for an unknown code", async () => {
    const room = await getInvite(`test-nonexistent-${randomUUID()}`);
    expect(room).toBeNull();
  });

  test("returns null once the TTL has expired", async () => {
    const code = `test-ttl-${randomUUID()}`;
    await putInvite(code, "room-ttl", 1);
    await Bun.sleep(1100);
    const room = await getInvite(code);
    expect(room).toBeNull();
  });
});
