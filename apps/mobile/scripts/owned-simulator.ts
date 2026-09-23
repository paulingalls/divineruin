export interface OwnedSimulatorDeps {
  cloneId: () => Promise<string>;
  run: (command: string[]) => Promise<string>;
}

interface Runtime {
  identifier?: string;
  version?: string;
  isAvailable?: boolean;
  supportedDeviceTypes?: { identifier?: string; productFamily?: string; name?: string }[];
}
interface Device {
  udid?: string;
  name?: string;
  state?: string;
  isAvailable?: boolean;
}

function parseRuntimes(raw: string): Runtime[] {
  const payload = JSON.parse(raw) as { runtimes?: Runtime[] };
  if (!Array.isArray(payload.runtimes) || payload.runtimes.length === 0)
    throw new Error("simctl returned no runtimes");
  return payload.runtimes;
}

function parseDevices(raw: string): Device[] {
  const payload = JSON.parse(raw) as { devices?: Record<string, Device[]> };
  if (!payload.devices || typeof payload.devices !== "object")
    throw new Error("simctl returned no devices");
  const devices = Object.values(payload.devices).flat();
  if (devices.length === 0) throw new Error("simctl returned no devices");
  return devices;
}

function versionParts(version: string): number[] {
  if (!/^\d+(?:\.\d+)*$/.test(version)) throw new Error(`invalid iOS runtime version ${version}`);
  return version.split(".").map(Number);
}

function newer(a: Runtime, b: Runtime): number {
  const left = versionParts(a.version ?? "");
  const right = versionParts(b.version ?? "");
  for (let i = 0; i < Math.max(left.length, right.length); i++) {
    const difference = (right[i] ?? 0) - (left[i] ?? 0);
    if (difference) return difference;
  }
  return 0;
}

function ownedDevice(devices: Device[], name: string): Device | undefined {
  const matches = devices.filter((device) => device.name === name);
  if (matches.length > 1) throw new Error(`multiple owned simulators named ${name}`);
  const device = matches.at(0);
  if (
    device &&
    (!device.udid?.trim() ||
      device.isAvailable !== true ||
      !["Booted", "Shutdown"].includes(device.state ?? ""))
  )
    throw new Error(`owned simulator ${name} is unusable`);
  return device;
}

export async function resolveOwnedSimulator(
  deps: OwnedSimulatorDeps,
  requestedUdid?: string,
): Promise<string> {
  const cloneId = (await deps.cloneId()).trim();
  if (!cloneId) throw new Error("clone ID is empty");
  const name = `divineruin-native-${cloneId}`;
  const runtimes = parseRuntimes(await deps.run(["xcrun", "simctl", "list", "runtimes", "--json"]));
  const ios = runtimes.filter(
    (runtime) =>
      runtime.isAvailable === true &&
      runtime.identifier?.startsWith("com.apple.CoreSimulator.SimRuntime.iOS-"),
  );
  ios.sort(newer);
  const runtime = ios.at(0);
  if (!runtime) throw new Error("no available iOS runtime");
  const devices = parseDevices(await deps.run(["xcrun", "simctl", "list", "devices", "--json"]));
  let device = ownedDevice(devices, name);
  if (requestedUdid !== undefined && requestedUdid.trim() !== device?.udid)
    throw new Error(`IOS_SIMULATOR_UDID must name the owned simulator ${name}`);
  if (!device) {
    const phone = runtime.supportedDeviceTypes?.find(
      (type) => type.productFamily === "iPhone" && type.identifier,
    );
    if (!phone?.identifier || !runtime.identifier)
      throw new Error(`iOS runtime ${runtime.version} has no supported iPhone`);
    const udid = (
      await deps.run(["xcrun", "simctl", "create", name, phone.identifier, runtime.identifier])
    ).trim();
    if (!udid) throw new Error("simctl create returned an empty UDID");
    const created = parseDevices(await deps.run(["xcrun", "simctl", "list", "devices", "--json"]));
    device = ownedDevice(created, name);
    if (device?.udid !== udid)
      throw new Error(`created UDID ${udid} does not belong to owned simulator ${name}`);
  }
  return device.udid!;
}

async function capture(command: string[], cwd: string): Promise<string> {
  const child = Bun.spawn(command, { cwd, stdout: "pipe", stderr: "pipe" });
  const [stdout, stderr, exit] = await Promise.all([
    new Response(child.stdout).text(),
    new Response(child.stderr).text(),
    child.exited,
  ]);
  if (exit !== 0) throw new Error(`${command.join(" ")} failed: ${stderr.trim()}`);
  return stdout;
}

export function createRealOwnedSimulatorDeps(repoRoot: string): OwnedSimulatorDeps {
  return {
    cloneId: () =>
      capture(
        [
          "bash",
          "-c",
          "source scripts/worktree-common.sh && wt_identity && printf '%s' \"$WT_CLONE_ID\"",
        ],
        repoRoot,
      ),
    run: (command) => capture(command, repoRoot),
  };
}
