import { test, expect, describe, spyOn } from "bun:test";
import { Socket } from "node:net";
import { ensureDbUp, parseHostPort, parseUser } from "./ensure-db.ts";
import { runMigrations } from "./migrate.ts";

// Mirrors the Python helper's test (apps/agent/tests/test_db_lifecycle.py): URL
// parsing, and the environment guards that must fire before either entry point
// touches a socket, a compose subprocess or a SQL client.
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
