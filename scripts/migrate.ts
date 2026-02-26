import { readdir } from "node:fs/promises";
import { join } from "node:path";

const sql = Bun.sql;

async function ensureMigrationsTable() {
  await sql`
    CREATE TABLE IF NOT EXISTS _migrations (
      name TEXT PRIMARY KEY,
      applied_at TIMESTAMPTZ DEFAULT NOW()
    )
  `;
}

async function getAppliedMigrations(): Promise<Set<string>> {
  const rows = await sql`SELECT name FROM _migrations ORDER BY name`;
  return new Set(rows.map((r: { name: string }) => r.name));
}

async function run() {
  console.log("Running migrations...");

  await ensureMigrationsTable();
  const applied = await getAppliedMigrations();

  const migrationsDir = join(import.meta.dir, "migrations");
  const files = (await readdir(migrationsDir))
    .filter((f) => f.endsWith(".sql"))
    .sort();

  let count = 0;
  for (const file of files) {
    if (applied.has(file)) {
      console.log(`  skip: ${file} (already applied)`);
      continue;
    }

    const filePath = join(migrationsDir, file);
    const content = await Bun.file(filePath).text();

    await sql.begin(async (tx) => {
      await tx.unsafe(content);
      await tx`INSERT INTO _migrations (name) VALUES (${file})`;
    });

    console.log(`  done: ${file}`);
    count++;
  }

  console.log(
    count > 0
      ? `Applied ${count} migration(s).`
      : "No new migrations to apply."
  );
  process.exit(0);
}

run().catch((err) => {
  console.error("Migration failed:", err);
  process.exit(1);
});
