import { resolve } from "node:path";
import { OwnedProcesses, withOwnedProcesses } from "./native-transport-processes";
import { createRealOwnedSimulatorDeps, resolveOwnedSimulator } from "./owned-simulator";
import { developmentClientUrl } from "./verify-native-transport";

const root = resolve(import.meta.dir, "../../..");
export const phases = [
  "gather_primary",
  "craft_primary_partial",
  "experiment_primary_complete",
  "craft_guest_partial",
  "experiment_guest_empty",
  "combat_distributed",
  "quest_party",
] as const;
type Child = ReturnType<OwnedProcesses["spawn"]>;
type Environment = Record<string, string | undefined>;
export interface LiveMaterialDeps {
  acceptance(scope: OwnedProcesses, path: string, runId: string): Promise<void>;
  readFixture(path: string): Promise<unknown>;
  resolveSimulator(): Promise<string>;
  reservePort(): Promise<number>;
  start(scope: OwnedProcesses, kind: "backend" | "metro", port: number, env: Environment): Child;
  ready(scope: OwnedProcesses, kind: "backend" | "metro", port: number): Promise<void>;
  stop(scope: OwnedProcesses, child: Child): Promise<void>;
  serve(fixture: unknown): { port: number; stop(): Promise<void> };
  command(
    scope: OwnedProcesses,
    argv: string[],
    env: Environment,
  ): Promise<{ exitCode: number | null; signal?: string }>;
}

export function validateFixture(value: unknown, runId: string): void {
  const fixture = value as
    | {
        runId?: string;
        owners?: string[];
        initial?: Record<string, unknown[]>;
        sender?: { isAgent?: boolean; identity?: string; kind?: number };
        steps?: {
          phase?: string;
          received?: unknown[];
          received_bytes?: number[][];
          expected?: Record<string, unknown[]>;
        }[];
      }
    | null
    | undefined;
  if (fixture?.runId !== runId) throw new Error("Capture does not belong to this invocation");
  const fail = () => {
    throw new Error("Capture has no usable committed inventory sequence");
  };
  if (
    fixture.owners?.length !== 2 ||
    new Set(fixture.owners).size !== 2 ||
    !fixture.sender?.isAgent ||
    !fixture.sender.identity ||
    fixture.sender.kind !== 4 ||
    fixture.steps?.length !== phases.length
  )
    fail();
  const owners = fixture.owners!;
  if (!owners.every((owner) => Array.isArray(fixture.initial?.[owner]))) fail();
  for (const [index, step] of fixture.steps!.entries()) {
    if (
      step.phase !== phases[index] ||
      !step.received_bytes?.length ||
      step.received?.length !== step.received_bytes.length ||
      !owners.every((owner) => Array.isArray(step.expected?.[owner]))
    )
      fail();
    for (const [offset, bytes] of step.received_bytes!.entries()) {
      if (
        !bytes.length ||
        !bytes.every((byte) => Number.isInteger(byte) && byte >= 0 && byte <= 255)
      )
        fail();
      try {
        const event = JSON.parse(
          new TextDecoder("utf-8", { fatal: true }).decode(new Uint8Array(bytes)),
        ) as { type?: unknown } | null;
        if (
          !event ||
          typeof event.type !== "string" ||
          event.type === "session_init" ||
          JSON.stringify(event) !== JSON.stringify(step.received![offset])
        )
          fail();
      } catch {
        fail();
      }
    }
  }
}

export async function runLiveMaterialInventory(
  scope: OwnedProcesses,
  deps: LiveMaterialDeps,
): Promise<void> {
  const runId = crypto.randomUUID();
  const path = `${root}/test-results/live-material-${runId}.json`;
  await deps.acceptance(scope, path, runId);
  const fixture = await deps.readFixture(path);
  validateFixture(fixture, runId);
  const udid = await deps.resolveSimulator();
  const backendPort = await deps.reservePort();
  const env = {
    ...process.env,
    EXPO_PUBLIC_API_URL: `http://127.0.0.1:${backendPort}`,
    IOS_SIMULATOR_UDID: udid,
  };
  let backend: Child | undefined;
  let metro: Child | undefined;
  let server: ReturnType<LiveMaterialDeps["serve"]> | undefined;
  let failure: Error | undefined;
  try {
    backend = deps.start(scope, "backend", backendPort, env);
    await scope.wait(deps.ready(scope, "backend", backendPort));
    await requireCommand(
      scope,
      deps,
      ["bun", "run", "--cwd", "apps/mobile", "verify:native-build"],
      env,
    );
    server = deps.serve(fixture);
    const metroPort = await deps.reservePort();
    metro = deps.start(scope, "metro", metroPort, env);
    await scope.wait(deps.ready(scope, "metro", metroPort));
    const route = `divineruin://live-material-inventory-test?fixture=${encodeURIComponent(`http://127.0.0.1:${server.port}`)}&run_id=${runId}`;
    await requireCommand(
      scope,
      deps,
      [
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
      ],
      env,
    );
  } catch (error) {
    failure = error instanceof Error ? error : new Error(String(error));
  }
  const failures: unknown[] = [];
  for (const dispose of [
    () => metro && deps.stop(scope, metro),
    () => server?.stop(),
    () => backend && deps.stop(scope, backend),
  ]) {
    try {
      await dispose();
    } catch (error) {
      failures.push(error);
    }
  }
  if (failures.length)
    throw new AggregateError(
      failure ? [failure, ...failures] : failures,
      "Inventory verification cleanup failed",
    );
  if (failure) throw failure;
  scope.signal.throwIfAborted();
}

