import { readdir } from "node:fs/promises";
import { join } from "node:path";

type Sql = InstanceType<typeof Bun.SQL>;

export function requireDatabaseUrl(env: Record<string, string | undefined> = process.env): string {
  const databaseUrl = env.DATABASE_URL;
  if (!databaseUrl) throw new Error("DATABASE_URL is not set");
  return databaseUrl;
}

async function ensureMigrationsTable(sql: Sql) {
  await sql`
    CREATE TABLE IF NOT EXISTS _migrations (
      name TEXT PRIMARY KEY,
      applied_at TIMESTAMPTZ DEFAULT NOW()
    )
  `;
}

async function getAppliedMigrations(sql: Sql): Promise<Set<string>> {
  const rows: Array<{ name: string }> = await sql`SELECT name FROM _migrations ORDER BY name`;
  return new Set(rows.map((r) => r.name));
}

async function run() {
  console.log("Running migrations...");
  const sql = new Bun.SQL(requireDatabaseUrl());

  await ensureMigrationsTable(sql);
  const applied = await getAppliedMigrations(sql);

  const migrationsDir = join(import.meta.dir, "migrations");
  const files = (await readdir(migrationsDir)).filter((f) => f.endsWith(".sql")).sort();

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

  console.log(count > 0 ? `Applied ${count} migration(s).` : "No new migrations to apply.");
  process.exit(0);
}

if (import.meta.main) {
  run().catch((err) => {
    console.error("Migration failed:", err);
    process.exit(1);
  });
}
