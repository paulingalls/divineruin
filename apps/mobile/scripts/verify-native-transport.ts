import { mkdir, readFile, stat, writeFile } from "node:fs/promises";
import { createServer } from "node:net";
import { join, resolve } from "node:path";
import { OwnedProcesses, withOwnedProcesses } from "./native-transport-processes";

import {
  assertTransportResult,
  assertNoCredentials,
  isPositiveCount,
  isZeroCount,
  type TransportResult,
} from "../src/audio/native-transport-observation";

export const OWNED_SIMULATOR_UDID = "DC457949-200B-479A-95FD-611E33210F12";
const BUNDLE_ID = "com.divineruin.app";
const SCENARIOS = ["none", "withhold-audio", "withhold-event"] as const;
type Fault = (typeof SCENARIOS)[number];
type PrepareNativeApp = (
  scope: OwnedProcesses,
  repoRoot: string,
  env: Record<string, string | undefined>,
) => Promise<void>;

interface OwnedProcess {
  exited: Promise<number>;
  kill(signal?: NodeJS.Signals): void;
}

function definedEnv(env: Record<string, string | undefined>): Record<string, string> {
  return Object.fromEntries(
    Object.entries(env).filter((entry): entry is [string, string] => entry[1] !== undefined),
  );
}

function required(env: Record<string, string | undefined>, name: string): string {
  const value = env[name]?.trim();
  if (!value) throw new Error(`${name} is required for native transport verification`);
  return value;
}

export function developmentClientUrl(port: number): string {
  return `exp+divineruin://expo-development-client/?url=${encodeURIComponent(`http://127.0.0.1:${port}`)}`;
}

export function transportRouteUrl(fixtureUrl: string, runId: string): string {
  return `divineruin://native-transport-test?fixture=${encodeURIComponent(fixtureUrl)}&run_id=${encodeURIComponent(runId)}`;
}

export function validateScenarioResult(raw: unknown, runId: string, fault: Fault): TransportResult {
  const result = raw as TransportResult;
  if (result.run_id !== runId) throw new Error("native result has stale run ID");
  if (!result.peer_ready || !result.mobile_identity || !result.publisher_identity) {
    throw new Error("native result is missing peer identities or readiness");
  }
  if (!isPositiveCount(result.microphone_frames)) {
    throw new Error("native result has no microphone frames");
  }
  if (fault === "none") return assertTransportResult(result, runId);
  const expected = fault === "withhold-audio" ? "received-audio" : "session-init-hud";
  if (result.guard_failed !== expected || result.expected_guard !== expected) {
    throw new Error(`native result did not fail the ${expected} guard`);
  }
  if (fault === "withhold-audio") {
    if (
      !isZeroCount(result.packets_received) ||
      !isZeroCount(result.bytes_received) ||
      result.audio_track_sid
    ) {
      throw new Error(
        "withhold-audio unexpectedly received publisher audio or omitted its counters",
      );
    }
    if (
      !result.event_received ||
      result.hud_character !== "Upgrade Test Hero" ||
      result.hud_location !== "Upgrade Test Room"
    ) {
      throw new Error("withhold-audio did not preserve SESSION_INIT and HUD evidence");
    }
  } else {
    if (
      !isPositiveCount(result.packets_received) ||
      !isPositiveCount(result.bytes_received) ||
      !result.audio_track_sid
    ) {
      throw new Error("withhold-event did not preserve received audio evidence");
    }
    if (result.event_received || result.hud_character || result.hud_location) {
      throw new Error("withhold-event unexpectedly observed SESSION_INIT or HUD values");
    }
  }
  return result;
}

async function capture(scope: OwnedProcesses, command: string[], cwd: string): Promise<string> {
  const child = scope.spawn(command, { cwd, capture: true });
  const [stdout, stderr, exit] = await scope.wait(
    Promise.all([
      new Response(child.stdout).text(),
      new Response(child.stderr).text(),
      child.exited,
    ]),
  );
  if (exit !== 0) throw new Error(`${command.join(" ")} failed: ${stderr.trim()}`);
  return stdout;
}

async function requireTargetSimulator(
  scope: OwnedProcesses,
  repoRoot: string,
  udid: string,
): Promise<void> {
  const raw = await capture(scope, ["xcrun", "simctl", "list", "devices", "--json"], repoRoot);
  const payload = JSON.parse(raw) as {
    devices?: Record<string, { udid?: string; state?: string; isAvailable?: boolean }[]>;
  };
  const devices = Object.values(payload.devices ?? {}).flat();
  if (devices.length === 0) throw new Error("simctl returned an empty simulator corpus");
  const target = devices.find((device) => device.udid === udid);
  if (!target) throw new Error(`requested simulator is unknown: ${udid}`);
  if (target.isAvailable === false || target.state !== "Booted") {
    throw new Error(`requested simulator is not booted and available: ${udid}`);
  }
  await capture(scope, ["xcrun", "simctl", "get_app_container", udid, BUNDLE_ID, "app"], repoRoot);
}

