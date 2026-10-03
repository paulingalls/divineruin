import { SignJWT } from "jose";
import { expect, test } from "bun:test";
import { networkInterfaces } from "node:os";
import { resolve } from "node:path";
import { verifyChoirMicrophone } from "../../scripts/verify-choir-encounter";

test("exported runner isolates ambient resources and refuses non-loopback HTTP", async () => {
  const keys = [
    "DATABASE_URL",
    "REDIS_URL",
    "LIVEKIT_URL",
    "LIVEKIT_API_KEY",
    "LIVEKIT_API_SECRET",
    "JWT_SECRET",
  ];
  const prior = keys.map((key) => process.env[key]);
  for (const key of keys) process.env[key] = "ambient-resource-must-not-be-used";
  let reached = false;
  try {
    await verifyChoirMicrophone(resolve(import.meta.dir, "../../../.."), async (_root, env) => {
      reached = true;
      for (const key of keys) expect(env[key]).not.toBe(process.env[key]);
      expect(env.JWT_SECRET).not.toBe("ab".repeat(32));
      const url = new URL(env.EXPO_PUBLIC_API_URL!);
      expect((await fetch(`${url}/api/inventory`)).status).toBe(401);
      const forged = await new SignJWT({ pid: "player_1" })
        .setProtectedHeader({ alg: "HS256" })
        .setSubject("attacker")
        .setExpirationTime("1h")
        .sign(new TextEncoder().encode("ab".repeat(32)));
      expect(
        (
          await fetch(`${url}/api/inventory`, {
            headers: { Authorization: `Bearer ${forged}` },
          })
        ).status,
      ).toBe(401);
      const external = Object.values(networkInterfaces())
        .flat()
        .find((address) => address && address.family === "IPv4" && !address.internal);
      expect(external).toBeDefined();
      url.hostname = external!.address;
      let refused = false;
      try {
        await fetch(`${url}/api/inventory`, { signal: AbortSignal.timeout(2000) });
      } catch {
        refused = true;
      }
      expect(refused).toBe(true);
    });
    expect(reached).toBe(true);
  } finally {
    keys.forEach((key, i) => {
      if (prior[i] === undefined) delete process.env[key];
      else process.env[key] = prior[i];
    });
  }
}, 180000);
