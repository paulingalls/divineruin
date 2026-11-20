import { SQL } from "bun";
import { authorizeIronResolveBackend } from "./iron-resolve-backend-ownership";
import { withOwnedProcesses } from "./native-transport-processes";
import { runNativeBuild } from "./verify-native-build";
import { createNativeBuildDeps } from "./verify-native-build-runtime";

const root = new URL("../../..", import.meta.url).pathname.replace(/\/$/, "");

async function reservePort(): Promise<number> {
  const listener = Bun.serve({ hostname: "127.0.0.1", port: 0, fetch: () => new Response("") });
  const port = listener.port;
  await listener.stop(true);
  if (!port) throw new Error("No port available");
  return port;
}

async function withCharacterFixture(
  api: string,
  run: (route: string) => Promise<void>,
): Promise<void> {
  const databaseUrl = process.env.DATABASE_URL;
  if (!databaseUrl) throw new Error("Native temp HP fixture requires DATABASE_URL");
  const sql = new SQL(databaseUrl);
  const email = `native-temp-hp-${crypto.randomUUID()}@example.com`;
  try {
    await sql`INSERT INTO signin_allowlist(email) VALUES(${email})`;
    const accounts = await sql<
      { id: string }[]
    >`INSERT INTO accounts(email) VALUES(${email}) RETURNING id`;
    const account = accounts.at(0);
    if (!account) throw new Error("Native temp HP fixture account was not created");
    await sql`INSERT INTO auth_codes(account_id,code,expires_at) VALUES(${account.id},'123456',now()+interval '10 minutes')`;
    const response = await fetch(`${api}/api/auth/verify-code`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, code: "123456" }),
    });
    if (!response.ok) throw new Error(`Native fixture auth failed: ${response.status}`);
    const auth = (await response.json()) as {
      token: string;
      account_id: string;
      player_id: string;
    };
    await sql`UPDATE players SET data=${{
      name: "Kael",
      class: "warrior",
      hp: { current: 12, max: 20 },
      temp_hp: 7,
    }} WHERE account_id=${account.id} AND player_id=${auth.player_id}`;
    const fixture = Bun.serve({
      hostname: "127.0.0.1",
      port: 0,
      fetch: (req) =>
        new URL(req.url).pathname === "/fixture" && req.method === "GET"
          ? Response.json(auth)
          : new Response(null, { status: 404 }),
    });
    try {
      const origin = `http://127.0.0.1:${fixture.port}`;
      await run(`divineruin://iron-resolve-test?fixture=${encodeURIComponent(origin)}`);
    } finally {
      await fixture.stop(true);
    }
  } finally {
    try {
      await sql.begin(async (transaction) => {
        await transaction`DELETE FROM players WHERE account_id IN (SELECT id FROM accounts WHERE email=${email})`;
        await transaction`DELETE FROM auth_codes WHERE account_id IN (SELECT id FROM accounts WHERE email=${email})`;
        await transaction`DELETE FROM accounts WHERE email=${email}`;
        await transaction`DELETE FROM signin_allowlist WHERE email=${email}`;
      });
    } finally {
      await sql.close();
    }
  }
}

await authorizeIronResolveBackend(root);

await withOwnedProcesses(async (scope) => {
  const apiPort = await reservePort();
  const env = {
    ...process.env,
    EXPO_PUBLIC_API_URL: `http://127.0.0.1:${apiPort}`,
    RESEND_API_KEY: "",
    NODE_ENV: "development",
    CI: "1",
  };
  const jwtSecret = (crypto.randomUUID() + crypto.randomUUID()).replaceAll("-", "");
  const backend = scope.spawn(["bun", "--env-file=.env", "apps/server/src/index.ts"], {
    cwd: root,
    env: { ...env, PORT: String(apiPort), JWT_SECRET: jwtSecret },
  });
  await ready(`${env.EXPO_PUBLIC_API_URL}/api/inventory`, 401);
  await withCharacterFixture(env.EXPO_PUBLIC_API_URL, async (route) => {
    await runNativeBuild({
      repoRoot: root,
      processEnv: env,
      deps: {
        ...createNativeBuildDeps(root),
        async runCommand(argv, cwd, env) {
          const commandEnv = Object.fromEntries(
            Object.entries(env).filter(
              (entry): entry is [string, string] => entry[1] !== undefined,
            ),
          );
          const child = scope.spawn(argv, { cwd, env: commandEnv });
          const exitCode = await scope.wait(child.exited);
          return {
            exitCode,
            signal: child.signalCode === null ? undefined : String(child.signalCode),
          };
        },
      },
      prepared: async (nativeEnv) => {
        const maestro = scope.spawn(
          [
            "maestro",
            `--device=${nativeEnv.IOS_SIMULATOR_UDID}`,
            "test",
            "--test-output-dir=test-results/iron-resolve-native",
            "-e",
            `APP_LAUNCH_URL=${nativeEnv.MAESTRO_APP_LAUNCH_URL}`,
            "-e",
            `ROUTE_URL=${route}`,
            `${root}/apps/mobile/.maestro/iron-resolve-hud.yaml`,
          ],
          { cwd: root, env },
        );
        const exit = await scope.wait(maestro.exited);
        if (exit !== 0) throw new Error(`Maestro exited ${String(exit)}`);
      },
    });
  });
  await scope.stop(backend);

  async function ready(url: string, status: number) {
    const deadline = Date.now() + 90000;
    let ready = false;
    while (Date.now() < deadline) {
      scope.signal.throwIfAborted();
      try {
        const response = await fetch(url, {
          signal: AbortSignal.any([scope.signal, AbortSignal.timeout(1000)]),
        });
        if (response.status === status) {
          ready = true;
          break;
        }
      } catch {
        scope.signal.throwIfAborted();
      }
      await scope.wait(Bun.sleep(200));
    }
    if (!ready) throw new Error(`Server did not become ready: ${url}`);
  }
});
