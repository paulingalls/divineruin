import { describe, expect, test } from "bun:test";
import { rm, writeFile } from "node:fs/promises";
import { resolve } from "node:path";

const e2eRoot = import.meta.dir;

function runChild(source: string, databaseUrl?: string) {
  const env: NodeJS.ProcessEnv = { ...process.env, REDIS_URL: "redis://127.0.0.1:61235" };
  delete env.DATABASE_URL;
  if (databaseUrl !== undefined) env.DATABASE_URL = databaseUrl;
  return Bun.spawnSync({
    cmd: [process.execPath, "-e", source],
    cwd: e2eRoot,
    env,
    stdout: "pipe",
    stderr: "pipe",
  });
}

function output(result: ReturnType<typeof runChild>): string {
  return `${result.stdout.toString()}${result.stderr.toString()}`;
}

function expectDatabaseGuard(result: ReturnType<typeof runChild>) {
  const diagnostic = output(result);
  expect(result.exitCode).not.toBe(0);
  expect(diagnostic).toContain("DATABASE_URL is required");
  expect(diagnostic).not.toContain("REACHED_SENTINEL");
  expect(diagnostic).not.toContain("55432");
  expect(diagnostic).not.toMatch(/ECONNREFUSED|connect ENOENT|socket/i);
}

describe("required e2e environment", () => {
  test("the helper returns the explicit value unchanged", () => {
    const value = "postgresql://story:secret@127.0.0.1:61234/story_210";
    const helper = resolve(e2eRoot, "require-environment.ts");
    const result = runChild(
      `import { requireEnvironment } from ${JSON.stringify(helper)}; console.log(requireEnvironment("DATABASE_URL"));`,
      value,
    );

    expect(result.exitCode).toBe(0);
    expect(result.stdout.toString().trim()).toBe(value);
  });

  test("the auth fixture fails before a query can run", () => {
    const auth = resolve(e2eRoot, "fixtures/auth.ts");
    const result = runChild(
      `const module = await import(${JSON.stringify(auth)}); await module.queryDb("SELECT 1"); console.log("REACHED_SENTINEL");`,
    );
    expectDatabaseGuard(result);
  });

  test("the Playwright config owns an independent guard", () => {
    const config = resolve(e2eRoot, "playwright.config.ts");
    const result = runChild(
      `await import(${JSON.stringify(config)}); console.log("REACHED_SENTINEL");`,
    );
    expectDatabaseGuard(result);
  });

  test("the Playwright config refuses an unspecified Valkey before startup", () => {
    const config = resolve(e2eRoot, "playwright.config.ts");
    const result = runChild(
      `delete process.env.REDIS_URL; await import(${JSON.stringify(config)}); console.log("REACHED_SENTINEL");`,
      "postgresql://story@127.0.0.1:61234/story_210",
    );
    expect(result.exitCode).not.toBe(0);
    expect(output(result)).toContain("REDIS_URL is required");
    expect(output(result)).not.toContain("REACHED_SENTINEL");
    expect(output(result)).not.toContain("56379");
  });

  test("removing only the auth guard exposes the auth module", async () => {
    const sourcePath = resolve(e2eRoot, "fixtures/auth.ts");
    const faultPath = resolve(e2eRoot, "fixtures/.story210-auth-fault.ts");
    const source = await Bun.file(sourcePath).text();
    expect(source).toContain('requireEnvironment("DATABASE_URL")');
    await writeFile(faultPath, source.replace('requireEnvironment("DATABASE_URL")', '"unguarded"'));
    try {
      const fault = runChild(
        `await import(${JSON.stringify(faultPath)}); console.log("REACHED_SENTINEL");`,
      );
      expect(fault.exitCode).toBe(0);
      expect(output(fault)).toContain("REACHED_SENTINEL");
      const config = runChild(
        `await import(${JSON.stringify(resolve(e2eRoot, "playwright.config.ts"))}); console.log("REACHED_SENTINEL");`,
      );
      expectDatabaseGuard(config);
    } finally {
      await rm(faultPath, { force: true });
    }
  });

  test("removing only the config guard exposes the config module", async () => {
    const sourcePath = resolve(e2eRoot, "playwright.config.ts");
    const faultPath = resolve(e2eRoot, ".story210-config-fault.ts");
    const source = await Bun.file(sourcePath).text();
    expect(source).toContain('requireEnvironment("DATABASE_URL")');
    await writeFile(faultPath, source.replace('requireEnvironment("DATABASE_URL")', '"unguarded"'));
    try {
      const fault = runChild(
        `await import(${JSON.stringify(faultPath)}); console.log("REACHED_SENTINEL");`,
      );
      expect(fault.exitCode).toBe(0);
      expect(output(fault)).toContain("REACHED_SENTINEL");
      const auth = runChild(
        `await import(${JSON.stringify(resolve(e2eRoot, "fixtures/auth.ts"))}); console.log("REACHED_SENTINEL");`,
      );
      expectDatabaseGuard(auth);
    } finally {
      await rm(faultPath, { force: true });
    }
  });

  test("the Playwright server receives a valid fixed test JWT key", () => {
    const config = resolve(e2eRoot, "playwright.config.ts");
    const result = runChild(
      `process.env.JWT_SECRET = "change-me-generate-with-openssl-rand-hex-32"; const config = (await import(${JSON.stringify(config)})).default; console.log(config.webServer[0].env.JWT_SECRET);`,
      "postgresql://story:secret@127.0.0.1:61234/story_210",
    );
    expect(result.exitCode).toBe(0);
    expect(result.stdout.toString().trim()).toMatch(/^[0-9a-f]{64}$/);
  });
});
