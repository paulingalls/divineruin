import { test, expect, describe } from "bun:test";
import { randomUUID } from "crypto";

const { putInvite, getInvite } = await import("./invite-store.ts");

describe("invite-store", () => {
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
