// Tests for the Maestro REQUIRE_EMULATOR gate.
//
// The gate is a pure function `runGate({env, runSimctl, runAdb, runMaestro})`.
// Tests inject fakes so they are hermetic — no real Maestro / Xcode / Android
// SDK on the test runner. Mirrors the REQUIRE_DOCKER pattern in
// apps/agent/tests/acceptance/conftest.py: absent prerequisites skip cleanly
// (exit 0) by default; hard-fail (exit 1) when REQUIRE_EMULATOR=1.

import { test, expect, describe } from "bun:test";

import { runGate } from "./maestro-acceptance";

// adb's "List of devices attached" header word "devices" must NOT match the
// device-presence regex, or every absent-device run is treated as present.
const ADB_EMPTY = "List of devices attached\n\n";
const ADB_ANDROID = "List of devices attached\nemulator-5554\tdevice\n";
const SIMCTL_NONE_BOOTED =
  "== Devices ==\n-- iOS 17.0 --\n    iPhone 15 (UUID) (Shutdown)\n";
const SIMCTL_BOOTED =
  "== Devices ==\n-- iOS 17.0 --\n    iPhone 15 (UUID) (Booted)\n";

const constResult = <T>(v: T) => () => Promise.resolve(v);
const enoent = () => Promise.reject(new Error("ENOENT"));
// runMaestro now takes flows; ignore them in fakes that only care about the
// resolved exit code. Cast through unknown so a Promise<null> (signal-kill
// simulation) can flow through the number-typed signature without `any`.
const maestroExit = (code: number | null) =>
  ((): Promise<number> => Promise.resolve(code) as unknown as Promise<number>);

describe("runGate", () => {
  test("exits 0 with skip message when no device and REQUIRE_EMULATOR unset", async () => {
    const r = await runGate({
      env: {},
      runSimctl: constResult(SIMCTL_NONE_BOOTED),
      runAdb: constResult(ADB_EMPTY),
      runMaestro: constResult(0),
    });
    expect(r.exitCode).toBe(0);
    expect(r.stdout).toMatch(/skip/i);
    expect(r.maestroInvoked).toBe(false);
  });

  test("exits 1 when no device and REQUIRE_EMULATOR=1", async () => {
    const r = await runGate({
      env: { REQUIRE_EMULATOR: "1" },
      runSimctl: constResult(SIMCTL_NONE_BOOTED),
      runAdb: constResult(ADB_EMPTY),
      runMaestro: constResult(0),
    });
    expect(r.exitCode).toBe(1);
    expect(r.stderr).toMatch(/xcrun simctl|adb devices|REQUIRE_EMULATOR/);
    expect(r.maestroInvoked).toBe(false);
  });

  test("invokes maestro when an iOS simulator is Booted", async () => {
    const r = await runGate({
      env: {},
      runSimctl: constResult(SIMCTL_BOOTED),
      runAdb: constResult(ADB_EMPTY),
      runMaestro: constResult(0),
    });
    expect(r.maestroInvoked).toBe(true);
    expect(r.exitCode).toBe(0);
  });

  test("invokes maestro when adb shows an attached device", async () => {
    const r = await runGate({
      env: {},
      runSimctl: constResult(SIMCTL_NONE_BOOTED),
      runAdb: constResult(ADB_ANDROID),
      runMaestro: constResult(0),
    });
    expect(r.maestroInvoked).toBe(true);
    expect(r.exitCode).toBe(0);
  });

  test("propagates maestro exit code on failure", async () => {
    const r = await runGate({
      env: {},
      runSimctl: constResult(SIMCTL_BOOTED),
      runAdb: constResult(ADB_EMPTY),
      runMaestro: constResult(7),
    });
    expect(r.maestroInvoked).toBe(true);
    expect(r.exitCode).toBe(7);
  });

  test("treats ENOENT on detection commands as device absent", async () => {
    // Linux dev machines have neither xcrun nor adb — Bun.spawn throws ENOENT.
    // Detection should treat this as 'no device' rather than crashing the gate.
    const r = await runGate({
      env: {},
      runSimctl: enoent,
      runAdb: enoent,
      runMaestro: constResult(0),
    });
    expect(r.exitCode).toBe(0);
    expect(r.stdout).toMatch(/skip/i);
    expect(r.maestroInvoked).toBe(false);
  });

  test("hard-fails with REQUIRE_EMULATOR=1 when detection tools are missing", async () => {
    const r = await runGate({
      env: { REQUIRE_EMULATOR: "1" },
      runSimctl: enoent,
      runAdb: enoent,
      runMaestro: constResult(0),
    });
    expect(r.exitCode).toBe(1);
    expect(r.maestroInvoked).toBe(false);
  });

  test("coerces null exit (signal-killed maestro) to non-zero", async () => {
    // Bun.spawn .exited resolves to null when the child terminates via signal
    // (e.g. SIGINT). Coercing to 0 via process.exit(null) would mask a Ctrl-C
    // mid-run as a passing acceptance lane — see code-review finding 2.
    const r = await runGate({
      env: {},
      runSimctl: constResult(SIMCTL_BOOTED),
      runAdb: constResult(ADB_EMPTY),
      runMaestro: maestroExit(null),
    });
    expect(r.maestroInvoked).toBe(true);
    expect(r.exitCode).not.toBe(0);
  });

  test("REQUIRE_BACKEND=1 adds backend-required flows; default omits them", async () => {
    // Default: only offline-safe flows (auth-form needs apps/server, so it's
    // gated behind REQUIRE_BACKEND to honor the skip-cleanly philosophy.)
    const seen: string[][] = [];
    const capture = (flows: string[]): Promise<number> => {
      seen.push(flows);
      return Promise.resolve(0);
    };

    await runGate({
      env: {},
      runSimctl: constResult(SIMCTL_BOOTED),
      runAdb: constResult(ADB_EMPTY),
      runMaestro: capture,
    });
    await runGate({
      env: { REQUIRE_BACKEND: "1" },
      runSimctl: constResult(SIMCTL_BOOTED),
      runAdb: constResult(ADB_EMPTY),
      runMaestro: capture,
    });

    expect(seen[0]).toEqual(["launch.yaml"]);
    expect(seen[1]).toContain("launch.yaml");
    expect(seen[1]).toContain("auth-form.yaml");
  });

  test("surfaces detection-tool diagnostic under REQUIRE_EMULATOR=1", async () => {
    // Wedged adb daemon exits non-zero with a real error; spawnText throws
    // rather than returning empty output, so the gate can distinguish 'tool
    // broken' from 'no device' instead of blaming the user generically.
    const adbBroken = () =>
      Promise.reject(new Error("adb exited 1: daemon not running"));
    const r = await runGate({
      env: { REQUIRE_EMULATOR: "1" },
      runSimctl: enoent,
      runAdb: adbBroken,
      runMaestro: constResult(0),
    });
    expect(r.exitCode).toBe(1);
    expect(r.stderr).toMatch(/adb devices probe failed/);
    expect(r.stderr).toMatch(/daemon not running/);
  });
});
