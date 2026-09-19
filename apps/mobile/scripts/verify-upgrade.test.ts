import { afterEach, describe, expect, test } from "bun:test";
import { mkdtemp, mkdir, readFile, realpath, rm, stat, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import {
  type CommandResult,
  type VerificationOptions,
  defaultRunCommand,
  runUpgradeVerification,
} from "./verify-upgrade";

const roots: string[] = [];

afterEach(async () => {
  await Promise.all(roots.splice(0).map((root) => rm(root, { recursive: true, force: true })));
});

async function fixture() {
  const projectRoot = await mkdtemp(join(tmpdir(), "verify-expo-upgrade-"));
  roots.push(projectRoot);
  await mkdir(join(projectRoot, "src", "app"), { recursive: true });
  await writeFile(join(projectRoot, "src", "app", "index.tsx"), "export default null;\n");
  await writeFile(join(projectRoot, "tsconfig.json"), '{"extends":"expo/tsconfig.base"}\n');
  return projectRoot;
}

async function failureMessage(action: Promise<unknown>): Promise<string> {
  try {
    await action;
  } catch (error) {
    return error instanceof Error ? error.message : String(error);
  }
  throw new Error("expected the action to fail");
}

async function pathExists(path: string): Promise<boolean> {
  try {
    await stat(path);
    return true;
  } catch {
    return false;
  }
}

function successfulRunner(projectRoot: string, calls: string[]) {
  return async (command: string[]): Promise<CommandResult> => {
    calls.push(command.join(" "));
    if (command.join(" ") === "bun expo customize tsconfig.json") {
      const types = join(projectRoot, ".expo", "types");
      await mkdir(types, { recursive: true });
      await writeFile(join(types, "router.d.ts"), "declare namespace ExpoRouter {}\n");
    }
    return { exitCode: 0 };
  };
}

const expectedCommands = [
  "bun expo install --check",
  "bunx expo-doctor",
  "bun expo customize tsconfig.json",
  "bunx tsc --noEmit",
  "bun expo export --platform ios --clear --output-dir .expo/upgrade-exports/ios",
  "bun expo export --platform android --clear --output-dir .expo/upgrade-exports/android",
  "bun expo export --platform web --clear --output-dir .expo/upgrade-exports/web",
];

describe("runUpgradeVerification", () => {
  test("runs every compatibility, type, and export stage in order", async () => {
    const projectRoot = await fixture();
    const calls: string[] = [];

    await runUpgradeVerification({ projectRoot, runCommand: successfulRunner(projectRoot, calls) });

    expect(calls).toEqual(expectedCommands);
  });

  test.each(expectedCommands.map((_, index) => index))(
    "propagates a nonzero result from stage %i",
    async (failedIndex) => {
      const projectRoot = await fixture();
      let index = 0;
      const options: VerificationOptions = {
        projectRoot,
        runCommand: async (command) => {
          const current = index++;
          if (current === failedIndex) return { exitCode: 23 };
          if (command.join(" ") === "bun expo customize tsconfig.json") {
            const types = join(projectRoot, ".expo", "types");
            await mkdir(types, { recursive: true });
            await writeFile(join(types, "router.d.ts"), "generated\n");
          }
          return { exitCode: 0 };
        },
      };

      expect(await failureMessage(runUpgradeVerification(options))).toContain("exit status 23");
      expect(index).toBe(failedIndex + 1);
    },
  );

  test("reports signal termination", async () => {
    const projectRoot = await fixture();
    const result = runUpgradeVerification({
      projectRoot,
      runCommand: () => Promise.resolve({ exitCode: null, signal: "SIGTERM" }),
    });
    expect(await failureMessage(result)).toContain("SIGTERM");
  });

  test("reports spawn failures with the stage name", async () => {
    const projectRoot = await fixture();
    const result = runUpgradeVerification({
      projectRoot,
      runCommand: () => Promise.reject(new Error("ENOENT")),
    });
    expect(await failureMessage(result)).toContain("Expo dependency check failed to start: ENOENT");
  });

  test("rejects successful type generation that produces no route types", async () => {
    const projectRoot = await fixture();
    const result = runUpgradeVerification({
      projectRoot,
      runCommand: () => Promise.resolve({ exitCode: 0 }),
    });
    expect(await failureMessage(result)).toContain("generated route types");
  });

  test("rejects route types left over from an earlier generation", async () => {
    const projectRoot = await fixture();
    await mkdir(join(projectRoot, ".expo", "types"), { recursive: true });
    await writeFile(join(projectRoot, ".expo", "types", "router.d.ts"), "stale\n");
    const result = runUpgradeVerification({
      projectRoot,
      runCommand: () => Promise.resolve({ exitCode: 0 }),
    });
    expect(await failureMessage(result)).toContain("generated route types");
  });

  test.each(["directory", "empty file"])(
    "rejects %s output as generated route types",
    async (kind) => {
      const projectRoot = await fixture();
      const result = runUpgradeVerification({
        projectRoot,
        runCommand: async (command) => {
          if (command[2] === "customize") {
            const directory = join(projectRoot, ".expo", "types");
            await mkdir(directory, { recursive: true });
            const routeTypes = join(directory, "router.d.ts");
            if (kind === "directory") await mkdir(routeTypes);
            else await writeFile(routeTypes, "");
          }
          return { exitCode: 0 };
        },
      });
      expect(await failureMessage(result)).toContain("generated route types");
    },
  );

  test("rejects type generation that edits tracked TypeScript config", async () => {
    const projectRoot = await fixture();
    const result = runUpgradeVerification({
      projectRoot,
      runCommand: async (command) => {
        if (command.join(" ") === "bun expo customize tsconfig.json") {
          await writeFile(join(projectRoot, "tsconfig.json"), "{}\n");
        }
        return { exitCode: 0 };
      },
    });
    expect(await failureMessage(result)).toContain("changed tsconfig.json");
  });

  test("removes stale export output before each platform export", async () => {
    const projectRoot = await fixture();
    for (const platform of ["ios", "android", "web"]) {
      const output = join(projectRoot, ".expo", "upgrade-exports", platform);
      await mkdir(output, { recursive: true });
      await writeFile(join(output, "stale.txt"), "stale\n");
    }
    const calls: string[] = [];
    const baseRunner = successfulRunner(projectRoot, calls);

    await runUpgradeVerification({
      projectRoot,
      runCommand: async (command) => {
        const platform = command[4];
        if (command[2] === "export") {
          expect(await pathExists(join(projectRoot, ".expo", "upgrade-exports", platform))).toBe(
            false,
          );
        }
        return baseRunner(command);
      },
    });

    expect(await readFile(join(projectRoot, ".expo", "types", "router.d.ts"), "utf8")).not.toBe("");
  });
});

describe("defaultRunCommand", () => {
  async function probe(projectRoot: string, expression: string): Promise<string> {
    const report = join(projectRoot, "probe.json");
    const result = await defaultRunCommand(
      ["bun", "-e", `await Bun.write(${JSON.stringify(report)}, String(${expression}))`],
      projectRoot,
    );
    expect(result).toEqual({ exitCode: 0, signal: undefined });
    return readFile(report, "utf8");
  }

  test("disables Corepack project pinning so exports cannot rewrite package.json", async () => {
    const projectRoot = await fixture();
    expect(await probe(projectRoot, "process.env.COREPACK_ENABLE_PROJECT_SPEC")).toBe("0");
  });

  test("passes the rest of the environment and the project root through", async () => {
    const projectRoot = await fixture();
    process.env.VERIFY_UPGRADE_PROBE = "inherited";
    try {
      expect(await probe(projectRoot, "process.env.VERIFY_UPGRADE_PROBE")).toBe("inherited");
    } finally {
      delete process.env.VERIFY_UPGRADE_PROBE;
    }
    expect(await probe(projectRoot, "process.cwd()")).toBe(await realpath(projectRoot));
  });

  test("reports the exit status of a failing command", async () => {
    const projectRoot = await fixture();
    expect(await defaultRunCommand(["bun", "-e", "process.exit(23)"], projectRoot)).toEqual({
      exitCode: 23,
      signal: undefined,
    });
  });
});
