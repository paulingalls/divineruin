import { describe, expect, test } from "bun:test";

import { type GateDeps, maestroCommand, runGate } from "./maestro-acceptance";

const TARGET_UDID = "A2080000-0000-0000-0000-000000000001";
const ADB_EMPTY = "List of devices attached\n\n";
const ADB_ANDROID = "List of devices attached\nemulator-5554\tdevice\n";
const SIMCTL_NONE_BOOTED =
  "== Devices ==\n-- iOS 26.5 --\n    story-208-sdk57 (TARGET) (Shutdown)\n";
const SIMCTL_SIBLINGS_BOOTED =
  "== Devices ==\n-- iOS 26.5 --\n" +
  "    story-045-legacy3-e2e (SIBLING-1) (Booted)\n" +
  "    story-058-legacy3-e2e (SIBLING-2) (Booted)\n";

const result =
  <T>(value: T) =>
  () =>
    Promise.resolve(value);
const enoent = () => Promise.reject(new Error("ENOENT"));

function deps(overrides: Partial<GateDeps> = {}): GateDeps {
  return {
    env: {},
    runSimctl: result(SIMCTL_NONE_BOOTED),
    runAdb: result(ADB_EMPTY),
    probeRequestedIos: result(false),
    runMaestro: () => Promise.resolve(0),
    ...overrides,
  };
}

describe("runGate", () => {
  test("skips a non-strict lane with no device", async () => {
    const gate = await runGate(deps());
    expect(gate).toMatchObject({ exitCode: 0, maestroInvoked: false });
    expect(gate.stdout).toMatch(/skip/i);
  });

  test("strict lane requires an explicit iOS simulator UDID", async () => {
    let probed = false;
    let invoked = false;
    const gate = await runGate(
      deps({
        env: { REQUIRE_EMULATOR: "1" },
        runSimctl: result(SIMCTL_SIBLINGS_BOOTED),
        runAdb: result(ADB_ANDROID),
        probeRequestedIos: () => {
          probed = true;
          return Promise.resolve(true);
        },
        runMaestro: () => {
          invoked = true;
          return Promise.resolve(0);
        },
      }),
    );
    expect(gate.exitCode).toBe(1);
    expect(gate.stderr).toMatch(/IOS_SIMULATOR_UDID/);
    expect(probed).toBe(false);
    expect(invoked).toBe(false);
  });

  test("booted siblings and Android cannot satisfy an unavailable requested target", async () => {
    let invoked = false;
    const gate = await runGate(
      deps({
        env: { REQUIRE_EMULATOR: "1", IOS_SIMULATOR_UDID: TARGET_UDID },
        runSimctl: result(SIMCTL_SIBLINGS_BOOTED),
        runAdb: result(ADB_ANDROID),
        probeRequestedIos: (udid) => {
          expect(udid).toBe(TARGET_UDID);
          return Promise.resolve(false);
        },
        runMaestro: () => {
          invoked = true;
          return Promise.resolve(0);
        },
      }),
    );
    expect(gate.exitCode).toBe(1);
    expect(gate.stderr).toContain(TARGET_UDID);
    expect(invoked).toBe(false);
  });

  test("passes the exact requested target and both strict flows to Maestro", async () => {
    const calls: Array<{ udid: string | undefined; flows: string[] }> = [];
    const gate = await runGate(
      deps({
        env: {
          REQUIRE_EMULATOR: "1",
          REQUIRE_BACKEND: "1",
          IOS_SIMULATOR_UDID: TARGET_UDID,
        },
        probeRequestedIos: result(true),
        runMaestro: (udid, flows) => {
          calls.push({ udid, flows });
          return Promise.resolve(0);
        },
      }),
    );
    expect(gate).toMatchObject({ exitCode: 0, maestroInvoked: true });
    expect(calls).toEqual([{ udid: TARGET_UDID, flows: ["launch.yaml", "auth-form.yaml"] }]);
  });

  test("passes the requested app launch URL to Maestro", () => {
    const command = maestroCommand(
      TARGET_UDID,
      ["launch.yaml"],
      "/repo/apps/mobile/.maestro",
      "exp+divineruin://expo-development-client/?url=http%3A%2F%2F127.0.0.1%3A18082",
    );
    expect(command).toContain("-e");
    expect(command).toContain(
      "APP_LAUNCH_URL=exp+divineruin://expo-development-client/?url=http%3A%2F%2F127.0.0.1%3A18082",
    );
  });

  test("fails rather than invoke Maestro when the selected flow set is empty", async () => {
    let invoked = false;
    const gate = await runGate(
      deps({
        env: { REQUIRE_EMULATOR: "1", IOS_SIMULATOR_UDID: TARGET_UDID },
        probeRequestedIos: result(true),
        flowNames: { offlineSafe: [], backendRequired: [] },
        runMaestro: () => {
          invoked = true;
          return Promise.resolve(0);
        },
      }),
    );
    expect(gate.exitCode).toBe(1);
    expect(gate.stderr).toMatch(/flow/i);
    expect(invoked).toBe(false);
  });

  test("keeps broad device detection for the non-strict developer lane", async () => {
    for (const available of [
      { runSimctl: result(SIMCTL_SIBLINGS_BOOTED), runAdb: result(ADB_EMPTY) },
      { runSimctl: result(SIMCTL_NONE_BOOTED), runAdb: result(ADB_ANDROID) },
    ]) {
      const gate = await runGate(deps(available));
      expect(gate).toMatchObject({ exitCode: 0, maestroInvoked: true });
    }
  });

  test("defaults to launch only and adds auth when the backend is required", async () => {
    const seen: string[][] = [];
    for (const env of [{}, { REQUIRE_BACKEND: "1" }]) {
      await runGate(
        deps({
          env,
          runSimctl: result(SIMCTL_SIBLINGS_BOOTED),
          runMaestro: (_udid, flows) => {
            seen.push(flows);
            return Promise.resolve(0);
          },
        }),
      );
    }
    expect(seen).toEqual([["launch.yaml"], ["launch.yaml", "auth-form.yaml"]]);
  });

  test("propagates Maestro failures and signal-like null exits", async () => {
    for (const exit of [7, null]) {
      const gate = await runGate(
        deps({
          runSimctl: result(SIMCTL_SIBLINGS_BOOTED),
          runMaestro: () => Promise.resolve(exit) as unknown as Promise<number>,
        }),
      );
      expect(gate.exitCode).not.toBe(0);
      expect(gate.maestroInvoked).toBe(true);
    }
  });

  test("treats missing detector tools as absent in the non-strict lane", async () => {
    const gate = await runGate(deps({ runSimctl: enoent, runAdb: enoent }));
    expect(gate).toMatchObject({ exitCode: 0, maestroInvoked: false });
  });

  test("surfaces requested-device probe diagnostics without invoking Maestro", async () => {
    const gate = await runGate(
      deps({
        env: { REQUIRE_EMULATOR: "1", IOS_SIMULATOR_UDID: TARGET_UDID },
        probeRequestedIos: () => Promise.reject(new Error("simctl service unavailable")),
      }),
    );
    expect(gate.exitCode).toBe(1);
    expect(gate.stderr).toMatch(/simctl service unavailable/);
    expect(gate.maestroInvoked).toBe(false);
  });
});
