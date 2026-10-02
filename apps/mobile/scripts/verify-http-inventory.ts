import { SQL } from "bun";
import { resolve } from "node:path";
import { withOwnedProcesses, type OwnedProcesses } from "./native-transport-processes";
import { createRealOwnedSimulatorDeps, resolveOwnedSimulator } from "./owned-simulator";
import { developmentClientUrl } from "./verify-native-transport";

const root = resolve(import.meta.dir, "../../..");
const sql = new SQL(process.env.DATABASE_URL!);
const env = (extra: Record<string, string>) => ({
  ...Object.fromEntries(
    Object.entries(process.env).filter((e): e is [string, string] => e[1] !== undefined),
  ),
  ...extra,
});
async function port() {
  const server = Bun.serve({ hostname: "127.0.0.1", port: 0, fetch: () => new Response() });
  const p = server.port!;
  await server.stop(true);
  return p;
}
async function command(
  scope: OwnedProcesses,
  argv: string[],
  environment: Record<string, string>,
  cwd = root,
) {
  const child = scope.spawn(argv, { cwd, env: environment });
  const result = await scope.wait(child.exited);
  if (result !== 0) throw new Error(`${argv[0]} failed with status ${result}`);
}
async function ready(scope: OwnedProcesses, url: string, status = 200) {
  const deadline = Date.now() + 90000;
  while (Date.now() < deadline) {
    try {
      if (
        (await fetch(url, { signal: AbortSignal.any([scope.signal, AbortSignal.timeout(1000)]) }))
          .status === status
      )
        return;
    } catch {
      scope.signal.throwIfAborted();
    }
    await scope.wait(Bun.sleep(200));
  }
  throw new Error(`Server did not become ready: ${url}`);
}

await withOwnedProcesses(async (scope) => {
  const udid = await resolveOwnedSimulator(
    createRealOwnedSimulatorDeps(root),
    process.env.IOS_SIMULATOR_UDID,
  );
  const apiPort = await port();
  const origin = `http://127.0.0.1:${apiPort}`;
  const backendEnv = env({
    PORT: String(apiPort),
    JWT_SECRET: "ab".repeat(32),
    NODE_ENV: "development",
    EMAIL_TRANSPORT: "mock",
    RATE_LIMIT_BYPASS: "1",
  });
  scope.spawn(["bun", "apps/server/src/index.ts"], { cwd: root, env: backendEnv });
  await ready(scope, `${origin}/api/inventory`, 401);
  const email = `native-http-${crypto.randomUUID()}@example.com`;
  const [account] = await sql<
    { id: string }[]
  >`INSERT INTO accounts(email) VALUES(${email}) RETURNING id`;
  await sql`INSERT INTO auth_codes(account_id,code,expires_at) VALUES(${account.id},'123456',now()+interval '10 minutes')`;
  const verified = await fetch(`${origin}/api/auth/verify-code`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, code: "123456" }),
  });
  if (!verified.ok) throw new Error(`Real auth failed: ${verified.status}`);
  const auth = (await verified.json()) as { token: string; account_id: string; player_id: string };
  await sql`INSERT INTO player_inventory(player_id,item_id,data) VALUES(${auth.player_id},'oak_wood',${{ quantity: 2, equipped: false }})`;
  let quantity = 2;
  let gets = 0;
  let hold = false;
  const observed: number[] = [];
  let held: { snapshot: unknown; release: (response: Response) => void } | undefined;
  async function snapshot() {
    const res = await fetch(`${origin}/api/inventory`, {
      headers: { Authorization: `Bearer ${auth.token}` },
    });
    if (!res.ok) throw new Error(`Snapshot failed: ${res.status}`);
    return (await res.json()) as unknown;
  }
  async function advance() {
    quantity++;
    await sql`UPDATE player_inventory SET data=${{ quantity, equipped: false }} WHERE player_id=${auth.player_id} AND item_id='oak_wood'`;
  }
  const proxy = Bun.serve({
    hostname: "127.0.0.1",
    port: 0,
    async fetch(req) {
      const path = new URL(req.url).pathname;
      if (path === "/observe") {
        observed.push(((await req.json()) as { quantity: number }).quantity);
        return new Response("observed");
      }
      if (path === "/fixture") return Response.json(auth);
      if (path === "/hold") {
        hold = true;
        return new Response("held");
      }
      if (path === "/advance") {
        const deadline = Date.now() + 5000;
        while (!held && Date.now() < deadline) await Bun.sleep(50);
        if (!held) return new Response("No pending snapshot to invalidate", { status: 409 });
        await advance();
        return Response.json(await snapshot());
      }
      if (path === "/release") {
        if (!held) return new Response("No held GET", { status: 409 });
        held.release(Response.json(held.snapshot));
        held = undefined;
        return new Response("released");
      }
      if (path === "/api/inventory") {
        gets++;
        if (hold) {
          hold = false;
          const data = await snapshot();
          return await new Promise<Response>((release) => {
            held = { snapshot: data, release };
          });
        }
      }
      return fetch(`${origin}${path}`, {
        method: req.method,
        headers: req.headers,
        body: req.method === "GET" ? undefined : await req.text(),
      });
    },
  });
  try {
    const proxyOrigin = `http://127.0.0.1:${proxy.port}`;
    const nativeEnv = env({ EXPO_PUBLIC_API_URL: proxyOrigin, IOS_SIMULATOR_UDID: udid, CI: "1" });
    console.log(
      "Native HTTP acceptance: building current source and running mandatory auth preflight",
    );
    await command(scope, ["bun", "run", "--cwd", "apps/mobile", "verify:native-build"], nativeEnv);
    const metroPort = await port();
    scope.spawn(["bun", "expo", "start", "--dev-client", "--port", String(metroPort)], {
      cwd: `${root}/apps/mobile`,
      env: nativeEnv,
    });
    await ready(scope, `http://127.0.0.1:${metroPort}/status`);
    const route = `divineruin://http-inventory-test?fixture=${encodeURIComponent(proxyOrigin)}`;
    const maestro = (file: string) =>
      command(
        scope,
        [
          "maestro",
          `--device=${udid}`,
          "test",
          "--test-output-dir=test-results/http-inventory-native",
          "-e",
          `APP_LAUNCH_URL=${developmentClientUrl(metroPort)}`,
          "-e",
          `ROUTE_URL=${route}`,
          `${root}/apps/mobile/.maestro/${file}`,
        ],
        nativeEnv,
      );
    await maestro("http-inventory-refresh.yaml");
    await scope.wait(Bun.sleep(1000));
    const before = gets;
    await scope.wait(Bun.sleep(7000));
    if (gets !== before) throw new Error("Background HUD continued authenticated polling");
    if (before < 1) throw new Error("Native HUD never requested a snapshot");
    await advance();
    console.log(
      "Native HTTP acceptance: background pause passed; checking resume and stale GET refusal",
    );
    await maestro("http-inventory-resume.yaml");
    await scope.wait(Bun.sleep(6000));
    if (held || gets < before + 2)
      throw new Error("Native stale GET was not exercised and refreshed");
    const immediate = observed.indexOf(4);
    if (immediate < 0 || observed.slice(immediate).some((q) => q !== 4))
      throw new Error("Native stale GET replaced immediate inventory");
    console.log("Native HTTP acceptance passed: open, pause, resume and stale response");
  } finally {
    held?.release(new Response("terminated", { status: 503 }));
    await proxy.stop(true);
    await sql.close();
  }
});
