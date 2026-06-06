import { test, expect, afterEach } from "bun:test";

import { assertDbRequired } from "./test-util";

const originalRequireDb = process.env.REQUIRE_DB;

afterEach(() => {
  if (originalRequireDb === undefined) delete process.env.REQUIRE_DB;
  else process.env.REQUIRE_DB = originalRequireDb;
});

test("assertDbRequired throws when REQUIRE_DB is set but the DB is absent", () => {
  process.env.REQUIRE_DB = "1";
  expect(() => assertDbRequired(false)).toThrow();
});

test("assertDbRequired passes when REQUIRE_DB is set and the DB is present", () => {
  process.env.REQUIRE_DB = "1";
  expect(() => assertDbRequired(true)).not.toThrow();
});

test("assertDbRequired passes when REQUIRE_DB is unset, regardless of the DB", () => {
  delete process.env.REQUIRE_DB;
  expect(() => assertDbRequired(false)).not.toThrow();
  expect(() => assertDbRequired(true)).not.toThrow();
});