async function buildCurrentNativeApp(
  scope: OwnedProcesses,
  repoRoot: string,
  env: Record<string, string | undefined>,
): Promise<void> {
  const child = scope.spawn(["bun", "run", "--cwd", "apps/mobile", "verify:native-build"], {
    cwd: repoRoot,
    env: definedEnv(env),
  });
  const exit = await scope.wait(child.exited);
  if (exit !== 0) throw new Error(`native app build failed with status ${exit}`);
}

async function reservePort(): Promise<number> {
  const server = createServer();
  await new Promise<void>((resolveReady, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolveReady);
  });
  const address = server.address();
  if (!address || typeof address === "string") throw new Error("failed to reserve Metro port");
  await new Promise<void>((resolveClose, reject) =>
    server.close((error) => (error ? reject(error) : resolveClose())),
  );
  return address.port;
}

async function waitForMetro(
  scope: OwnedProcesses,
  process: OwnedProcess,
  port: number,
): Promise<void> {
  let exit: number | undefined;
  void process.exited.then((code) => {
    exit = code;
  });
  const deadline = Date.now() + 120_000;
  while (Date.now() < deadline) {
    scope.signal.throwIfAborted();
    if (exit !== undefined) throw new Error(`Metro exited before readiness with status ${exit}`);
    try {
      const response = await fetch(`http://127.0.0.1:${port}/status`, {
        signal: AbortSignal.any([scope.signal, AbortSignal.timeout(1_000)]),
      });
      if (response.ok && (await response.text()).includes("packager-status:running")) return;
    } catch {
      await Bun.sleep(500);
      continue;
    }
    await Bun.sleep(500);
  }
  throw new Error(`Metro readiness timed out on owned port ${port}`);
}

async function waitForJson(
  scope: OwnedProcesses,
  path: string,
  timeoutMs: number,
): Promise<Record<string, unknown>> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    scope.signal.throwIfAborted();
    try {
      const raw: unknown = JSON.parse(await readFile(path, "utf8")) as unknown;
      if (raw && typeof raw === "object") return raw as Record<string, unknown>;
    } catch {
      await Bun.sleep(100);
      continue;
    }
    await Bun.sleep(100);
  }
  throw new Error(`timed out waiting for nonempty JSON artifact ${path}`);
}

