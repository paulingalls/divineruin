import { authorizeIronResolveBackend } from "./iron-resolve-backend-ownership";
import { withCharacterFixture } from "./iron-resolve-fixture";
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
  await withCharacterFixture(env.EXPO_PUBLIC_API_URL, process.env.DATABASE_URL, async (route) => {
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
