import {
  copyFile,
  lstat,
  mkdir,
  mkdtemp,
  readFile,
  readlink,
  rm,
  stat,
  symlink,
} from "node:fs/promises";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";

import {
  createRealGateDeps,
  listSimulatorDevices,
  requestedDeviceIsBooted,
  runGate,
  type SimulatorDevice,
} from "../../../scripts/maestro-acceptance";
import type { CommandResult, NativeBuildDeps } from "./verify-native-build";
import { createRealOwnedSimulatorDeps, resolveOwnedSimulator } from "./owned-simulator";

interface OwnedProcess {
  pid: number;
  exited: Promise<number | null>;
  kill(signal?: number | NodeJS.Signals): void;
}

function definedEnv(env: Record<string, string | undefined>): Record<string, string> {
  return Object.fromEntries(
    Object.entries(env).filter((entry): entry is [string, string] => entry[1] !== undefined),
  );
}

async function capture(command: string[], cwd?: string): Promise<string> {
  const child = Bun.spawn(command, { cwd, stdout: "pipe", stderr: "pipe" });
  const [stdout, stderr, exit] = await Promise.all([
    new Response(child.stdout).text(),
    new Response(child.stderr).text(),
    child.exited,
  ]);
  if (exit !== 0) throw new Error(`${command.join(" ")} failed: ${stderr.trim()}`);
  return stdout;
}

async function runCommand(
  command: string[],
  cwd: string,
  env: Record<string, string | undefined>,
): Promise<CommandResult> {
  const child = Bun.spawn(command, {
    cwd,
    env: definedEnv(env),
    stdout: "inherit",
    stderr: "inherit",
  });
  const exitCode = await child.exited;
  return {
    exitCode,
    signal: child.signalCode === null ? undefined : String(child.signalCode),
  };
}

function parseEnv(text: string): Record<string, string> {
  const env: Record<string, string> = {};
  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) continue;
    const match = line.match(/^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$/);
    if (!match) throw new Error("root .env contains an invalid assignment");
    let value = match[2].trim();
    if (
      value.length >= 2 &&
      ((value.startsWith('"') && value.endsWith('"')) ||
        (value.startsWith("'") && value.endsWith("'")))
    ) {
      value = value.slice(1, -1);
    }
    env[match[1]] = value;
  }
  if (Object.keys(env).length === 0) throw new Error("root .env produced no variables");
  return env;
}

export function requiredSimulatorAction(
  devices: SimulatorDevice[],
  udid: string,
): "ready" | "boot" {
  const device = devices.find((candidate) => candidate.udid === udid);
  if (!device) throw new Error(`requested simulator is unknown: ${udid}`);
  if (device.isAvailable === false) throw new Error(`requested simulator is unavailable: ${udid}`);
  if (device.state === "Booted") return "ready";
  if (device.state === "Shutdown") return "boot";
  throw new Error(`requested simulator has unsupported state ${device.state}: ${udid}`);
}

async function ensureSimulator(udid: string): Promise<void> {
  if (requiredSimulatorAction(await listSimulatorDevices(), udid) === "boot") {
    await capture(["xcrun", "simctl", "boot", udid]);
    await capture(["xcrun", "simctl", "bootstatus", udid, "-b"]);
  }
  if (!requestedDeviceIsBooted(await listSimulatorDevices(), udid)) {
    throw new Error(`requested simulator did not become booted and available: ${udid}`);
  }
}

export function shouldCopyPath(path: string): boolean {
  return !(
    path === ".env" ||
    path.startsWith("apps/mobile/ios/") ||
    path.startsWith("apps/mobile/android/") ||
    path.includes("/node_modules/") ||
    path.includes("/.expo/")
  );
}

