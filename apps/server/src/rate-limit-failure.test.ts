import { expect, test } from "bun:test";
import { sql } from "./db.ts";
import { codePath, launch, resources } from "./test-fixtures/rate-limit-server.ts";

test("a real Valkey command failure reaches HTTP 500 before auth or email work", async () => {
  const data = await resources(),
    server = await launch();
  try {
    const email = await data.address(),
      controlEmail = await data.address(),
      control = "198.19.0.1",
      target = "198.19.0.2";
    data.track("ip", control);
    const k = data.track("ip", target);
    const send = (ip: string, address = email) =>
      server.request(codePath, { "X-Forwarded-For": ip }, { email: address });
    expect((await send(control, controlEmail)).status).toBe(200);
    expect(await data.codes(controlEmail)).toBe(1);
    const emails = server.logs().split("rate-limit email sent").length;
    await Bun.redis.send("LPUSH", [k, "wrong-type"]);
    await Bun.redis.send("PEXPIRE", [k, "60000"]);
    expect((await send(target)).status).toBe(500);
    expect(server.logs()).toContain("Server request failed");
    expect(await data.codes(email)).toBe(0);
    expect(await sql`SELECT id FROM accounts WHERE email=${email}`).toHaveLength(0);
    expect(server.logs().split("rate-limit email sent").length).toBe(emails);
    expect(server.proc.exitCode).toBeNull();
  } finally {
    await server.stop();
    await data.cleanup();
  }
});
