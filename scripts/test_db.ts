const sql = Bun.sql;
const redis = Bun.redis;

let passed = 0;
let failed = 0;

function ok(name: string) {
  console.log(`  pass: ${name}`);
  passed++;
}

function fail(name: string, err: unknown) {
  console.error(`  FAIL: ${name} —`, err);
  failed++;
}

console.log("Testing database connectivity...\n");

// PostgreSQL: insert, select, clean up
try {
  const testData = { name: "Test", tier: 1, region: "test" };
  await sql`
    INSERT INTO locations (id, data)
    VALUES ('__test_location', ${testData}::jsonb)
    ON CONFLICT (id) DO UPDATE SET data = EXCLUDED.data
  `;

  const rows = await sql`SELECT id, data FROM locations WHERE id = '__test_location'`;
  if (rows.length !== 1) throw new Error(`Expected 1 row, got ${rows.length}`);
  if (rows[0].data.name !== "Test") throw new Error(`Expected name 'Test', got '${rows[0].data.name}'`);

  await sql`DELETE FROM locations WHERE id = '__test_location'`;
  ok("PostgreSQL INSERT/SELECT/DELETE JSONB");
} catch (err) {
  fail("PostgreSQL INSERT/SELECT/DELETE JSONB", err);
}

// Redis: set, get, clean up
try {
  await redis.set("__test_key", "divineruin_ok");
  const val = await redis.get("__test_key");
  if (val !== "divineruin_ok") throw new Error(`Expected 'divineruin_ok', got '${val}'`);

  await redis.del("__test_key");
  ok("Redis SET/GET/DEL");
} catch (err) {
  fail("Redis SET/GET/DEL", err);
}

console.log(`\nResults: ${passed} passed, ${failed} failed`);
process.exit(failed > 0 ? 1 : 0);