async function runScenario(
  scope: OwnedProcesses,
  repoRoot: string,
  env: Record<string, string | undefined>,
  udid: string,
  fault: Fault,
): Promise<void> {
  const runId = `${Date.now().toString(36)}-${crypto.randomUUID().slice(0, 8)}`;
  const artifactDir = join(repoRoot, "test-results/native-transport", runId);
  const controlPath = join(artifactDir, "control.json");
  const resultPath = join(artifactDir, "result.json");
  const maestroOutput = join(artifactDir, "maestro");
  await mkdir(artifactDir, { recursive: true });
  const port = await reservePort();
  const mobileRoot = join(repoRoot, "apps/mobile");
  let metro: ReturnType<OwnedProcesses["spawn"]> | undefined;
  let probe: ReturnType<OwnedProcesses["spawn"]> | undefined;
  let maestro: ReturnType<OwnedProcesses["spawn"]> | undefined;
  let failure: Error | undefined;
  try {
    const metroChild = scope.spawn(
      ["bun", "expo", "start", "--dev-client", "--port", String(port)],
      {
        cwd: mobileRoot,
        env: definedEnv({ ...env, CI: "1" }),
      },
    );
    metro = metroChild;
    await waitForMetro(scope, metro, port);

    const probeChild = scope.spawn(
      [
        "uv",
        "run",
        "--project",
        join(repoRoot, "apps/agent"),
        "python",
        join(repoRoot, "apps/agent/native_transport_probe.py"),
        "--run-id",
        runId,
        "--fault",
        fault,
        "--control",
        controlPath,
        "--result",
        resultPath,
      ],
      { cwd: repoRoot, env: definedEnv(env) },
    );
    probe = probeChild;
    const control = await waitForJson(scope, controlPath, 60_000);
    const fixtureUrl = typeof control.fixture_url === "string" ? control.fixture_url : "";
    if (!fixtureUrl.startsWith("http://127.0.0.1:"))
      throw new Error("probe supplied no loopback fixture URL");
    const appLaunchUrl = developmentClientUrl(port);
    const expectedStatus =
      fault === "none"
        ? "Transport complete"
        : `Guard failed: ${fault === "withhold-audio" ? "received-audio" : "session-init-hud"}`;
    maestro = scope.spawn(
      [
        "maestro",
        `--device=${udid}`,
        "test",
        `--test-output-dir=${maestroOutput}`,
        "-e",
        `APP_LAUNCH_URL=${appLaunchUrl}`,
        "-e",
        `ROUTE_URL=${transportRouteUrl(fixtureUrl, runId)}`,
        "-e",
        `EXPECTED_STATUS=${expectedStatus}`,
        "-e",
        `RUN_ID_TEXT=Run: ${runId}`,
        "-e",
        `MOBILE_IDENTITY_TEXT=Mobile: mobile-${runId}`,
        "-e",
        `PUBLISHER_IDENTITY_TEXT=Publisher: python-${runId}`,
        "-e",
        "SCREENSHOT_PATH=simulator",
        join(mobileRoot, ".maestro/native-transport.yaml"),
      ],
      { cwd: mobileRoot, env: definedEnv(env) },
    );
    const maestroExit = await scope.wait(maestro.exited);
    if (maestroExit !== 0)
      throw new Error(`Maestro native transport failed with status ${maestroExit}`);
    const rawResult = await waitForJson(scope, resultPath, 10_000);
    const result = validateScenarioResult(rawResult, runId, fault);
    const screenshotMatches = await Array.fromAsync(
      new Bun.Glob("**/takeScreenshot/simulator.png").scan({ cwd: maestroOutput }),
    );
    if (screenshotMatches.length !== 1) {
      throw new Error(`Maestro emitted ${screenshotMatches.length} simulator screenshots`);
    }
    const screenshotPath = join(maestroOutput, screenshotMatches[0]);
    const screenshot = await stat(screenshotPath).catch(() => null);
    if (!screenshot?.isFile() || screenshot.size === 0)
      throw new Error("Maestro screenshot is missing or empty");
    const durable = {
      ...result,
      simulator_udid: udid,
      screenshot: join("maestro", screenshotMatches[0]),
      tool: "maestro",
      expo_mcp: "unavailable_in_tool_catalog",
    };
    const serialized = JSON.stringify(durable, null, 2) + "\n";
    assertNoCredentials(durable);
    await writeFile(resultPath, serialized);
    const probeExit = await scope.wait(probe.exited);
    if (probeExit !== 0) throw new Error(`native transport probe failed with status ${probeExit}`);
  } catch (error) {
    failure = error instanceof Error ? error : new Error(String(error));
  }
  const cleanup = await Promise.allSettled([
    scope.stop(probe),
    scope.stop(metro),
    scope.stop(maestro),
  ]);
  if (failure) throw failure;
  const rejected = cleanup.filter((entry) => entry.status === "rejected");
  if (rejected.length) throw new AggregateError(rejected, "native transport cleanup failed");
}

export async function runNativeTransport(
  repoRoot: string,
  processEnv: Record<string, string | undefined>,
  selectedFault?: Fault,
  prepareNativeApp: PrepareNativeApp = buildCurrentNativeApp,
): Promise<void> {
  await withOwnedProcesses(async (scope) => {
    const udid = required(processEnv, "IOS_SIMULATOR_UDID");
    if (udid !== OWNED_SIMULATOR_UDID) {
      throw new Error(
        `IOS_SIMULATOR_UDID must be the sprint-owned simulator ${OWNED_SIMULATOR_UDID}`,
      );
    }
    await prepareNativeApp(scope, repoRoot, processEnv);
    await requireTargetSimulator(scope, repoRoot, udid);
    const flow = join(repoRoot, "apps/mobile/.maestro/native-transport.yaml");
    if ((await stat(flow)).size === 0) throw new Error("native transport Maestro flow is empty");
    for (const fault of selectedFault ? [selectedFault] : SCENARIOS) {
      scope.signal.throwIfAborted();
      await runScenario(scope, repoRoot, processEnv, udid, fault);
    }
  });
}

if (import.meta.main) {
  const repoRoot = resolve(import.meta.dir, "../../..");
  const faultArg = process.argv.indexOf("--fault");
  const selected = faultArg >= 0 ? (process.argv[faultArg + 1] as Fault) : undefined;
  if (selected && !SCENARIOS.includes(selected)) throw new Error(`unknown fault: ${selected}`);
  await runNativeTransport(repoRoot, process.env, selected);
}
