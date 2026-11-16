import { test, expect, describe } from "bun:test";
import { randomUUID } from "crypto";

const { putInvite, getInvite } = await import("./invite-store.ts");

const hasRedis = Boolean(process.env.REDIS_URL);
if (process.env.REQUIRE_REDIS === "1" && !hasRedis) throw new Error("REDIS_URL is required");

test("missing REDIS_URL fails before using the client", async () => {
  const prior = process.env.REDIS_URL;
  delete process.env.REDIS_URL;
  try {
    let failure: unknown;
    try {
      await getInvite("missing-env");
    } catch (error) {
      failure = error;
    }
    expect(failure).toBeInstanceOf(Error);
    if (!(failure instanceof Error)) throw failure;
    expect(failure.message).toContain("REDIS_URL");
  } finally {
    if (prior === undefined) delete process.env.REDIS_URL;
    else process.env.REDIS_URL = prior;
  }
});

describe.skipIf(!hasRedis)("invite-store", () => {
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
