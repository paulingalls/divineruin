import { join } from "node:path";

import type { GateResult } from "../../../scripts/maestro-acceptance";
import { createNativeBuildDeps } from "./verify-native-build-runtime";

export interface CommandResult {
  exitCode: number | null;
  signal?: string;
}

export interface NativeBuildDeps {
  loadRootEnvironment: (repoRoot: string) => Promise<Record<string, string | undefined>>;
  requireNonemptyFile: (path: string) => Promise<void>;
  ensureSimulator: (udid: string) => Promise<void>;
  probeBackend: (url: string) => Promise<void>;
  createWorkspace: (repoRoot: string) => Promise<string>;
  runCommand: (
    command: string[],
    cwd: string,
    env: Record<string, string | undefined>,
  ) => Promise<CommandResult>;
  requireGeneratedNativeProjects: (mobileRoot: string) => Promise<void>;
  isAppInstalled: (udid: string, bundleId: string) => Promise<boolean>;
  reservePort: () => Promise<number>;
  startMetro: (
    mobileRoot: string,
    port: number,
    env: Record<string, string | undefined>,
  ) => Promise<unknown>;
  waitForMetro: (process: unknown, port: number) => Promise<void>;
  runAcceptance: (env: Record<string, string | undefined>) => Promise<GateResult>;
  stopMetro: (process: unknown) => Promise<void>;
  removeWorkspace: (root: string) => Promise<void>;
}

export interface NativeBuildOptions {
  repoRoot: string;
  processEnv: Record<string, string | undefined>;
  deps: NativeBuildDeps;
}

const BUNDLE_ID = "com.divineruin.app";

function developmentClientUrl(port: number): string {
  const metroUrl = encodeURIComponent(`http://127.0.0.1:${port}`);
  return `exp+divineruin://expo-development-client/?url=${metroUrl}`;
}

function required(env: Record<string, string | undefined>, name: string): string {
  const value = env[name]?.trim();
  if (!value) throw new Error(`${name} is required for native verification`);
  return value;
}

async function runChecked(
  deps: NativeBuildDeps,
  name: string,
  command: string[],
  cwd: string,
  env: Record<string, string | undefined>,
): Promise<void> {
  let result: CommandResult;
  try {
    result = await deps.runCommand(command, cwd, env);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    throw new Error(`${name} failed to start: ${message}`, { cause: error });
  }
  if (result.exitCode === null) {
    throw new Error(`${name} terminated by ${result.signal ?? "an unknown signal"}`);
  }
  if (result.exitCode !== 0) throw new Error(`${name} failed with exit status ${result.exitCode}`);
}

export async function runNativeBuild(options: NativeBuildOptions): Promise<void> {
  const { deps, repoRoot } = options;
  const fileEnv = await deps.loadRootEnvironment(repoRoot);
  const env = { ...fileEnv, ...options.processEnv };
  const udid = required(env, "IOS_SIMULATOR_UDID");
  const apiUrl = required(env, "EXPO_PUBLIC_API_URL");
  const sourceMobile = join(repoRoot, "apps/mobile");

  await deps.requireNonemptyFile(join(sourceMobile, ".maestro/launch.yaml"));
  await deps.requireNonemptyFile(join(sourceMobile, ".maestro/auth-form.yaml"));
  await deps.ensureSimulator(udid);
  await deps.probeBackend(apiUrl);

  let workspace: string | undefined;
  let metro: unknown;
  try {
    workspace = await deps.createWorkspace(repoRoot);
    const mobileRoot = join(workspace, "apps/mobile");
    await runChecked(
      deps,
      "dependency install",
      ["bun", "install", "--frozen-lockfile"],
      workspace,
      { ...env, BUN_INSTALL_CACHE_DIR: join(workspace, ".bun-cache") },
    );
    await runChecked(
      deps,
      "native prebuild",
      ["bun", "expo", "prebuild", "--clean", "--platform", "all", "--no-install"],
      mobileRoot,
      env,
    );
    await deps.requireGeneratedNativeProjects(mobileRoot);

    await runChecked(
      deps,
      "iOS development build",
      ["bun", "expo", "run:ios", "--device", udid, "--no-bundler"],
      mobileRoot,
      env,
    );
    if (!(await deps.isAppInstalled(udid, BUNDLE_ID))) {
      throw new Error(`${BUNDLE_ID} is not installed on requested simulator ${udid}`);
    }

    const port = await deps.reservePort();
    metro = await deps.startMetro(mobileRoot, port, env);
    await deps.waitForMetro(metro, port);
    const appLaunchUrl = developmentClientUrl(port);
    await runChecked(
      deps,
      "app launch",
      ["xcrun", "simctl", "openurl", udid, appLaunchUrl],
      mobileRoot,
      env,
    );
    const acceptance = await deps.runAcceptance({
      ...env,
      REQUIRE_EMULATOR: "1",
      REQUIRE_BACKEND: "1",
      IOS_SIMULATOR_UDID: udid,
      MAESTRO_APP_LAUNCH_URL: appLaunchUrl,
    });
    if (!acceptance.maestroInvoked) throw new Error("Maestro acceptance was not invoked");
    if (acceptance.exitCode !== 0) {
      throw new Error(`Maestro acceptance failed with exit status ${acceptance.exitCode}`);
    }
  } finally {
    if (metro) await deps.stopMetro(metro);
    if (workspace) await deps.removeWorkspace(workspace);
  }
}

if (import.meta.main) {
  const repoRoot = join(import.meta.dir, "../../..");
  await runNativeBuild({
    repoRoot,
    processEnv: process.env,
    deps: createNativeBuildDeps(repoRoot),
  });
}
