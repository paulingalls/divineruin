import { afterEach, beforeAll, beforeEach, describe, expect, spyOn, test } from "bun:test";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { Socket } from "node:net";
import { runMigrations } from "./migrate.ts";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  authorizeRuntime,
  ensureDbUp,
  isAcceptingQueries,
  isCiServiceMode,
  parseHostPort,
  parseUser,
  stopIfStarted,
  type LifecycleDeps,
} from "./ensure-db.ts";

const originalEnv = { ...process.env };
// A caller with the CI service markers exported (an `act` run, a CI shell) would
// otherwise steer ensureDbUp down its ci branch. Cases that need them set them.
beforeEach(() => {
  delete process.env.GITHUB_ACTIONS;
  delete process.env.DIVINERUIN_CI_SERVICE_DB;
});
afterEach(() => {
  process.env = { ...originalEnv };
});

function fakeDeps(reachable: boolean) {
  const calls: string[] = [];
  const deps: LifecycleDeps = {
    authorizeRuntime: (databaseUrl, redisUrl) => {
      calls.push(`authorize-runtime:${databaseUrl}:${redisUrl ?? ""}`);
      return Promise.resolve();
    },
    authorize: (intent) => {
      calls.push(`authorize:${intent}`);
      return Promise.resolve();
    },
    compose: (intent, ...args) => {
      calls.push(`compose:${intent}:${args.join(" ")}`);
      return Promise.resolve(0);
    },
    reachable: () => {
      calls.push("reachable");
      return Promise.resolve(reachable);
    },
    accepting: () => Promise.resolve(true),
    sleep: () => Promise.resolve(),
    now: () => 0,
  };
  return { calls, deps };
}

describe("URL parsing", () => {
  test("reads host, port, and user", () => {
    const url = "postgresql://divineruin:p@localhost:55432/divineruin";
    expect(parseHostPort(url)).toEqual({ host: "localhost", port: 55432 });
    expect(parseUser(url)).toBe("divineruin");
  });

  test("uses protocol defaults", () => {
    expect(parseHostPort("postgresql://localhost/db")).toEqual({ host: "localhost", port: 5432 });
    expect(parseUser("postgresql://localhost/db")).toBe("divineruin");
  });
});

test("ownership is checked before reachability and reachable connection", async () => {
  const { calls, deps } = fakeDeps(true);
  expect(await ensureDbUp(deps)).toBe(false);
  expect(calls).toEqual([
    `authorize-runtime:${process.env.DATABASE_URL}:${process.env.REDIS_URL ?? ""}`,
    "reachable",
    "authorize:connect",
  ]);
});

// The real authority answers about the checkout it runs in, so a hardcoded
// "foreign" endpoint is only foreign from SOME checkouts: :55432/:56379 are the
// primary's OWN endpoints, and CI has no repo-root .env at all. These cases
// drive the real script against a disposable checkout whose settings this test
// generates, so what is owned and what is foreign is known here.
const OWNER_SCRIPT = new URL("./worktree-common.sh", import.meta.url).pathname;
let fixture: { dir: string; settings: Record<string, string> };

function setting(key: string): string {
  const value = fixture.settings[key];
  if (value === undefined) throw new Error(`the fixture checkout has no ${key}`);
  return value;
}

function ownerIn(cwd: string) {
  return async (...args: string[]) => {
    const proc = Bun.spawn(["bash", OWNER_SCRIPT, ...args], { cwd, stdout: "pipe", stderr: "pipe" });
    const stderr = await new Response(proc.stderr).text();
    return { exit: await proc.exited, stderr };
  };
}

beforeAll(() => {
  const dir = mkdtempSync(join(tmpdir(), "dr-ensure-db-"));
  Bun.spawnSync(["git", "init", "-q"], { cwd: dir });
  const expected = Bun.spawnSync(["bash", OWNER_SCRIPT, "expected-env"], { cwd: dir });
  const text = new TextDecoder().decode(expected.stdout);
  writeFileSync(join(dir, ".env"), text);
  const settings = Object.fromEntries(
    text
      .trim()
      .split("\n")
      .map((line) => {
        const at = line.indexOf("=");
        return [line.slice(0, at), line.slice(at + 1)] as const;
      }),
  );
  fixture = { dir, settings };
  process.on("exit", () => rmSync(dir, { recursive: true, force: true }));
});

test("the real shared authority accepts the checkout's own endpoints", async () => {
  await authorizeRuntime(
    setting("DATABASE_URL"),
    setting("REDIS_URL"),
    ownerIn(fixture.dir),
  );
});

test("the real shared authority rejects a foreign runtime endpoint", () => {
  const foreign = Number(setting("POSTGRES_HOST_PORT")) + 1;
  expect(
    authorizeRuntime(
      `postgresql://u:p@localhost:${foreign}/divineruin`,
      setting("REDIS_URL"),
      ownerIn(fixture.dir),
    ),
  ).rejects.toThrow("runtime DATABASE_URL");
});

test("the real shared authority rejects a foreign ambient Redis endpoint", () => {
  const foreign = Number(setting("VALKEY_HOST_PORT")) + 1;
  expect(
    authorizeRuntime(
      setting("DATABASE_URL"),
      `redis://localhost:${foreign}`,
      ownerIn(fixture.dir),
    ),
  ).rejects.toThrow("runtime REDIS_URL");
});

