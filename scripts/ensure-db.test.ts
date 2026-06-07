import { test, expect, describe } from "bun:test";
import { parseHostPort, parseUser } from "./ensure-db.ts";

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
