import { expect, test } from "bun:test";
import { resolveOwnedSimulator, type OwnedSimulatorDeps } from "./owned-simulator";

const NAME = "divineruin-native-clone-one";
const RUNTIMES = {
  runtimes: [
    {
      identifier: "com.apple.CoreSimulator.SimRuntime.iOS-9-9",
      version: "9.9",
      isAvailable: true,
      supportedDeviceTypes: [
        { name: "iPhone Old", productFamily: "iPhone", identifier: "old-phone" },
      ],
    },
    {
      identifier: "com.apple.CoreSimulator.SimRuntime.iOS-27-0",
      version: "27.0",
      isAvailable: true,
      supportedDeviceTypes: [
        { name: "iPad", productFamily: "iPad", identifier: "pad" },
        { name: "iPhone 18 Pro", productFamily: "iPhone", identifier: "phone-18" },
      ],
    },
    {
      identifier: "com.apple.CoreSimulator.SimRuntime.iOS-28-0",
      version: "28.0",
      isAvailable: false,
      supportedDeviceTypes: [
        { name: "iPhone 19", productFamily: "iPhone", identifier: "phone-19" },
      ],
    },
  ],
};
const STOCK = { udid: "STOCK", name: "iPhone 18 Pro", state: "Shutdown", isAvailable: true };
const OWNED = { udid: "OWNED", name: NAME, state: "Shutdown", isAvailable: true };
function fixture(devices: readonly object[], runtimes: object = RUNTIMES) {
  const calls: string[][] = [];
  let current = devices;
  const deps: OwnedSimulatorDeps = {
    cloneId: () => Promise.resolve("clone-one"),
    run: (command) => {
      calls.push(command);
      if (command.includes("runtimes")) return Promise.resolve(JSON.stringify(runtimes));
      if (command.includes("devices"))
        return Promise.resolve(
          JSON.stringify({
            devices: { "com.apple.CoreSimulator.SimRuntime.iOS-27-0": current },
          }),
        );
      if (command.includes("create")) {
        current = [...current, OWNED];
        return Promise.resolve("OWNED\n");
      }
      throw new Error("unexpected command");
    },
  };
  return { deps, calls };
}

async function failure(action: Promise<unknown>): Promise<string> {
  try {
    await action;
  } catch (error) {
    return error instanceof Error ? error.message : String(error);
  }
  throw new Error("expected failure");
}

test("creates one clone-named iPhone on newest available iOS runtime, ignoring stock", async () => {
  const { deps, calls } = fixture([STOCK]);
  expect(await resolveOwnedSimulator(deps)).toBe("OWNED");
  expect(calls.filter((call) => call.includes("create"))).toEqual([
    ["xcrun", "simctl", "create", NAME, "phone-18", "com.apple.CoreSimulator.SimRuntime.iOS-27-0"],
  ]);
});
test("reuses the one exact-name device and accepts only its explicit UDID", async () => {
  const { deps, calls } = fixture([STOCK, OWNED]);
  expect(await resolveOwnedSimulator(deps, "OWNED")).toBe("OWNED");
  expect(calls.some((call) => call.includes("create"))).toBe(false);
  expect(await failure(resolveOwnedSimulator(deps, "STOCK"))).toMatch(/owned simulator/);
  expect(await failure(resolveOwnedSimulator(deps, " "))).toMatch(/owned simulator/);
});
test("duplicates and unusable owned devices fail before create", async () => {
  for (const [devices, expected] of [
    [[OWNED, OWNED], /multiple owned/],
    [[{ ...OWNED, isAvailable: false }], /unusable/],
    [[{ ...OWNED, state: "Creating" }], /unusable/],
  ] as const) {
    const { deps, calls } = fixture(devices);
    expect(await failure(resolveOwnedSimulator(deps))).toMatch(expected);
    expect(calls.some((call) => call.includes("create"))).toBe(false);
  }
});

test("owned-name collisions across runtime buckets fail", async () => {
  const { deps, calls } = fixture([STOCK]);
  const original = deps.run;
  deps.run = (command) =>
    command.includes("devices")
      ? Promise.resolve(
          JSON.stringify({
            devices: {
              "com.apple.CoreSimulator.SimRuntime.iOS-9-9": [OWNED],
              "com.apple.CoreSimulator.SimRuntime.iOS-27-0": [STOCK, OWNED],
            },
          }),
        )
      : original(command);
  expect(await failure(resolveOwnedSimulator(deps))).toMatch(/multiple owned/);
  expect(calls.some((call) => call.includes("create"))).toBe(false);
});
test("no available iOS runtime, empty listings, and invalid create result fail", async () => {
  const { deps } = fixture([STOCK], {
    runtimes: [{ ...RUNTIMES.runtimes[1], isAvailable: false }],
  });
  expect(await failure(resolveOwnedSimulator(deps))).toMatch(/runtime/);
  const empty = fixture([]);
  empty.deps.run = (command) =>
    Promise.resolve(
      command.includes("runtimes") ? JSON.stringify(RUNTIMES) : JSON.stringify({ devices: {} }),
    );
  expect(await failure(resolveOwnedSimulator(empty.deps))).toMatch(/devices/);
  const bad = fixture([STOCK]);
  const original = bad.deps.run;
  bad.deps.run = (command) =>
    command.includes("create") ? Promise.resolve("\n") : original(command);
  expect(await failure(resolveOwnedSimulator(bad.deps))).toMatch(/empty UDID/);
});

test("create failure and mismatched created identity fail without selecting a stock device", async () => {
  const failed = fixture([STOCK]);
  const originalFailed = failed.deps.run;
  failed.deps.run = (command) =>
    command.includes("create")
      ? Promise.reject(new Error("CoreSimulator failed"))
      : originalFailed(command);
  expect(await failure(resolveOwnedSimulator(failed.deps))).toContain("CoreSimulator failed");

  const mismatched = fixture([STOCK]);
  const originalMismatched = mismatched.deps.run;
  mismatched.deps.run = (command) =>
    command.includes("create") ? Promise.resolve("STOCK") : originalMismatched(command);
  expect(await failure(resolveOwnedSimulator(mismatched.deps))).toMatch(/does not belong/);
});
