import { expect, test } from "bun:test";
import { resolve } from "node:path";

const root = resolve(import.meta.dir, "../../..");
const required = [
  "DATABASE_URL",
  "REDIS_URL",
  "JWT_SECRET",
  "INTERNAL_SECRET",
  "CORS_ORIGIN",
  "LIVEKIT_URL",
  "LIVEKIT_API_KEY",
  "LIVEKIT_API_SECRET",
  "GEMINI_API_KEY",
  "RESEND_API_KEY",
  "MEDIA_DIR",
];
const complete: Record<string, string> = Object.fromEntries(
  required.map((name) => [name, `private-${name}`]),
);
Object.assign(complete, {
  DATABASE_URL: "postgres://127.0.0.1:1/missing",
  REDIS_URL: "redis://127.0.0.1:1",
  MEDIA_DIR: "/nonexistent-production-config-smoke",
});

async function refused(values: Record<string, string>, missing: string[], mock = false) {
  const child = Bun.spawn([process.execPath, "--no-env-file", "run", "apps/server/src/index.ts"], {
    cwd: root,
    env: { NODE_ENV: "production", PORT: "0", ...values },
    stdout: "pipe",
    stderr: "pipe",
  });
  const timer = setTimeout(() => child.kill(), 5000);
  try {
    const [code, stdout, stderr] = await Promise.all([
      child.exited,
      new Response(child.stdout).text(),
      new Response(child.stderr).text(),
    ]);
    const output = stdout + stderr;
    expect(code).not.toBe(0);
    for (const name of missing) expect(output).toContain(name);
    if (mock) {
      expect(output).toContain("EMAIL_TRANSPORT");
      expect(output).toMatch(/mock.*(?:refused|forbidden|not allowed)/i);
    }
    expect(output).not.toMatch(/listening|server running/i);
    for (const value of Object.values(values).filter((v) => v.startsWith("private-"))) {
      expect(output).not.toContain(value);
    }
  } finally {
    clearTimeout(timer);
    child.kill();
    await child.exited;
  }
}

test("production entry point reports all absent configuration before route imports", async () => {
  await refused({}, required);
});
for (const name of required) {
  test(`production requires ${name}`, async () => {
    const values = { ...complete };
    delete values[name];
    await refused(values, [name]);
  });
}
test("production aggregates empty/whitespace values and explicit mock refusal", async () => {
  await refused(
    { ...complete, DATABASE_URL: "", JWT_SECRET: " \t", EMAIL_TRANSPORT: "mock" },
    ["DATABASE_URL", "JWT_SECRET"],
    true,
  );
  await refused({ ...complete, EMAIL_TRANSPORT: "mock" }, [], true);
  // BUN_TEST=1 is the other route into the mock transport (env.ts, email-transport.ts).
  await refused({ ...complete, BUN_TEST: "1" }, ["BUN_TEST"]);
  for (const transport of [undefined, "resend"]) {
    for (const key of ["", " \t"]) {
      await refused(
        { ...complete, ...(transport ? { EMAIL_TRANSPORT: transport } : {}), RESEND_API_KEY: key },
        ["RESEND_API_KEY"],
      );
    }
  }
});
