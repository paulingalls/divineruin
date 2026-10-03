import { authorizeIronResolveBackend } from "./iron-resolve-backend-ownership";
import { createRealOwnedSimulatorDeps, resolveOwnedSimulator } from "./owned-simulator";
import { withOwnedProcesses } from "./native-transport-processes";

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
  const udid = await resolveOwnedSimulator(
    createRealOwnedSimulatorDeps(root),
    process.env.IOS_SIMULATOR_UDID,
  );
  const apiPort = await reservePort();
  const env = {
    ...process.env,
    IOS_SIMULATOR_UDID: udid,
    EXPO_PUBLIC_API_URL: `http://127.0.0.1:${apiPort}`,
    RESEND_API_KEY: "",
    NODE_ENV: "development",
    CI: "1",
  };
  const backend = scope.spawn(["bun", "--env-file=.env", "apps/server/src/index.ts"], {
    cwd: root,
    env: { ...env, PORT: String(apiPort) },
  });
  await ready(`${env.EXPO_PUBLIC_API_URL}/api/inventory`, 401);
  async function command(argv: string[]) {
    const child = scope.spawn(argv, { cwd: root, env });
    const exit = await scope.wait(child.exited);
    if (exit !== 0) throw new Error(`${argv[0]} exited ${String(exit)}`);
  }
  await command(["bun", "run", "--cwd", "apps/mobile", "verify:native-build"]);
  const port = await reservePort();
  const metro = scope.spawn(["bun", "expo", "start", "--dev-client", "--port", String(port)], {
    cwd: `${root}/apps/mobile`,
    env,
  });
  await ready(`http://127.0.0.1:${port}/status`, 200);
  await command([
    "maestro",
    `--device=${udid}`,
    "test",
    "--test-output-dir=test-results/iron-resolve-native",
    "-e",
    `APP_LAUNCH_URL=exp+divineruin://expo-development-client/?url=${encodeURIComponent(`http://127.0.0.1:${port}`)}`,
    `${root}/apps/mobile/.maestro/iron-resolve-hud.yaml`,
  ]);
  await scope.stop(metro);
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
