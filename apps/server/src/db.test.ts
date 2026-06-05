import { describe, expect, test } from "bun:test";

import { sql } from "./db.ts";

// db.ts exports `sql` as a lazy Proxy over Bun.SQL: the apply trap runs
// tagged-template queries, the get trap forwards methods (sql.begin, etc.)
// bound to the real client, and a `then` guard keeps `sql` non-thenable so
// `await sql` / Promise probes never force construction (or read the env).
// A Bun SQL upgrade could silently break trap forwarding or the guard, so
// this regression test exercises both traps live. The live queries skip when
// DATABASE_URL is unset, keeping the env-free unit lane green; the pre-push
// server lane provisions DATABASE_URL (scripts/test-env.sh) so they run there.
const hasDb = Boolean(process.env.DATABASE_URL);

// Anti-silent-skip sentinel: the server lane sets REQUIRE_DB=1 (package.json
// test:server). If DATABASE_URL ever drifts to unset in that lane, the live-PG
// describe below would silently skip and the lane would go green untested — so
// fail loud here instead. The env-free unit lane leaves REQUIRE_DB unset and skips.
test("DATABASE_URL present when the lane requires it (REQUIRE_DB sentinel)", () => {
  if (process.env.REQUIRE_DB) expect(hasDb).toBe(true);
});

// Env-free: probing `.then` hits the guard at db.ts and returns before
// getClient(), so it neither constructs the client nor reads the env. The
// laziness guarantee itself is enforced by the whole env-free unit lane — every
// other server test imports db.ts (transitively) with no DATABASE_URL and would
// throw on any eager getClient(). This test pins the observable shape of that
// guard: `.then` is undefined and the Proxy target stays callable.
test("sql exposes a non-thenable, callable Proxy (then-guard returns undefined)", () => {
  expect((sql as unknown as { then?: unknown }).then).toBeUndefined();
  expect(typeof sql).toBe("function"); // the Proxy target is a function
});

describe.skipIf(!hasDb)("sql live-PG trap forwarding", () => {
  test("apply trap: tagged-template read round-trips", async () => {
    const rows = await sql<{ one: number }[]>`SELECT 1 AS one`;
    expect(Number(rows[0]!.one)).toBe(1);
  });

  test("get trap: sql.begin runs a transaction round-trip", async () => {
    const result = await sql.begin(async (tx) => {
      const r = await tx<{ two: number }[]>`SELECT 2 AS two`;
      return Number(r[0]!.two);
    });
    expect(result).toBe(2);
  });
});
