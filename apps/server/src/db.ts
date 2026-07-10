import { SQL } from "bun";
import { requireEnv } from "./env.ts";

// The SQL client is built lazily on first use, not at import. Importing db.ts
// (e.g. transitively via items.ts/recipes.ts in a pure unit test) therefore does
// NOT require DATABASE_URL — only an actual query (a `sql`...`` tagged template or
// a `sql.begin(...)` / other method call) constructs the client and reads the env.
// This keeps mocked + pure-loader unit tests runnable without a DB or .env, while
// production and integration code resolve DATABASE_URL exactly as before.
let client: SQL | undefined;
function getClient(): SQL {
  // idleTimeout: 0 (disabled) — NOT 30s. Bun.sql closes a connection after
  // idleTimeout seconds idle, but races a query dispatched onto that connection
  // as it closes, failing it with ERR_POSTGRES_IDLE_TIMEOUT. Under load (e.g. the
  // pre-push gate's concurrent lanes) connections idle past 30s and catchup
  // queries intermittently fail — the recurring non-deterministic e2e flake
  // (SMM risk 5d3e56d533b4). A long-lived server pool should keep its (max 5)
  // connections warm; 0 removes the race entirely.
  return (client ??= new SQL({ url: requireEnv("DATABASE_URL"), max: 5, idleTimeout: 0 }));
}

export const sql = new Proxy(function lazySql() {} as unknown as SQL, {
  // `sql`...`` — tagged-template query.
  apply(_target, _thisArg, args: unknown[]): unknown {
    return (getClient() as unknown as (...a: unknown[]) => unknown)(...args);
  },
  // `sql.begin`, `sql.close`, etc. — forward to the real client (methods bound to it).
  get(_target, prop: PropertyKey): unknown {
    // Keep `sql` non-thenable so an accidental `await sql` / Promise probe never
    // forces construction (and never needs the env) — only real queries do.
    if (prop === "then") return undefined;
    const value = (getClient() as unknown as Record<PropertyKey, unknown>)[prop];
    return typeof value === "function"
      ? (value as (...a: unknown[]) => unknown).bind(getClient())
      : value;
  },
});
