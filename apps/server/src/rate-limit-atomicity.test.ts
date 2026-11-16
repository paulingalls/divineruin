import { expect, test } from "bun:test";
import { key } from "./test-fixtures/rate-limit-server.ts";

test("an interrupted first caller leaves an expiring bucket after its first committed mutation", async () => {
  const player = crypto.randomUUID();
  const bucket = key("player", player, "/api/activities");
  const child = Bun.spawn(
    [
      process.execPath,
      "--no-env-file",
      "--eval",
      `
    const { checkRateLimit } = await import(${JSON.stringify(new URL("./rate-limit.ts", import.meta.url).pathname)});
    const send = Bun.redis.send.bind(Bun.redis);
    Bun.redis.send = async (command, args) => {
      const result = await send(command, args);
      process.stdout.write("committed\\n");
      await new Promise(() => {});
      return result;
    };
    await checkRateLimit("player", ${JSON.stringify(player)}, "/api/activities");
  `,
    ],
    {
      env: { ...process.env, RATE_LIMIT_BYPASS: undefined },
      stdout: "pipe",
      stderr: "pipe",
    },
  );
  try {
    const reader = child.stdout.getReader();
    const first = await Promise.race([
      reader.read(),
      Bun.sleep(10000).then(() => {
        throw new Error("first mutation deadline");
      }),
    ]);
    expect(new TextDecoder().decode(first.value)).toContain("committed");
    child.kill("SIGKILL");
    await child.exited;
    expect(await Bun.redis.get(bucket)).toBe("1");
    expect(Number(await Bun.redis.send("PTTL", [bucket]))).toBeWithin(1, 60001);
  } finally {
    child.kill("SIGKILL");
    await child.exited;
    await Bun.redis.del(bucket);
  }
});