test("readiness raises ownership refusal instead of returning not-ready", async () => {
  const calls: string[][] = [];
  expect(
    isAcceptingQueries("divineruin", (...args) => {
      calls.push(args);
      return Promise.resolve({
        exit: 78,
        stderr: "worktree ownership: project belongs to foreign checkout",
      });
    }),
  ).rejects.toThrow("foreign checkout");
  expect(calls).toEqual([
    ["compose", "connect", "exec", "-T", "postgres", "pg_isready", "-U", "divineruin"],
  ]);
  expect(
    await isAcceptingQueries("divineruin", () => Promise.resolve({ exit: 1, stderr: "not ready" })),
  ).toBe(false);
});

test("an ownership refusal prevents the reachability probe", async () => {
  const { calls, deps } = fakeDeps(true);
  deps.authorizeRuntime = (databaseUrl, redisUrl) => {
    calls.push(`authorize-runtime:${databaseUrl}:${redisUrl ?? ""}`);
    return Promise.reject(new Error("foreign checkout owner"));
  };
  try {
    await ensureDbUp(deps);
    throw new Error("expected ownership refusal");
  } catch (error) {
    expect(error).toBeInstanceOf(Error);
    expect((error as Error).message).toContain("foreign checkout owner");
  }
  expect(calls).toEqual([
    `authorize-runtime:${process.env.DATABASE_URL}:${process.env.REDIS_URL ?? ""}`,
  ]);
});

test("an owned unreachable database starts only through create intent", async () => {
  const { calls, deps } = fakeDeps(false);
  expect(await ensureDbUp(deps)).toBe(true);
  expect(calls).toEqual([
    `authorize-runtime:${process.env.DATABASE_URL}:${process.env.REDIS_URL ?? ""}`,
    "reachable",
    "compose:create:up -d",
  ]);
});

test("stop uses the destructive ownership intent", async () => {
  const { calls, deps } = fakeDeps(true);
  await stopIfStarted(true, deps);
  expect(calls).toEqual(["compose:destroy:stop"]);
});

test("stop rejects a nonzero Compose result", () => {
  const { calls, deps } = fakeDeps(true);
  deps.compose = (intent, ...args) => {
    calls.push(`compose:${intent}:${args.join(" ")}`);
    return Promise.resolve(1);
  };

  expect(stopIfStarted(true, deps)).rejects.toThrow("docker compose stop` failed (exit 1)");
  expect(calls).toEqual(["compose:destroy:stop"]);
});

test("CI service mode refuses stop without invoking Compose", () => {
  process.env.GITHUB_ACTIONS = "true";
  process.env.DIVINERUIN_CI_SERVICE_DB = "1";
  const { calls, deps } = fakeDeps(true);

  expect(stopIfStarted(true, deps)).rejects.toThrow("cannot stop Compose resources");
  expect(calls).toEqual([]);
});

test("CI mode requires both explicit signals", () => {
  expect(isCiServiceMode({ GITHUB_ACTIONS: "true", DIVINERUIN_CI_SERVICE_DB: "1" })).toBe(true);
  expect(isCiServiceMode({ GITHUB_ACTIONS: "true" })).toBe(false);
  expect(isCiServiceMode({ DIVINERUIN_CI_SERVICE_DB: "1" })).toBe(false);
});

test("CI mode never invokes Compose", async () => {
  process.env.GITHUB_ACTIONS = "true";
  process.env.DIVINERUIN_CI_SERVICE_DB = "1";
  const { calls, deps } = fakeDeps(false);
  try {
    await ensureDbUp(deps);
    throw new Error("expected CI reachability refusal");
  } catch (error) {
    expect(error).toBeInstanceOf(Error);
    expect((error as Error).message).toContain("Compose mutation is disabled");
  }
  expect(calls).toEqual(["authorize:ci", "reachable"]);
});

test("missing DATABASE_URL fails before socket or compose actions", async () => {
  const prior = process.env.DATABASE_URL;
  delete process.env.DATABASE_URL;
  const connect = spyOn(Socket.prototype, "connect");
  const spawn = spyOn(Bun, "spawn");
  try {
    let failure: unknown;
    try {
      await ensureDbUp();
    } catch (error) {
      failure = error;
    }
    expect(failure).toBeInstanceOf(Error);
    if (!(failure instanceof Error)) throw failure;
    expect(failure.message).toContain("DATABASE_URL");
    expect(connect).not.toHaveBeenCalled();
    expect(spawn).not.toHaveBeenCalled();
  } finally {
    connect.mockRestore();
    spawn.mockRestore();
    if (prior === undefined) delete process.env.DATABASE_URL;
    else process.env.DATABASE_URL = prior;
  }
});

test("the migration entrypoint refuses before it opens a SQL client", async () => {
  const prior = process.env.DATABASE_URL;
  delete process.env.DATABASE_URL;
  const constructed = (): never => {
    throw new Error("Bun.SQL constructed without a DATABASE_URL guard");
  };
  // spyOn over a class narrows mockImplementation's parameter to never.
  const sql = spyOn(Bun, "SQL").mockImplementation(constructed as never);
  try {
    let failure: unknown;
    try {
      await runMigrations();
    } catch (error) {
      failure = error;
    }
    expect(failure).toBeInstanceOf(Error);
    if (!(failure instanceof Error)) throw failure;
    expect(failure.message).toContain("DATABASE_URL is not set");
    expect(sql).not.toHaveBeenCalled();
  } finally {
    sql.mockRestore();
    if (prior === undefined) delete process.env.DATABASE_URL;
    else process.env.DATABASE_URL = prior;
  }
});