async function createWorkspace(repoRoot: string): Promise<string> {
  const listed = await capture(
    ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
    repoRoot,
  );
  const files = listed.split("\0").filter(Boolean).filter(shouldCopyPath);
  if (files.length === 0) throw new Error("isolated source file corpus is empty");
  const target = await mkdtemp(join(tmpdir(), "divineruin-story-208-"));
  let copied = 0;
  for (const relative of files) {
    const source = join(repoRoot, relative);
    const destination = join(target, relative);
    const metadata = await lstat(source).catch((error: NodeJS.ErrnoException) => {
      if (error.code === "ENOENT") return null;
      throw error;
    });
    if (!metadata) continue;
    await mkdir(dirname(destination), { recursive: true });
    if (metadata.isSymbolicLink()) {
      await symlink(await readlink(source), destination);
      copied += 1;
    } else if (metadata.isFile()) {
      await copyFile(source, destination);
      copied += 1;
    }
  }
  if (copied === 0) {
    await rm(target, { recursive: true, force: true });
    throw new Error("isolated source copy produced no files");
  }
  await capture(["git", "init", "--quiet"], target);
  return target;
}

async function requireNonemptyFile(path: string): Promise<void> {
  const metadata = await stat(path).catch(() => null);
  if (!metadata?.isFile() || metadata.size === 0)
    throw new Error(`required file is missing or empty: ${path}`);
}

async function requireGeneratedNativeProjects(mobileRoot: string): Promise<void> {
  await requireNonemptyFile(join(mobileRoot, "ios/Podfile"));
  await requireNonemptyFile(join(mobileRoot, "android/settings.gradle"));
}

async function reservePort(): Promise<number> {
  const server = createServer();
  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  const address = server.address();
  if (!address || typeof address === "string") throw new Error("failed to reserve a Metro port");
  await new Promise<void>((resolve, reject) =>
    server.close((error) => (error ? reject(error) : resolve())),
  );
  return address.port;
}

function startMetro(
  mobileRoot: string,
  port: number,
  env: Record<string, string | undefined>,
): Promise<OwnedProcess> {
  const child = Bun.spawn(["bun", "expo", "start", "--dev-client", "--port", String(port)], {
    cwd: mobileRoot,
    env: definedEnv({ ...env, CI: "1" }),
    stdout: "inherit",
    stderr: "inherit",
  });
  return Promise.resolve({
    pid: child.pid,
    exited: child.exited,
    kill: (signal) => child.kill(signal),
  });
}

async function waitForMetro(process: OwnedProcess, port: number): Promise<void> {
  let exit: number | null | undefined;
  void process.exited.then((value) => {
    exit = value;
  });
  const deadline = Date.now() + 120_000;
  while (Date.now() < deadline) {
    if (exit !== undefined)
      throw new Error(`Metro exited before readiness with status ${String(exit)}`);
    try {
      const response = await fetch(`http://127.0.0.1:${port}/status`, {
        signal: AbortSignal.timeout(1_000),
      });
      if (response.ok && (await response.text()).includes("packager-status:running")) return;
    } catch {
      // Connection refusal is expected while the owned Metro process starts.
    }
    await Bun.sleep(500);
  }
  throw new Error(`Metro readiness timed out on port ${port}`);
}

async function stopMetro(process: OwnedProcess): Promise<void> {
  process.kill("SIGTERM");
  const stopped = await Promise.race([
    process.exited.then(() => true),
    Bun.sleep(10_000).then(() => false),
  ]);
  if (!stopped) {
    process.kill("SIGKILL");
    await process.exited;
  }
}

export function createNativeBuildDeps(repoRoot: string): NativeBuildDeps {
  const ownedDeps = createRealOwnedSimulatorDeps(repoRoot);
  return {
    loadRootEnvironment: async (root) => parseEnv(await readFile(join(root, ".env"), "utf8")),
    requireNonemptyFile,
    resolveOwnedSimulator: (requested) => resolveOwnedSimulator(ownedDeps, requested),
    ensureSimulator,
    probeBackend: async (url) => {
      await fetch(url, { signal: AbortSignal.timeout(5_000) });
    },
    createWorkspace,
    runCommand,
    requireGeneratedNativeProjects,
    isAppInstalled: async (udid, bundleId) => {
      try {
        await capture(["xcrun", "simctl", "get_app_container", udid, bundleId, "app"]);
        return true;
      } catch {
        return false;
      }
    },
    reservePort,
    startMetro,
    waitForMetro: (process, port) => waitForMetro(process as OwnedProcess, port),
    runAcceptance: (env) => runGate(createRealGateDeps(env, repoRoot)),
    stopMetro: (process) => stopMetro(process as OwnedProcess),
    removeWorkspace: (root) => rm(root, { recursive: true, force: true }),
  };
}
