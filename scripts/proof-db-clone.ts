import { SQL } from "bun";

const admin = process.env.PROOF_ACCEPTANCE_ADMIN;
if (!admin || process.env.PROOF_ACCEPTANCE_TEMPLATE !== "proof_template") {
  throw new Error("Bun proof tasks require the seeded provider");
}
const sql = new SQL(admin);
const name = `proof_bun_${crypto.randomUUID().replaceAll("-", "")}`;
const url = new URL(admin);
url.pathname = `/${name}`;
let status: number;
try {
  await sql.unsafe(`CREATE DATABASE "${name}" TEMPLATE "proof_template"`);
  const child = Bun.spawn(["sh", "-c", Bun.argv.slice(2).join(" ")], {
    env: { ...process.env, DATABASE_URL: url.href },
    stdout: "inherit",
    stderr: "inherit",
  });
  status = await child.exited;
} finally {
  await sql.unsafe(`DROP DATABASE IF EXISTS "${name}" WITH (FORCE)`);
  await sql.close();
}
process.exit(status);
