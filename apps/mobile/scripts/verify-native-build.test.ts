import { describe, expect, test } from "bun:test";

import {
  type NativeBuildDeps,
  type NativeBuildOptions,
  runNativeBuild,
} from "./verify-native-build";
import { requiredSimulatorAction, shouldCopyPath } from "./verify-native-build-runtime";

const ROOT = "/source/story-208";
const TEMP = "/tmp/story-208-native";
const UDID = "A2080000-0000-0000-0000-000000000001";
const API_URL = "http://127.0.0.1:3001";

interface Fixture {
  deps: NativeBuildDeps;
  calls: string[];
  cleaned: string[];
}

function fixture(): Fixture {
  const calls: string[] = [];
  const cleaned: string[] = [];
  const deps: NativeBuildDeps = {
    loadRootEnvironment: () =>
      Promise.resolve({
        EXPO_PUBLIC_API_URL: API_URL,
      }),
    resolveOwnedSimulator: (requested) => {
      calls.push(`resolve ${requested ?? "unset"}`);
      if (requested && requested !== UDID)
        return Promise.reject(new Error("IOS_SIMULATOR_UDID must name the owned simulator"));
      return Promise.resolve(UDID);
    },
    requireNonemptyFile: (path) => {
      calls.push(`file ${path}`);
      return Promise.resolve();
    },
    ensureSimulator: (udid) => {
      calls.push(`simulator ${udid}`);
      return Promise.resolve();
    },
    probeBackend: (url) => {
      calls.push(`backend ${url}`);
      return Promise.resolve();
    },
    createWorkspace: (root) => {
      calls.push(`copy ${root}`);
      return Promise.resolve(TEMP);
    },
    runCommand: (command, cwd) => {
      calls.push(`run ${cwd} :: ${command.join(" ")}`);
      return Promise.resolve({ exitCode: 0 });
    },
    requireGeneratedNativeProjects: (mobileRoot) => {
      calls.push(`generated ${mobileRoot}`);
      return Promise.resolve();
    },
    isAppInstalled: (udid, bundleId) => {
      calls.push(`installed ${udid} ${bundleId}`);
      return Promise.resolve(true);
    },
    reservePort: () => Promise.resolve(18082),
    startMetro: (mobileRoot, port, env) => {
      calls.push(`metro ${mobileRoot} ${port} ${env.EXPO_PUBLIC_API_URL}`);
      return Promise.resolve({ pid: 208 });
    },
    waitForMetro: (_process, port) => {
      calls.push(`ready ${port}`);
      return Promise.resolve();
    },
    runAcceptance: (env) => {
      calls.push(
        `acceptance ${env.IOS_SIMULATOR_UDID} ${env.MAESTRO_APP_LAUNCH_URL ?? "missing-url"} ${env.EXPO_PUBLIC_API_URL}`,
      );
      return Promise.resolve({ exitCode: 0, stdout: "", stderr: "", maestroInvoked: true });
    },
    stopMetro: () => {
      cleaned.push("metro");
      return Promise.resolve();
    },
    removeWorkspace: (root) => {
      cleaned.push(root);
      return Promise.resolve();
    },
  };
  return { deps, calls, cleaned };
}

function options(deps: NativeBuildDeps, processEnv = {}): NativeBuildOptions {
  return { repoRoot: ROOT, processEnv, deps };
}

async function failure(action: Promise<unknown>): Promise<string> {
  try {
    await action;
  } catch (error) {
    return error instanceof Error ? error.message : String(error);
  }
  throw new Error("expected failure");
}

