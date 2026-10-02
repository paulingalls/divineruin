import { createRealOwnedSimulatorDeps, resolveOwnedSimulator } from "./owned-simulator";
import { withOwnedProcesses } from "./native-transport-processes";

const root = new URL("../../..", import.meta.url).pathname.replace(/\/$/, "");

await withOwnedProcesses(async (scope) => {
  const udid = await resolveOwnedSimulator(
    createRealOwnedSimulatorDeps(root),
    process.env.IOS_SIMULATOR_UDID,
  );
  const env = { ...process.env, IOS_SIMULATOR_UDID: udid };
  async function command(argv: string[]) {
    const child = scope.spawn(argv, { cwd: root, env });
    const exit = await scope.wait(child.exited);
    if (exit !== 0) throw new Error(`${argv[0]} exited ${String(exit)}`);
  }
  await command(["bun", "run", "--cwd", "apps/mobile", "verify:native-build"]);
  const listener = Bun.serve({ hostname: "127.0.0.1", port: 0, fetch: () => new Response("") });
  const port = listener.port;
  await listener.stop(true);
  if (!port) throw new Error("No Metro port available");
  const metro = scope.spawn(["bun", "expo", "start", "--dev-client", "--port", String(port)], {
    cwd: `${root}/apps/mobile`,
    env,
  });
  const deadline = Date.now() + 90000;
  let ready = false;
  while (Date.now() < deadline) {
    scope.signal.throwIfAborted();
    try {
      const response = await fetch(`http://127.0.0.1:${port}/status`, {
        signal: AbortSignal.any([scope.signal, AbortSignal.timeout(1000)]),
      });
      if (response.ok) {
        ready = true;
        break;
      }
    } catch {
      scope.signal.throwIfAborted();
    }
    await scope.wait(Bun.sleep(200));
  }
  if (!ready) throw new Error("Metro did not become ready");
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
});
