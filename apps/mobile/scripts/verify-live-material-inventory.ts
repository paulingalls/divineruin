import { resolve } from "node:path";
import { OwnedProcesses, withOwnedProcesses } from "./native-transport-processes";
import { createRealOwnedSimulatorDeps, resolveOwnedSimulator } from "./owned-simulator";
import { developmentClientUrl } from "./verify-native-transport";

const root = resolve(import.meta.dir, "../../..");

async function run(scope: OwnedProcesses, argv: string[], cwd = root): Promise<void> {
  const child = scope.spawn(argv, {
    cwd,
    env: Object.fromEntries(
      Object.entries(process.env).filter(
        (entry): entry is [string, string] => entry[1] !== undefined,
      ),
    ),
  });
  const exit = await scope.wait(child.exited);
  if (exit !== 0) throw new Error(`${argv.join(" ")} failed with status ${exit}`);
}

await withOwnedProcesses(async (scope) => {
  const fixture = (await Bun.file(`${root}/test-results/live-material-inventory.json`).json()) as {
    owners?: string[];
    steps?: unknown[];
    sender?: { isAgent: boolean };
  };
  if (fixture.owners?.length !== 2 || fixture.steps?.length !== 6 || !fixture.sender?.isAgent) {
    throw new Error("Run the real PostgreSQL/LiveKit material acceptance first");
  }
  const udid = await resolveOwnedSimulator(
    createRealOwnedSimulatorDeps(root),
    process.env.IOS_SIMULATOR_UDID,
  );
  const reservation = Bun.serve({ hostname: "127.0.0.1", port: 0, fetch: () => new Response() });
  const backendPort = reservation.port!;
  await reservation.stop(true);
  const backend = scope.spawn(["bun", "--env-file=.env", "apps/server/src/index.ts"], {
    cwd: root,
    env: { ...process.env, PORT: String(backendPort), RESEND_API_KEY: "", NODE_ENV: "development" },
  });
  const previousApiUrl = process.env.EXPO_PUBLIC_API_URL;
  process.env.EXPO_PUBLIC_API_URL = `http://127.0.0.1:${backendPort}`;
  const deadline = Date.now() + 15000;
  let backendReady = false;
  while (!backendReady && Date.now() < deadline) {
    backendReady = await fetch(process.env.EXPO_PUBLIC_API_URL)
      .then(() => true)
      .catch(() => false);
    if (!backendReady) await Bun.sleep(100);
  }
  if (!backendReady) throw new Error("Owned backend did not start");
  const previousUdid = process.env.IOS_SIMULATOR_UDID;
  process.env.IOS_SIMULATOR_UDID = udid;
  try {
    await run(scope, ["bun", "run", "--cwd", "apps/mobile", "verify:native-build"]);
    const runId = crypto.randomUUID();
    const fixtureServer = Bun.serve({
      hostname: "127.0.0.1",
      port: 0,
      fetch: () => Response.json({ ...fixture, runId }),
    });
    const metroReservation = Bun.serve({
      hostname: "127.0.0.1",
      port: 0,
      fetch: () => new Response(),
    });
    const metroPort = metroReservation.port!;
    await metroReservation.stop(true);
    const metro = scope.spawn(
      ["bun", "expo", "start", "--dev-client", "--port", String(metroPort)],
      { cwd: `${root}/apps/mobile`, env: { ...process.env, CI: "1" } },
    );
    try {
      const deadline = Date.now() + 120000;
      let ready = false;
      while (!ready && Date.now() < deadline) {
        scope.signal.throwIfAborted();
        ready = await fetch(`http://127.0.0.1:${metroPort}/status`)
          .then(async (r) => (await r.text()).includes("packager-status:running"))
          .catch(() => false);
        if (!ready) await Bun.sleep(500);
      }
      if (!ready) throw new Error("Metro did not become ready");
      const endpoint = `http://127.0.0.1:${fixtureServer.port}`;
      const route = `divineruin://live-material-inventory-test?fixture=${encodeURIComponent(endpoint)}&run_id=${runId}`;
      await run(scope, [
        "maestro",
        `--device=${udid}`,
        "test",
        "--test-output-dir=test-results/live-material-panel",
        "-e",
        `APP_LAUNCH_URL=${developmentClientUrl(metroPort)}`,
        "-e",
        `ROUTE_URL=${route}`,
        "-e",
        `RUN_ID_TEXT=Run: ${runId}`,
        `${root}/apps/mobile/.maestro/live-material-inventory.yaml`,
      ]);
    } finally {
      await fixtureServer.stop(true);
      await scope.stop(metro);
    }
  } finally {
    await scope.stop(backend);
    if (previousApiUrl === undefined) delete process.env.EXPO_PUBLIC_API_URL;
    else process.env.EXPO_PUBLIC_API_URL = previousApiUrl;
    if (previousUdid === undefined) delete process.env.IOS_SIMULATOR_UDID;
    else process.env.IOS_SIMULATOR_UDID = previousUdid;
  }
});
