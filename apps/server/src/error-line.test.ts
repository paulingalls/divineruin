import { expect, test } from "bun:test";
import { resolve } from "node:path";

const root = resolve(import.meta.dir, "../../..");
const secret =
  "Bearer private-key person@example.com I open the silver door\nAuthorization: secret";
const env = {
  NODE_ENV: "production",
  PORT: "0",
  SERVER_HOST: "127.0.0.1",
  ...Object.fromEntries(
    "DATABASE_URL REDIS_URL JWT_SECRET INTERNAL_SECRET CORS_ORIGIN LIVEKIT_URL LIVEKIT_API_KEY LIVEKIT_API_SECRET GEMINI_API_KEY RESEND_API_KEY"
      .split(" ")
      .map((k) => [k, "synthetic"]),
  ),
  MEDIA_DIR: "/tmp/synthetic-media",
};
async function child(script: string, values: Record<string, string> = env, entry = false) {
  const proc = Bun.spawn(
    [
      process.execPath,
      "--no-env-file",
      ...(entry ? ["run", "apps/server/src/index.ts"] : ["-e", script]),
    ],
    { cwd: root, env: values, stdout: "pipe", stderr: "pipe" },
  );
  const timeout = setTimeout(() => proc.kill(), 10000);
  try {
    const [code, out, err] = await Promise.all([
      proc.exited,
      new Response(proc.stdout).text(),
      new Response(proc.stderr).text(),
    ]);
    return { code, out, err };
  } finally {
    clearTimeout(timeout);
    proc.kill();
  }
}
function lines(output: string) {
  return output.split("\n").flatMap((line) => {
    try {
      const value = JSON.parse(line) as Record<string, string>;
      return value.service === "server" ? [value] : [];
    } catch {
      return [];
    }
  });
}
function check(line: Record<string, string>) {
  expect(Object.keys(line).sort()).toEqual(["message", "service", "stack", "time"]);
  expect(Number.isNaN(Date.parse(line.time!))).toBe(false);
  expect(line.message).toMatch(/^Server (request failed|fatal)(: Error)?$/);
  expect(line.stack!.length).toBeGreaterThan(0);
  for (const part of (secret + " untrusted").split(/\s+/).filter((p) => p.length > 3))
    expect(JSON.stringify(line)).not.toContain(part);
}
test("real requests retain Bun's response and report abandoned errors privately once", async () => {
  const result = await child(`
    import { mock } from "bun:test";
    let healthCalls=0;
    const fail = () => { const e = new Error(${JSON.stringify(secret)}); e.stack += "\\n    at leak (https://user:private-key@example.com/file.ts:1:2)"; throw e; };
    mock.module("./apps/server/src/health.ts", () => ({handleHealth: () => { healthCalls++; if (healthCalls === 2) throw 'untrusted speech'; if (healthCalls === 3) {const e=new Error(${JSON.stringify(secret)});e.stack=${JSON.stringify(secret)};throw e;} return fail(); }}));
    mock.module("./apps/server/src/auth.ts", () => ({requireAuth: async () => ({playerId: "synthetic"}), handleRequestCode() {}, handleVerifyCode() {}, handleGetMe() {}, signJwt() {}, verifyJwt() {}}));
    mock.module("./apps/server/src/db.ts", () => ({sql: fail}));
    mock.module("./apps/server/src/media-dir.ts", () => ({mediaDir: () => "/tmp/synthetic-media", validateMediaDir: async () => {}}));
    for (const [file, names] of Object.entries({locations:["loadLocations"],errand_risk:["loadDestinationDangerLevels"],spells:["loadSpells"],training_state_machine:["loadTrainingActivityTypes"],activity_templates:["loadTrainingPrograms","loadErrandTemplates"],recipes:["loadRecipes"],items:["loadItems"],archetypes:["loadArchetypes"],abilities:["loadAbilities"],mentor_variants:["loadMentorVariants"],role_archetypes:["loadRoleArchetypes"],milestones:["loadMilestones"],pricing:["loadPricing"]})) { const path="./apps/server/src/"+file+".ts"; const original=await import(path); mock.module(path, () => ({...original,...Object.fromEntries(names.map(n => [n, async () => []]))})); }
    const {startServer} = await import("./apps/server/src/index.ts");
    const server = await startServer();
    const baseline = Bun.serve({port:0, hostname:"127.0.0.1",fetch:fail});
    const read = async (url, init) => {const r=await fetch(url, init); return [r.status, r.headers.get("content-type"), await r.text(), Object.fromEntries([...r.headers].filter(([key]) => key !== "date"))];};
    console.log(JSON.stringify({responses:[await read(baseline.url), await read(new URL("/api/health",server.url)), await read(new URL("/missing",server.url)), await read(new URL("/api/god-whispers/test/played",server.url),{method:"POST",headers:{Authorization:${JSON.stringify(secret.split("\n")[0])}}})]}));
    await read(new URL("/api/health?raw",server.url));
    await read(new URL("/api/health?hostile",server.url));
    server.stop(true); baseline.stop(true); process.exit(0);
  `);
  expect(result.code, result.err).toBe(0);
  const { responses } = JSON.parse(
    result.out.split("\n").find((l) => l.startsWith('{"responses"'))!,
  ) as { responses: [number, string, string, Record<string, string>][] };
  expect(responses[0]!.slice(0, 3)).toEqual([500, "text/plain", "Something went wrong!"]);
  expect(responses[1]).toEqual(responses[0]);
  expect(responses[2]![0]).toBe(404);
  expect(responses[3]!.slice(0, 3)).toEqual([
    500,
    "application/json;charset=utf-8",
    '{"error":"Internal server error"}',
  ]);
  expect(lines(result.out)).toHaveLength(0);
  const errors = lines(result.err);
  expect(errors).toHaveLength(4);
  errors.forEach(check);
  expect(errors[0]!.stack).toContain("[eval]");
  expect(errors[2]!.stack).toContain("error-line.ts");
  expect(errors[3]!.stack).toContain("error-line.ts");
});
test("production configuration and rejected startup await keep nonzero termination", async () => {
  for (const values of [{ NODE_ENV: "production" }, { ...env, MEDIA_DIR: "relative" }]) {
    const result = await child("", values, true);
    expect(result.code).not.toBe(0);
    expect(lines(result.out)).toHaveLength(0);
    const errors = lines(result.err);
    expect(errors).toHaveLength(1);
    check(errors[0]!);
  }
});
