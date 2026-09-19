import { afterEach, describe, expect, test } from "bun:test";
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

test("ownership is checked before reachability and reachable reuse", async () => {
  const { calls, deps } = fakeDeps(true);
  expect(await ensureDbUp(deps)).toBe(false);
  expect(calls).toEqual([
    `authorize-runtime:${process.env.DATABASE_URL}:${process.env.REDIS_URL ?? ""}`,
    "reachable",
    "authorize:reuse",
  ]);
});

test("the real shared authority rejects a foreign runtime endpoint", () => {
  expect(
    authorizeRuntime("postgresql://u:p@localhost:55432/divineruin", undefined),
  ).rejects.toThrow("runtime DATABASE_URL");
});

test("the real shared authority rejects a foreign ambient Redis endpoint", () => {
  expect(authorizeRuntime(process.env.DATABASE_URL!, "redis://localhost:56379")).rejects.toThrow(
    "runtime REDIS_URL",
  );
});

test("readiness raises ownership refusal instead of returning not-ready", async () => {
  expect(
    isAcceptingQueries("divineruin", () =>
      Promise.resolve({
        exit: 78,
        stderr: "worktree ownership: project belongs to foreign checkout",
      }),
    ),
  ).rejects.toThrow("foreign checkout");
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
