// Shared db.ts mock for the activities REST handlers (create + read paths).
//
// Results are matched to queries by a SQL substring/regex predicate, NOT by call
// position. Inserting or reordering a pre-transaction read therefore no longer
// shifts every downstream stub — a positional array silently mis-mapped on any
// read-order change and could false-green (concern 109567241849, flagged twice).
//
// Only queries that return ROWS need a stub: an unmatched query resolves to [],
// so locks, deletes, and inserts (all empty results) need no entry. Each stub's
// `match` doubles as documentation of which statement supplies the rows.
//
// The mock factory is exported (not self-installed) so each test file calls
// `mock.module("./db.ts", dbMockFactory)` at its own top level. Bun's mock.module
// is global and most-recent-wins; a one-time install in this shared module would
// be clobbered by sibling test files that also mock ./db.ts, leaving handlers
// bound to the wrong mock. Per-file install (the pattern the other server tests
// use) keeps the binding ours while the resolution logic + state stay shared here.
export type QueryStub = { match: string | RegExp; result: unknown[] };

let stubs: QueryStub[] = [];
let consumed: boolean[] = [];
let capturedQueries: { sql: string; values: unknown[] }[] = [];

function resolveResult(sql: string): unknown[] {
  // First UNCONSUMED stub whose predicate matches. Consuming in order keeps two
  // identical-SQL reads (rare) deterministic without coupling to global position.
  for (let i = 0; i < stubs.length; i++) {
    if (consumed[i]) continue;
    const m = stubs[i]!.match;
    const hit = typeof m === "string" ? sql.includes(m) : m.test(sql);
    if (hit) {
      consumed[i] = true;
      return stubs[i]!.result;
    }
  }
  return [];
}

function mockTaggedTemplate(strings: TemplateStringsArray, ...values: unknown[]) {
  const sql = strings.join(" ");
  capturedQueries.push({ sql, values });
  return Promise.resolve(resolveResult(sql));
}

/**
 * Factory for `mock.module("./db.ts", dbMockFactory)`. Each test file installs it
 * at its own top level (before the dynamic handler import) so the binding is theirs.
 */
export function dbMockFactory(): { sql: unknown } {
  const mockSql = Object.assign(mockTaggedTemplate, {
    close: () => Promise.resolve(),
    begin: async (fn: (tx: typeof mockTaggedTemplate) => Promise<unknown>) => {
      return fn(mockSql);
    },
  });
  // Support sql(values) call form for IN expressions (distinct from tagged template calls)
  const proxy = new Proxy(mockSql, {
    apply(_target, _thisArg, args: [unknown, ...unknown[]]) {
      const first = args[0] as { raw?: unknown } | unknown[] | undefined;
      // Tagged template: first arg has .raw property
      if (first && typeof first === "object" && "raw" in first)
        return mockTaggedTemplate(first as TemplateStringsArray, ...args.slice(1));
      // sql(array) form for IN clauses — return passthrough
      if (Array.isArray(first)) return first;
      return mockTaggedTemplate(first as TemplateStringsArray, ...args.slice(1));
    },
  });
  return { sql: proxy };
}

/** Install the row-returning stubs for the next handler call (matched by SQL). */
export function setQueryStubs(next: QueryStub[]): void {
  stubs = next;
  consumed = Array.from({ length: next.length }, () => false);
}

/** Reset all mock state — call in beforeEach. */
export function resetMockDb(): void {
  stubs = [];
  consumed = [];
  capturedQueries = [];
}

/** The SQL text + bound values captured per query, in call order. */
export function getCapturedQueries(): { sql: string; values: unknown[] }[] {
  return capturedQueries;
}

export function makeRequest(method: string, path: string, body?: Record<string, unknown>): Request {
  const opts: RequestInit = { method };
  if (body) {
    opts.body = JSON.stringify(body);
    opts.headers = { "Content-Type": "application/json" };
  }
  return new Request(`http://localhost${path}`, opts);
}
