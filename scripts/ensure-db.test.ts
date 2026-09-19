import { test, expect, describe, spyOn } from "bun:test";
import { Socket } from "node:net";
import { ensureDbUp, parseHostPort, parseUser } from "./ensure-db.ts";
import { requireDatabaseUrl } from "./migrate.ts";

// The docker subprocess + socket probe in ensure-db.ts are integration glue,
// verified end-to-end (stop compose -> `bun run test:all` auto-starts it). This
// pins the one pure piece — URL parsing — mirroring the Python helper's test
// (apps/agent/tests/test_db_lifecycle.py).
describe("parseHostPort", () => {
  test("reads host and port from a postgres URL", () => {
    expect(parseHostPort("postgresql://u:p@localhost:55432/divineruin")).toEqual({
      host: "localhost",
      port: 55432,
    });
  });

  test("defaults the port to 5432 when absent", () => {
    expect(parseHostPort("postgresql://u:p@db.example/divineruin")).toEqual({
      host: "db.example",
      port: 5432,
    });
  });
});

describe("parseUser", () => {
  test("reads the user from a postgres URL", () => {
    expect(parseUser("postgresql://divineruin:p@localhost:55432/divineruin")).toBe("divineruin");
  });

  test("defaults to divineruin when absent", () => {
    expect(parseUser("postgresql://localhost:55432/divineruin")).toBe("divineruin");
  });
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

test("migration requires DATABASE_URL", () => {
  expect(() => requireDatabaseUrl({})).toThrow("DATABASE_URL");
});

test("service commands explicitly load the root environment", async () => {
  const expected = {
    "package.json": {
      "dev:server": "--env-file=../../.env",
      migrate: "--env-file=.env",
      seed: "--env-file=../.env",
      "dev:agent": "--env-file=../../.env",
      "dev:worker": "--env-file=../../.env",
      "test:server": "--env-file=.env",
      test: "--env-file=.env",
      "test:python": "--env-file=../../.env",
      "test:acceptance": "--env-file=../../.env",
      "test:acceptance:nollm": "--env-file=../../.env",
      "test:all": "--env-file=.env",
    },
    "apps/server/package.json": {
      dev: "--env-file=../../.env",
      start: "--env-file=../../.env",
      test: "--env-file=../../.env",
    },
  } as const;
  expect(Object.values(expected).flatMap(Object.keys).length).toBeGreaterThan(0);
  for (const [manifest, commands] of Object.entries(expected)) {
    const packageJson: unknown = await Bun.file(new URL(`../${manifest}`, import.meta.url)).json();
    if (!packageJson || typeof packageJson !== "object" || !("scripts" in packageJson)) {
      throw new Error(`${manifest} has no scripts`);
    }
    const scripts = packageJson.scripts;
    if (!scripts || typeof scripts !== "object") throw new Error(`${manifest} scripts are invalid`);
    for (const [name, envFile] of Object.entries(commands)) {
      const command = (scripts as Record<string, unknown>)[name];
      expect(command).toBeString();
      if (typeof command !== "string") throw new Error(`${manifest} has no ${name} command`);
      expect(command).toContain(envFile);
    }
  }
});
