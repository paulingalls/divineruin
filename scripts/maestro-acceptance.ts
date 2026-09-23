import {
  createRealOwnedSimulatorDeps,
  resolveOwnedSimulator,
} from "../apps/mobile/scripts/owned-simulator";

export interface SimulatorDevice {
  udid?: string;
  name?: string;
  state?: string;
  isAvailable?: boolean;
}

export interface GateDeps {
  env: Record<string, string | undefined>;
  resolveOwnedSimulator: (requestedUdid?: string) => Promise<string>;
  runSimctl: () => Promise<string>;
  runAdb: () => Promise<string>;
  probeRequestedIos: (udid: string) => Promise<boolean>;
  runMaestro: (udid: string | undefined, flows: string[]) => Promise<number>;
}

export interface GateResult {
  exitCode: number;
  stdout: string;
  stderr: string;
  maestroInvoked: boolean;
}

const OFFLINE_SAFE_FLOWS = ["launch.yaml"];
const BACKEND_REQUIRED_FLOWS = ["auth-form.yaml"];
const SIMCTL_BOOTED_PATTERN = /\(Booted\)/;
const ADB_DEVICE_LINE = /^\S+\s+device\b/m;

interface DetectionResult {
  present: boolean;
  diagnostic?: string;
}

function isToolMissing(error: unknown): boolean {
  const message = error instanceof Error ? error.message : String(error);
  return /ENOENT|not found|No such file/i.test(message);
}

async function detect(
  label: string,
  probe: () => Promise<string>,
  pattern: RegExp,
): Promise<DetectionResult> {
  try {
    return { present: pattern.test(await probe()) };
  } catch (error) {
    if (isToolMissing(error)) return { present: false };
    const message = error instanceof Error ? error.message : String(error);
    return { present: false, diagnostic: `${label} probe failed: ${message}` };
  }
}

function failure(stderr: string): GateResult {
  return { exitCode: 1, stdout: "", stderr, maestroInvoked: false };
}

export function parseSimulatorDevices(raw: string): SimulatorDevice[] {
  const payload = JSON.parse(raw) as { devices?: Record<string, SimulatorDevice[]> };
  const devices = Object.values(payload.devices ?? {}).flat();
  if (devices.length === 0) throw new Error("simctl returned no simulator devices");
  return devices;
}

export function requestedDeviceIsBooted(devices: SimulatorDevice[], udid: string): boolean {
  return devices.some(
    (device) => device.udid === udid && device.state === "Booted" && device.isAvailable !== false,
  );
}

export async function runGate(deps: GateDeps): Promise<GateResult> {
  const strict = deps.env.REQUIRE_EMULATOR === "1";
  let requestedUdid = deps.env.IOS_SIMULATOR_UDID;
  const flows = [...OFFLINE_SAFE_FLOWS];
  if (deps.env.REQUIRE_BACKEND === "1") flows.push(...BACKEND_REQUIRED_FLOWS);

  if (strict || requestedUdid !== undefined) {
    try {
      requestedUdid = await deps.resolveOwnedSimulator(requestedUdid);
    } catch (error) {
      return failure(error instanceof Error ? error.message : String(error));
    }
  }

  if (requestedUdid) {
    try {
      if (!(await deps.probeRequestedIos(requestedUdid))) {
        return failure(`Requested iOS simulator is not booted and available: ${requestedUdid}`);
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      return failure(`Requested iOS simulator probe failed for ${requestedUdid}: ${message}`);
    }
  } else {
    const [ios, android] = await Promise.all([
      detect("xcrun simctl", deps.runSimctl, SIMCTL_BOOTED_PATTERN),
      detect("adb devices", deps.runAdb, ADB_DEVICE_LINE),
    ]);
    if (!ios.present && !android.present) {
      const diagnostics = [ios.diagnostic, android.diagnostic].filter((value): value is string =>
        Boolean(value),
      );
      return {
        exitCode: 0,
        stdout:
          "Maestro acceptance: skipped (no booted iOS simulator or attached Android device). " +
          "Set REQUIRE_EMULATOR=1 to use the owned iOS simulator." +
          diagnostics.map((diagnostic) => `\n  - ${diagnostic}`).join(""),
        stderr: "",
        maestroInvoked: false,
      };
    }
  }

  const exit = await deps.runMaestro(requestedUdid, flows);
  return {
    exitCode: typeof exit === "number" ? exit : 130,
    stdout: "",
    stderr: "",
    maestroInvoked: true,
  };
}

async function spawnText(command: string[]): Promise<string> {
  const child = Bun.spawn(command, { stdout: "pipe", stderr: "pipe" });
  const [stdout, stderr, exit] = await Promise.all([
    new Response(child.stdout).text(),
    new Response(child.stderr).text(),
    child.exited,
  ]);
  if (exit !== 0) throw new Error(`${command[0]} exited ${String(exit)}: ${stderr.trim()}`);
  return stdout;
}

export async function listSimulatorDevices(): Promise<SimulatorDevice[]> {
  return parseSimulatorDevices(await spawnText(["xcrun", "simctl", "list", "devices", "--json"]));
}

async function spawnInherit(command: string[], cwd: string): Promise<number> {
  const child = Bun.spawn(command, { stdout: "inherit", stderr: "inherit", cwd });
  const exit = await child.exited;
  return typeof exit === "number" ? exit : 130;
}

export function maestroCommand(
  udid: string | undefined,
  flows: string[],
  maestroDir: string,
  appLaunchUrl = "divineruin://",
): string[] {
  return [
    "maestro",
    ...(udid ? [`--device=${udid}`] : []),
    "test",
    "-e",
    `APP_LAUNCH_URL=${appLaunchUrl}`,
    ...flows.map((flow) => `${maestroDir}/${flow}`),
  ];
}

export function createRealGateDeps(
  env: Record<string, string | undefined>,
  repoRoot: string,
): GateDeps {
  const mobileDir = `${repoRoot}/apps/mobile`;
  const maestroDir = `${mobileDir}/.maestro`;
  const ownedDeps = createRealOwnedSimulatorDeps(repoRoot);
  return {
    env,
    resolveOwnedSimulator: (requested) => resolveOwnedSimulator(ownedDeps, requested),
    runSimctl: () => spawnText(["xcrun", "simctl", "list", "devices"]),
    runAdb: () => spawnText(["adb", "devices"]),
    probeRequestedIos: async (udid) => requestedDeviceIsBooted(await listSimulatorDevices(), udid),
    runMaestro: (udid, flows) =>
      spawnInherit(maestroCommand(udid, flows, maestroDir, env.MAESTRO_APP_LAUNCH_URL), mobileDir),
  };
}

if (import.meta.main) {
  const repoRoot = new URL("..", import.meta.url).pathname.replace(/\/$/, "");
  const gate = await runGate(createRealGateDeps(process.env, repoRoot));
  if (gate.stdout) console.log(gate.stdout);
  if (gate.stderr) console.error(gate.stderr);
  process.exit(gate.exitCode);
}
