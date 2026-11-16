import { normalizeEmail } from "../apps/server/src/email.ts";

const args = Bun.argv.slice(2);
const remove = args[0] === "--remove";
const email = normalizeEmail(args[remove ? 1 : 0]);
if (args.length !== (remove ? 2 : 1) || !email) {
  throw new Error("Usage: bun run allow [--remove] <email>");
}
const databaseUrl = process.env.DATABASE_URL;
if (!databaseUrl) throw new Error("DATABASE_URL is not set");
const sql = new Bun.SQL(databaseUrl);
try {
  if (remove) {
    await sql`DELETE FROM signin_allowlist WHERE email=${email}`;
  } else {
    await sql`INSERT INTO signin_allowlist(email) VALUES(${email}) ON CONFLICT(email) DO NOTHING`;
  }
} finally {
  await sql.close();
}
