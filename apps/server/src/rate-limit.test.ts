import { expect, test } from "bun:test";
import { spawnServer } from "./test-fixtures/rate-limit-server.ts";

async function refuses(overrides: Record<string, string | undefined>, diagnostic: string) {
  const proc = spawnServer(overrides, `${import.meta.dir}/index.ts`);
  let killed = false;
  const timer = setTimeout(() => {
    killed = true;
    proc.kill();
  }, 3000);
  try {
    const [code, out, err] = await Promise.all([
      proc.exited,
      new Response(proc.stdout).text(),
      new Response(proc.stderr).text(),
    ]);
    expect(killed).toBe(false);
    expect(code).not.toBe(0);
    expect(out + err).toContain(diagnostic);
    expect(out).not.toContain("Server running at");
  } finally {
    clearTimeout(timer);
    proc.kill();
  }
}
test("startup refuses invalid trusted proxy hops before listening", async () => {
  await Promise.all(
    ["0", "1.5", "2x"].map((TRUSTED_PROXY_HOPS) =>
      refuses({ TRUSTED_PROXY_HOPS }, "TRUSTED_PROXY_HOPS"),
    ),
  );
});
test("production refuses the development rate-limit bypass", async () => {
  const env = Object.fromEntries(
    "DATABASE_URL REDIS_URL JWT_SECRET INTERNAL_SECRET CORS_ORIGIN LIVEKIT_URL LIVEKIT_API_KEY LIVEKIT_API_SECRET GEMINI_API_KEY RESEND_API_KEY MEDIA_DIR"
      .split(" ")
      .map((k) => [k, "synthetic"]),
  );
  await refuses(
    {
      ...env,
      NODE_ENV: "production",
      RATE_LIMIT_BYPASS: "1",
      EMAIL_TRANSPORT: undefined,
      BUN_TEST: undefined,
    },
    "RATE_LIMIT_BYPASS",
  );
});