async function requireCommand(
  scope: OwnedProcesses,
  deps: LiveMaterialDeps,
  argv: string[],
  env: Environment,
) {
  const result = await scope.wait(deps.command(scope, argv, env));
  if (result.exitCode !== 0 || result.signal)
    throw new Error(
      `${argv.join(" ")} failed with status ${result.exitCode}${result.signal ? ` (${result.signal})` : ""}`,
    );
}

function definedEnv(env: Environment): Record<string, string> {
  return Object.fromEntries(
    Object.entries(env).filter((entry): entry is [string, string] => entry[1] !== undefined),
  );
}

export function realLiveMaterialDeps(): LiveMaterialDeps {
  const command: LiveMaterialDeps["command"] = async (scope, argv, env) => {
    const child = scope.spawn(argv, { cwd: root, env: definedEnv(env) });
    return {
      exitCode: await scope.wait(child.exited),
      signal: child.signalCode === null ? undefined : String(child.signalCode),
    };
  };
  return {
    command,
    acceptance: async (scope, path, runId) => {
      const env = {
        ...process.env,
        TESTCONTAINERS_RYUK_DISABLED: "true",
        REQUIRE_DOCKER: "1",
        LIVE_MATERIAL_INVENTORY_OUTPUT: path,
        LIVE_MATERIAL_INVENTORY_RUN_ID: runId,
      };
      await requireCommand(
        scope,
        { command } as LiveMaterialDeps,
        [
          "uv",
          "run",
          "--env-file",
          ".env",
          "--project",
          "apps/agent",
          "pytest",
          "apps/agent/tests/acceptance/test_live_material_inventory.py",
          "-q",
        ],
        env,
      );
    },
    readFixture: (path) => Bun.file(path).json(),
    resolveSimulator: () =>
      resolveOwnedSimulator(createRealOwnedSimulatorDeps(root), process.env.IOS_SIMULATOR_UDID),
    reservePort: async () => {
      const server = Bun.serve({ hostname: "127.0.0.1", port: 0, fetch: () => new Response() });
      const port = server.port!;
      await server.stop(true);
      return port;
    },
    start: (scope, kind, port, env) =>
      scope.spawn(
        kind === "backend"
          ? ["bun", "--env-file=.env", "apps/server/src/index.ts"]
          : ["bun", "expo", "start", "--dev-client", "--port", String(port)],
        {
          cwd: kind === "backend" ? root : `${root}/apps/mobile`,
          env: definedEnv({
            ...env,
            PORT: String(port),
            RESEND_API_KEY: "",
            NODE_ENV: "development",
            CI: "1",
          }),
        },
      ),
    ready: async (scope, kind, port) => {
      const deadline = Date.now() + (kind === "backend" ? 15000 : 90000);
      while (Date.now() < deadline) {
        scope.signal.throwIfAborted();
        try {
          const response = await scope.wait(
            fetch(`http://127.0.0.1:${port}${kind === "metro" ? "/status" : ""}`, {
              signal: AbortSignal.any([scope.signal, AbortSignal.timeout(1000)]),
            }),
          );
          if (kind === "backend" || (await response.text()).includes("packager-status:running"))
            return;
        } catch {
          scope.signal.throwIfAborted();
        }
        await scope.wait(Bun.sleep(100));
      }
      throw new Error(`Owned ${kind} did not become ready`);
    },
    stop: (scope, child) => scope.stop(child),
    serve: (fixture) => {
      const server = Bun.serve({
        hostname: "127.0.0.1",
        port: 0,
        fetch: () => Response.json(fixture),
      });
      return { port: server.port!, stop: () => server.stop(true) };
    },
  };
}

if (import.meta.main)
  await withOwnedProcesses((scope) => runLiveMaterialInventory(scope, realLiveMaterialDeps()));