describe("runNativeBuild", () => {
  test("runs isolated native build and strict acceptance on one exact simulator", async () => {
    const { deps, calls, cleaned } = fixture();
    await runNativeBuild(options(deps));

    expect(calls).toEqual([
      "resolve unset",
      `file ${ROOT}/apps/mobile/.maestro/launch.yaml`,
      `file ${ROOT}/apps/mobile/.maestro/auth-form.yaml`,
      `simulator ${UDID}`,
      `backend ${API_URL}`,
      `copy ${ROOT}`,
      `run ${TEMP} :: bun install --frozen-lockfile`,
      `run ${TEMP}/apps/mobile :: bun expo prebuild --clean --platform all --no-install`,
      `generated ${TEMP}/apps/mobile`,
      `run ${TEMP}/apps/mobile :: bun expo run:ios --device ${UDID} --no-bundler`,
      `installed ${UDID} com.divineruin.app`,
      `metro ${TEMP}/apps/mobile 18082 ${API_URL}`,
      "ready 18082",
      `run ${TEMP}/apps/mobile :: xcrun simctl openurl ${UDID} exp+divineruin://expo-development-client/?url=http%3A%2F%2F127.0.0.1%3A18082`,
      `acceptance ${UDID} exp+divineruin://expo-development-client/?url=http%3A%2F%2F127.0.0.1%3A18082 ${API_URL}`,
    ]);
    expect(cleaned).toEqual(["metro", TEMP]);
  });

  test("accepts an explicit owned UDID and rejects a foreign one before boot", async () => {
    const { deps, calls } = fixture();
    await runNativeBuild(options(deps, { IOS_SIMULATOR_UDID: UDID }));
    expect(calls).toContain(`simulator ${UDID}`);
    const foreign = fixture();
    expect(
      await failure(runNativeBuild(options(foreign.deps, { IOS_SIMULATOR_UDID: "FOREIGN" }))),
    ).toContain("owned simulator");
    expect(foreign.calls).toEqual(["resolve FOREIGN"]);
  });

  test.each([
    [
      "root .env",
      (deps: NativeBuildDeps) => {
        deps.loadRootEnvironment = () => Promise.reject(new Error("root .env is missing"));
      },
    ],
    [
      "owned simulator",
      (deps: NativeBuildDeps) => {
        deps.resolveOwnedSimulator = () => Promise.reject(new Error("owned simulator unavailable"));
      },
    ],
    [
      "EXPO_PUBLIC_API_URL",
      (deps: NativeBuildDeps) => {
        deps.loadRootEnvironment = () => Promise.resolve({ IOS_SIMULATOR_UDID: UDID });
      },
    ],
    [
      "launch.yaml",
      (deps: NativeBuildDeps) => {
        deps.requireNonemptyFile = (path) => {
          if (path.endsWith("launch.yaml"))
            return Promise.reject(new Error("launch.yaml is empty"));
          return Promise.resolve();
        };
      },
    ],
    [
      "auth-form.yaml",
      (deps: NativeBuildDeps) => {
        deps.requireNonemptyFile = (path) => {
          if (path.endsWith("auth-form.yaml"))
            return Promise.reject(new Error("auth-form.yaml is missing"));
          return Promise.resolve();
        };
      },
    ],
    [
      "simulator",
      (deps: NativeBuildDeps) => {
        deps.ensureSimulator = () => Promise.reject(new Error("simulator boot failed"));
      },
    ],
    [
      "backend",
      (deps: NativeBuildDeps) => {
        deps.probeBackend = () => Promise.reject(new Error("backend unreachable"));
      },
    ],
  ])("fails preflight for %s before copying source", async (expected, mutate) => {
    const { deps, calls } = fixture();
    mutate(deps);
    expect(await failure(runNativeBuild(options(deps)))).toContain(expected);
    expect(calls.some((call) => call.startsWith("copy "))).toBe(false);
  });

  test.each([
    ["bun install --frozen-lockfile", "dependency install"],
    ["bun expo prebuild", "native prebuild"],
    ["bun expo run:ios", "iOS development build"],
    ["xcrun simctl openurl", "app launch"],
  ])("fails loud when %s exits nonzero", async (commandFragment, stage) => {
    const { deps, cleaned } = fixture();
    deps.runCommand = (command) =>
      Promise.resolve({ exitCode: command.join(" ").includes(commandFragment) ? 23 : 0 });
    expect(await failure(runNativeBuild(options(deps)))).toContain(`${stage} failed`);
    expect(cleaned).toContain(TEMP);
  });

  test("rejects a successful prebuild with missing generated projects", async () => {
    const { deps } = fixture();
    deps.requireGeneratedNativeProjects = () =>
      Promise.reject(new Error("generated Android project is missing"));
    expect(await failure(runNativeBuild(options(deps)))).toContain("Android");
  });

  test("rejects a successful build that did not install the app", async () => {
    const { deps } = fixture();
    deps.isAppInstalled = () => Promise.resolve(false);
    expect(await failure(runNativeBuild(options(deps)))).toContain("not installed");
  });

  test("rejects Metro readiness failure and still reaps owned resources", async () => {
    const { deps, cleaned } = fixture();
    deps.waitForMetro = () => Promise.reject(new Error("Metro exited before readiness"));
    expect(await failure(runNativeBuild(options(deps)))).toContain("Metro exited");
    expect(cleaned).toEqual(["metro", TEMP]);
  });

  test.each([
    [{ exitCode: 0, stdout: "skipped", stderr: "", maestroInvoked: false }, "not invoked"],
    [{ exitCode: 9, stdout: "", stderr: "failed", maestroInvoked: true }, "exit status 9"],
  ])("rejects incomplete acceptance: %s", async (gate, expected) => {
    const { deps } = fixture();
    deps.runAcceptance = () => Promise.resolve(gate);
    expect(await failure(runNativeBuild(options(deps)))).toContain(expected);
  });

  test("reaps the workspace even when Metro refuses to stop, keeping the first failure", async () => {
    const { deps, cleaned } = fixture();
    deps.stopMetro = () => Promise.reject(new Error("Metro would not stop"));
    deps.runAcceptance = () =>
      Promise.resolve({ exitCode: 9, stdout: "", stderr: "", maestroInvoked: true });
    expect(await failure(runNativeBuild(options(deps)))).toContain("exit status 9");
    expect(cleaned).toEqual([TEMP]);
  });

  test("fails loud when cleanup fails after an otherwise passing run", async () => {
    const { deps } = fixture();
    deps.removeWorkspace = () => Promise.reject(new Error("temporary workspace is locked"));
    expect(await failure(runNativeBuild(options(deps)))).toContain("left owned resources behind");
  });
});

