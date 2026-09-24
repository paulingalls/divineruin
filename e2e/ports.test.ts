import { expect, test } from "bun:test";
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";

const root = import.meta.dir;
const legacy = [3000 + 1, 8080 + 2, 8080 + 5, 9220 + 2].map(String);
// Playwright writes run output here; a primary checkout's reports carry its own origins.
const generated = new Set(["node_modules", "playwright-report", "test-results"]);

function authoredFiles(dir: string): string[] {
  if (!existsSync(dir)) throw new Error(`Missing E2E corpus: ${dir}`);
  return readdirSync(dir).flatMap((entry) => {
    if (generated.has(entry)) return [];
    const path = join(dir, entry);
    return statSync(path).isDirectory() ? authoredFiles(path) : [path];
  });
}

test("every authored E2E file uses the port module", () => {
  const files = authoredFiles(root).filter((path) => relative(root, path) !== "ports.ts");
  expect(files.length).toBeGreaterThan(20);
  for (const required of [
    "playwright.config.ts",
    "global-setup.ts",
    "fixtures/auth.ts",
    "specs/web-home.e2e.ts",
  ]) {
    expect(files.map((path) => relative(root, path))).toContain(required);
  }
  const hits = files.flatMap((path) => {
    const text = readFileSync(path, "utf8");
    return legacy
      .filter((port) => new RegExp(`(?<![0-9])${port}(?![0-9])`).test(text))
      .map((port) => `${relative(root, path)}:${port}`);
  });
  expect(hits).toEqual([]);
});

test("port module requires valid exported ports and builds origins", () => {
  const env = {
    ...process.env,
    E2E_API_PORT: "14001",
    E2E_APP_PORT: "14002",
    E2E_WEB_PORT: "14003",
    E2E_LH_DEBUG_PORT: "14004",
  };
  const source = `import * as ports from ${JSON.stringify(join(root, "ports.ts"))}; console.log([ports.API_ORIGIN, ports.APP_ORIGIN, ports.WEB_ORIGIN, ports.LH_DEBUG_PORT].join(" "));`;
  const run = (childEnv: NodeJS.ProcessEnv) =>
    Bun.spawnSync({
      cmd: [process.execPath, "-e", source],
      env: childEnv,
      stdout: "pipe",
      stderr: "pipe",
    });
  const valid = run(env);
  expect(valid.exitCode).toBe(0);
  expect(valid.stdout.toString()).toContain(
    "http://localhost:14001 http://localhost:14002 http://localhost:14003 14004",
  );
  for (const invalid of ["", "0", "65536", "14x01"]) {
    const result = run({ ...env, E2E_API_PORT: invalid });
    expect(result.exitCode).not.toBe(0);
    expect(result.stderr.toString()).toContain("E2E_API_PORT");
  }
});

test("Playwright binds and builds against this checkout's API", () => {
  const env = {
    ...process.env,
    E2E_API_PORT: "14001",
    E2E_APP_PORT: "14002",
    E2E_WEB_PORT: "14003",
    E2E_LH_DEBUG_PORT: "14004",
    DATABASE_URL: "postgresql://test@localhost:60001/test",
    REDIS_URL: "redis://localhost:60002",
  };
  const source = `const c = (await import(${JSON.stringify(join(root, "playwright.config.ts"))})).default; console.log(JSON.stringify(c.webServer));`;
  const result = Bun.spawnSync({
    cmd: [process.execPath, "-e", source],
    env,
    cwd: root,
    stdout: "pipe",
    stderr: "pipe",
  });
  expect(result.exitCode).toBe(0);
  const [api, app, web] = JSON.parse(result.stdout.toString()) as Array<{
    port?: number;
    url?: string;
    command: string;
    env: Record<string, string>;
  }>;
  expect(api.port).toBe(14001);
  expect(api.env.PORT).toBe("14001");
  expect(app.command).toContain("--port 14002");
  expect(app.url).toBe("http://localhost:14002/");
  expect(app.env.EXPO_PUBLIC_API_URL).toBe("http://localhost:14001");
  expect(web.url).toBe("http://localhost:14003/");
  expect(web.env.PORT).toBe("14003");
  expect(web.env.PUBLIC_API_URL).toBe("http://localhost:14001");
});
