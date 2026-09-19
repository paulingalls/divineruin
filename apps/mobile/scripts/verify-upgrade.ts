import { readFile, rm, stat } from "node:fs/promises";
import { join } from "node:path";

import { verifySdk57Baseline } from "./sdk-baseline";

export interface CommandResult {
  exitCode: number | null;
  signal?: string;
}

export interface VerificationOptions {
  projectRoot: string;
  verifyBaseline: () => Promise<void>;
  runCommand?: (command: string[], cwd: string) => Promise<CommandResult>;
}

interface Stage {
  name: string;
  command: string[];
}

const stages = {
  dependencyCheck: {
    name: "Expo dependency check",
    command: ["bun", "expo", "install", "--check"],
  },
  doctor: { name: "Expo Doctor", command: ["bunx", "expo-doctor"] },
  routeTypes: {
    name: "Expo Router type generation",
    command: ["bun", "expo", "customize", "tsconfig.json"],
  },
  typecheck: { name: "mobile typecheck", command: ["bunx", "tsc", "--noEmit"] },
} satisfies Record<string, Stage>;

export async function defaultRunCommand(command: string[], cwd: string): Promise<CommandResult> {
  const child = Bun.spawn(command, {
    cwd,
    // Expo's web render probes Corepack, which otherwise auto-pins pnpm in package.json.
    env: { ...process.env, COREPACK_ENABLE_PROJECT_SPEC: "0" },
    stdout: "inherit",
    stderr: "inherit",
  });
  const exitCode = await child.exited;
  return {
    exitCode,
    signal: child.signalCode === null ? undefined : String(child.signalCode),
  };
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

async function executeStage(
  stage: Stage,
  projectRoot: string,
  runCommand: NonNullable<VerificationOptions["runCommand"]>,
): Promise<void> {
  let result: CommandResult;
  try {
    result = await runCommand(stage.command, projectRoot);
  } catch (error) {
    throw new Error(`${stage.name} failed to start: ${errorMessage(error)}`, { cause: error });
  }
  if (result.exitCode === null) {
    throw new Error(`${stage.name} terminated by ${result.signal ?? "an unknown signal"}`);
  }
  if (result.exitCode !== 0) {
    throw new Error(`${stage.name} failed with exit status ${result.exitCode}`);
  }
}

// Exported because CI needs the generation AND its floor without the export
// stages: `lint:ts` typechecks apps/mobile, whose tsconfig includes the gitignored
// generated types. A missing expo-env.d.ts reds loudly (TS2882), but a missing
// router.d.ts does not — `Href` falls back to `string`, so a bogus route compiles
// clean. Measured 2026-09-19: dropping .expo/types alone typechecks a
// `router.push("/definitely-not-a-route")` green.
export async function generateRouteTypes(
  projectRoot: string,
  runCommand: NonNullable<VerificationOptions["runCommand"]> = defaultRunCommand,
): Promise<void> {
  const tsconfig = join(projectRoot, "tsconfig.json");
  const before = await readFile(tsconfig);
  const typesDirectory = join(projectRoot, ".expo", "types");
  await rm(typesDirectory, { recursive: true, force: true });
  await executeStage(stages.routeTypes, projectRoot, runCommand);
  const after = await readFile(tsconfig);
  if (!before.equals(after)) {
    throw new Error("Expo Router type generation changed tsconfig.json");
  }

  const routeTypes = join(typesDirectory, "router.d.ts");
  const generated = await stat(routeTypes).catch(() => null);
  if (!generated?.isFile() || generated.size === 0) {
    throw new Error("Expo Router generated route types must be a nonempty regular file");
  }
}

function exportStage(platform: "ios" | "android" | "web"): Stage {
  return {
    name: `${platform} export`,
    command: [
      "bun",
      "expo",
      "export",
      "--platform",
      platform,
      "--clear",
      "--output-dir",
      `.expo/upgrade-exports/${platform}`,
    ],
  };
}

export async function runUpgradeVerification(options: VerificationOptions): Promise<void> {
  const runCommand = options.runCommand ?? defaultRunCommand;
  await options.verifyBaseline();
  await executeStage(stages.dependencyCheck, options.projectRoot, runCommand);
  await executeStage(stages.doctor, options.projectRoot, runCommand);
  await generateRouteTypes(options.projectRoot, runCommand);
  await executeStage(stages.typecheck, options.projectRoot, runCommand);

  for (const platform of ["ios", "android", "web"] as const) {
    await rm(join(options.projectRoot, ".expo", "upgrade-exports", platform), {
      recursive: true,
      force: true,
    });
    await executeStage(exportStage(platform), options.projectRoot, runCommand);
  }
}

if (import.meta.main) {
  const projectRoot = join(import.meta.dir, "..");
  const repoRoot = join(projectRoot, "../..");
  await runUpgradeVerification({
    projectRoot,
    verifyBaseline: () => verifySdk57Baseline({ repoRoot }),
  });
}