describe("requiredSimulatorAction", () => {
  const sibling = { udid: "SIBLING-1", state: "Booted", isAvailable: true };

  test("boots only the requested target, never a booted sibling", () => {
    const devices = [sibling, { udid: UDID, state: "Shutdown", isAvailable: true }];
    expect(requiredSimulatorAction(devices, UDID)).toBe("boot");
    expect(requiredSimulatorAction([sibling, { ...devices[1], state: "Booted" }], UDID)).toBe(
      "ready",
    );
  });

  test.each([
    [[sibling], "unknown"],
    [[{ udid: UDID, state: "Shutdown", isAvailable: false }], "unavailable"],
    [[{ udid: UDID, state: "Creating", isAvailable: true }], "unsupported state Creating"],
  ])("refuses to act on %s", (devices, expected) => {
    expect(() => requiredSimulatorAction(devices, UDID)).toThrow(expected);
  });
});

describe("isolated native workspace", () => {
  test("excludes source native trees and secrets but keeps application source", () => {
    expect(shouldCopyPath("apps/mobile/ios/Podfile")).toBe(false);
    expect(shouldCopyPath("apps/mobile/android/settings.gradle")).toBe(false);
    expect(shouldCopyPath(".env")).toBe(false);
    expect(shouldCopyPath("apps/mobile/src/app/auth.tsx")).toBe(true);
  });
});
