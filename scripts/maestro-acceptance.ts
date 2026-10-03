import {
  createRealOwnedSimulatorDeps,
  resolveOwnedSimulator,
  lookupOwnedSimulator,
  OwnedSimulatorProbeError,
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
  lookupOwnedSimulator: () => ReturnType<typeof lookupOwnedSimulator>;
  runAdb: () => Promise<string>;
  probeRequestedIos: (udid: string) => Promise<boolean>;
  runMaestro: (device: string, flows: string[]) => Promise<number>;
}

export interface GateResult {
  exitCode: number;
  stdout: string;
  stderr: string;
  maestroInvoked: boolean;
}

const OFFLINE_SAFE_FLOWS = ["launch.yaml"];
const BACKEND_REQUIRED_FLOWS = ["auth-form.yaml"];
function isToolMissing(error: unknown): boolean {
  const message = error instanceof Error ? error.message : String(error);
  return /ENOENT|not found|No such file/i.test(message);
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

  const targets: string[] = [];
  let stdout = "";
  if (requestedUdid) {
    try {
      if (!(await deps.probeRequestedIos(requestedUdid))) {
        return failure(`Requested iOS simulator is not booted and available: ${requestedUdid}`);
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      return failure(`Requested iOS simulator probe failed for ${requestedUdid}: ${message}`);
    }
    targets.push(requestedUdid);
  } else {
    try {
      const { name, device } = await deps.lookupOwnedSimulator();
      if (device?.state === "Booted") targets.push(device.udid!);
      else
        stdout =
          `Maestro acceptance: skipped owned iOS simulator ${name}. ` +
          (device
            ? `Boot it with xcrun simctl boot ${device.udid} && xcrun simctl bootstatus ${device.udid} -b.`
            : "Provision it with bun run --cwd apps/mobile verify:native-build, then boot the owned simulator.");
    } catch (error) {
      if (!(error instanceof OwnedSimulatorProbeError))
        return failure(`Owned iOS simulator lookup failed: ${String(error)}`);
      stdout =
        `Maestro acceptance: skipped owned iOS simulator ${error.simulatorName}. ` +
        "Use bun run --cwd apps/mobile verify:native-build to provision and boot it.";
      if (!isToolMissing(error.cause)) stdout += `\n  - ${error.message}`;
    }
    try {
      const serial = (await deps.runAdb()).match(/^(\S+)\s+device\s*$/m)?.[1];
      if (serial) targets.push(serial);
    } catch (error) {
      if (!isToolMissing(error))
        stdout += `\n  - adb devices probe failed: ${error instanceof Error ? error.message : String(error)}`;
    }
  }

  let exitCode = 0;
  for (const device of targets) {
    const exit = await deps.runMaestro(device, flows);
    if (exitCode === 0) exitCode = typeof exit === "number" ? exit : 130;
  }
  return { exitCode, stdout, stderr: "", maestroInvoked: targets.length > 0 };
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
  device: string,
  flows: string[],
  maestroDir: string,
  appLaunchUrl = "divineruin://",
): string[] {
  return [
    "maestro",
    `--device=${device}`,
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
    lookupOwnedSimulator: () => lookupOwnedSimulator(ownedDeps),
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
