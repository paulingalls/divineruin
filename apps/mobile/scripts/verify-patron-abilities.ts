import { withOwnedProcesses, type OwnedProcesses } from "./native-transport-processes";

async function ready(
  scope: OwnedProcesses,
  url: string,
  child?: { exitCode: number | null },
  log?: string,
) {
  const deadline = Date.now() + 90_000;
  while (Date.now() < deadline) {
    if (child && child.exitCode !== null)
      throw new Error(`Patron prerequisite exited ${child.exitCode}; see ${log}`);
    try {
      if (
        (await fetch(url, { signal: AbortSignal.any([scope.signal, AbortSignal.timeout(1000)]) }))
          .ok
      )
        return;
    } catch {
      scope.signal.throwIfAborted();
    }
    await scope.wait(Bun.sleep(200));
  }
  throw new Error(`Patron prerequisite did not become ready: ${url}`);
}

export async function runPatronAbilitiesFlow(
  root: string,
  udid: string,
  env: Record<string, string | undefined>,
  runSimple: (launch: string, scope: OwnedProcesses) => Promise<number>,
): Promise<number> {
  return withOwnedProcesses(async (scope) => {
    const environment = Object.fromEntries(
      Object.entries(env).filter((v): v is [string, string] => v[1] !== undefined),
    );
    const runId = crypto.randomUUID();
    const results = `${root}/test-results/patron-${runId}`;
    await Bun.$`mkdir -p ${results}`;
    const installed = scope.spawn(
      ["xcrun", "simctl", "get_app_container", udid, "com.divineruin.app", "app"],
      { cwd: root, capture: true },
    );
    if ((await scope.wait(installed.exited)) !== 0)
      throw new Error(`Missing com.divineruin.app on owned simulator ${udid}`);
    const reserve = Bun.serve({ hostname: "127.0.0.1", port: 0, fetch: () => new Response() });
    const probePort = reserve.port!;
    await reserve.stop(true);
    const probeLog = `${results}/probe.log`;
    const child = scope.spawn(
      [
        "bun",
        `--env-file=${root}/.env`,
        "run",
        "--cwd",
        "apps/agent",
        "uv",
        "run",
        "python",
        "patron_abilities_native_probe.py",
        "--run-id",
        runId,
        "--port",
        String(probePort),
        "--ready",
        `${results}/ready.json`,
        "--evidence",
        `${results}/control.json`,
      ],
      { cwd: root, env: environment, capture: true },
    );
    const logs = Promise.all([
      Bun.write(probeLog, child.stdout!),
      Bun.write(`${results}/probe-error.log`, child.stderr!),
    ]);
    let launch = env.MAESTRO_APP_LAUNCH_URL;
    if (!launch) {
      const metroPort = probePort + 1;
      const metro = scope.spawn(
        ["bunx", "expo", "start", "--dev-client", "--port", String(metroPort)],
        { cwd: `${root}/apps/mobile`, env: { ...environment, CI: "1" }, capture: true },
      );
      void Bun.write(`${results}/metro.log`, metro.stdout!);
      void Bun.write(`${results}/metro-error.log`, metro.stderr!);
      await ready(
        scope,
        `http://127.0.0.1:${metroPort}/status`,
        metro,
        `${results}/metro-error.log`,
      );
      launch = `exp+divineruin://expo-development-client/?url=${encodeURIComponent(`http://127.0.0.1:${metroPort}`)}`;
    }
    const endpoint = `http://127.0.0.1:${probePort}`;
    await ready(scope, `${endpoint}?run_id=${runId}`, child, `${results}/probe-error.log`);
    const simple = await runSimple(launch, scope);
    if (simple !== 0) return simple;
    const route = `divineruin://patron-abilities-test?endpoint=${encodeURIComponent(endpoint)}&run_id=${runId}`;
    const maestro = scope.spawn(
      [
        "maestro",
        `--device=${udid}`,
        "test",
        "--test-output-dir",
        results,
        "-e",
        `PATRON_ROUTE=${route}`,
        `${root}/apps/mobile/.maestro/patron-abilities.yaml`,
      ],
      { cwd: root },
    );
    try {
      return await scope.wait(maestro.exited);
    } finally {
      await scope.stop(child);
      await logs;
    }
  });
}
