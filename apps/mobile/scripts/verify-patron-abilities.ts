import { SQL } from "bun";
import { mkdir } from "node:fs/promises";
import { withOwnedProcesses, type OwnedProcesses } from "./native-transport-processes";

async function ready(
  scope: OwnedProcesses,
  url: string,
  child?: { exitCode: number | null },
  log?: string,
  expectedStatus?: number,
) {
  const deadline = Date.now() + 90_000;
  while (Date.now() < deadline) {
    if (child && child.exitCode !== null)
      throw new Error(`Patron prerequisite exited ${child.exitCode}; see ${log}`);
    try {
      const response = await fetch(url, {
        signal: AbortSignal.any([scope.signal, AbortSignal.timeout(1000)]),
      });
      if (expectedStatus === undefined ? response.ok : response.status === expectedStatus) return;
    } catch {
      scope.signal.throwIfAborted();
    }
    await scope.wait(Bun.sleep(200));
  }
  throw new Error(`Patron prerequisite did not become ready: ${url}; see ${log}`);
}

export async function withNativeOwnedBackend<T>(
  scope: OwnedProcesses,
  root: string,
  environment: Record<string, string>,
  results: string,
  run: (environment: Record<string, string> & { EXPO_PUBLIC_API_URL: string }) => Promise<T>,
): Promise<T> {
  if (!environment.DATABASE_URL || !environment.DATABASE_URL.trim())
    throw new Error("Owned backend requires DATABASE_URL");
  const sql = new SQL(environment.DATABASE_URL);
  const email = "acceptance@divineruin.test";
  let enrolled = false;
  let child: ReturnType<OwnedProcesses["spawn"]> | undefined;
  let logs: Promise<unknown> | undefined;
  let outcome: { value: T } | { error: unknown };
  try {
    const reserve = Bun.serve({ hostname: "127.0.0.1", port: 0, fetch: () => new Response() });
    const port = reserve.port!;
    await reserve.stop(true);
    const origin = `http://127.0.0.1:${port}`;
    const log = `${results}/backend.log`;
    const errorLog = `${results}/backend-error.log`;
    child = scope.spawn(["bun", "--no-env-file", "apps/server/src/index.ts"], {
      cwd: root,
      env: {
        ...environment,
        SERVER_HOST: "127.0.0.1",
        PORT: String(port),
        EMAIL_TRANSPORT: "mock",
        RATE_LIMIT_BYPASS: "1",
        JWT_SECRET: "ab".repeat(32),
        NODE_ENV: "development",
      },
      capture: true,
    });
    logs = Promise.allSettled([
      Bun.write(log, child.stdout!),
      Bun.write(errorLog, child.stderr!),
    ]).then((writes) => {
      const errors = writes.flatMap((write) =>
        write.status === "rejected" ? [write.reason as unknown] : [],
      );
      if (errors.length) throw new AggregateError(errors, "Backend log capture failed");
    });
    void logs.catch(() => {});
    console.log(`Owned native backend: ${origin} pid=${child.pid}; logs: ${log}, ${errorLog}`);
    const inserted = await sql<{ email: string }[]>`
      INSERT INTO signin_allowlist(email) VALUES(${email})
      ON CONFLICT (email) DO NOTHING RETURNING email`;
    enrolled = inserted.length === 1;
    scope.signal.throwIfAborted();
    await ready(scope, `${origin}/api/inventory`, child, errorLog, 401);
    outcome = { value: await run({ ...environment, EXPO_PUBLIC_API_URL: origin }) };
  } catch (error) {
    outcome = { error };
  }
  const errors: unknown[] = [];
  for (const cleanup of [
    () => scope.stop(child),
    () => logs,
    async () => {
      if (enrolled) await sql`DELETE FROM signin_allowlist WHERE email=${email}`;
    },
    () => sql.close(),
  ]) {
    try {
      await cleanup();
    } catch (error) {
      errors.push(error);
    }
  }
  if ("error" in outcome) errors.unshift(outcome.error);
  if (errors.length) throw new AggregateError(errors, "Owned native backend failed");
  return (outcome as { value: T }).value;
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
    const results = `${root}/test-results/patron-${crypto.randomUUID()}`;
    await mkdir(results, { recursive: true });
    const installed = scope.spawn(
      ["xcrun", "simctl", "get_app_container", udid, "com.divineruin.app", "app"],
      { cwd: root, capture: true },
    );
    if ((await scope.wait(installed.exited)) !== 0)
      throw new Error(`Missing com.divineruin.app on owned simulator ${udid}`);
    const run = async (environment: Record<string, string>) => {
      let launch = env.MAESTRO_APP_LAUNCH_URL;
      if (!launch) {
        const reservation = Bun.serve({
          hostname: "127.0.0.1",
          port: 0,
          fetch: () => new Response(),
        });
        const metroPort = reservation.port!;
        await reservation.stop(true);
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
      return withPatronProbe(
        scope,
        root,
        environment,
        results,
        async (route) => {
          const simple = await runSimple(launch, scope);
          if (simple !== 0) return simple;
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
          return scope.wait(maestro.exited);
        },
        true,
      );
    };
    return environment.REQUIRE_BACKEND === "1" && !environment.MAESTRO_APP_LAUNCH_URL
      ? withNativeOwnedBackend(scope, root, environment, results, run)
      : run(environment);
  });
}

export async function withPatronProbe<T>(
  scope: OwnedProcesses,
  root: string,
  environment: Record<string, string>,
  results: string,
  run: (route: string) => Promise<T>,
  loadEnvFile = false,
): Promise<T> {
  await mkdir(results, { recursive: true });
  const runId = crypto.randomUUID();
  const reserve = Bun.serve({ hostname: "127.0.0.1", port: 0, fetch: () => new Response() });
  const probePort = reserve.port!;
  await reserve.stop(true);
  const probeLog = `${results}/probe.log`;
  const child = scope.spawn(
    [
      "bun",
      ...(loadEnvFile ? [`--env-file=${root}/.env`] : ["--no-env-file"]),
      "run",
      "--cwd",
      "apps/agent",
      "uv",
      "run",
      "--frozen",
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
  void logs.catch(() => {});
  try {
    const endpoint = `http://127.0.0.1:${probePort}`;
    await ready(scope, `${endpoint}?run_id=${runId}`, child, `${results}/probe-error.log`);
    return await run(
      `divineruin://patron-abilities-test?endpoint=${encodeURIComponent(endpoint)}&run_id=${runId}`,
    );
  } finally {
    await scope.stop(child);
    await logs;
  }
}
