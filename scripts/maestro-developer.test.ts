import { describe, expect, test } from "bun:test";
import captured from "./fixtures/simctl-devices.json";
import { lookupOwnedSimulator } from "../apps/mobile/scripts/owned-simulator";
import { type GateDeps, maestroCommand, runGate } from "./maestro-acceptance";
const ADB_ANDROID = "List of devices attached\nemulator-5554\tdevice\n";
const result =
  <T>(value: T) =>
  () =>
    Promise.resolve(value);
const OWNED_NAME = "divineruin-native-48517b6c883b";
const OWNED_UDID = "B0642F52-11B2-4F2E-9A75-502C1F290F08";
function lookup(state?: string) {
  return () =>
    lookupOwnedSimulator({
      cloneId: result("48517b6c883b"),
      run: (command) => {
        expect(command).toEqual(["xcrun", "simctl", "list", "devices", "--json"]);
        const rows = Object.values(captured.devices).flat();
        expect(rows.some((row) => row.name === OWNED_NAME && row.state === "Shutdown")).toBe(true);
        expect(rows.some((row) => row.name !== OWNED_NAME && row.state === "Booted")).toBe(true);
        const payload = structuredClone(captured);
        return Promise.resolve(
          JSON.stringify({
            devices: Object.fromEntries(
              Object.entries(payload.devices).map(([runtime, rows]) => [
                runtime,
                rows
                  .filter((row) => row.name !== OWNED_NAME || state !== undefined)
                  .map((row) => (row.name === OWNED_NAME ? { ...row, state: state! } : row)),
              ]),
            ),
          }),
        );
      },
    });
}

function deps(overrides: Partial<GateDeps> = {}): GateDeps {
  return {
    env: {},
    resolveOwnedSimulator: () =>
      Promise.reject(new Error("developer mode must not resolve/create")),
    lookupOwnedSimulator: lookup("Shutdown"),
    runAdb: result("List of devices attached\n\n"),
    probeRequestedIos: () => Promise.reject(new Error("unexpected strict probe")),
    runMaestro: result(0),
    ...overrides,
  };
}
describe("developer runGate", () => {
  test("developer lookup diagnostics report failed device probe with owned name", async () => {
    const gate = await runGate(
      deps({
        lookupOwnedSimulator: () =>
          lookupOwnedSimulator({
            cloneId: result("48517b6c883b"),
            run: () => Promise.reject(new Error("CoreSimulator is wedged")),
          }),
      }),
    );
    expect(gate.exitCode).toBe(0);
    expect(gate.stdout).toContain(OWNED_NAME);
    expect(gate.stdout).toContain("CoreSimulator is wedged");
    expect(gate.maestroInvoked).toBe(false);
  });

  test("developer skips foreign booted iOS when owned is absent or shut down", async () => {
    for (const state of [undefined, "Shutdown"]) {
      const calls: string[] = [];
      const gate = await runGate(
        deps({
          lookupOwnedSimulator: lookup(state),
          runMaestro: (device) => {
            calls.push(device);
            return Promise.resolve(0);
          },
        }),
      );
      expect(calls).toEqual([]);
      expect(gate.exitCode).toBe(0);
      expect(gate.stdout).toContain(OWNED_NAME);
      expect(gate.stdout).toContain(state ? "xcrun simctl boot " : "verify:native-build");
      if (state) expect(gate.stdout).toContain("bootstatus");
    }
  });

  test("developer targets only the booted owned iOS simulator", async () => {
    const calls: string[] = [];
    await runGate(
      deps({
        lookupOwnedSimulator: lookup("Booted"),
        runMaestro: (device, flows) => {
          calls.push(device);
          expect(maestroCommand(device, flows, "/flows")).toContain(`--device=${OWNED_UDID}`);
          return Promise.resolve(0);
        },
      }),
    );
    expect(calls).toEqual([OWNED_UDID]);
  });

  test("developer targets Android serial despite foreign booted iOS", async () => {
    for (const state of [undefined, "Shutdown"]) {
      const calls: string[] = [];
      const gate = await runGate(
        deps({
          lookupOwnedSimulator: lookup(state),
          runAdb: result(ADB_ANDROID),
          runMaestro: (device, flows) => {
            calls.push(device);
            expect(maestroCommand(device, flows, "/flows")).toContain("--device=emulator-5554");
            return Promise.resolve(0);
          },
        }),
      );
      expect(calls).toEqual(["emulator-5554"]);
      expect(gate.stdout).toContain(OWNED_NAME);
      expect(gate.stdout).toContain(state ? "xcrun simctl boot " : "verify:native-build");
    }
  });

  test("developer runs owned iOS and Android separately; both platform failures", async () => {
    for (const exits of [
      [0, 0],
      [7, 9],
      [0, 9],
      [null, 0],
    ]) {
      const calls: string[] = [];
      const gate = await runGate(
        deps({
          lookupOwnedSimulator: lookup("Booted"),
          runAdb: result(ADB_ANDROID),
          runMaestro: (device, flows) => {
            expect(flows).toEqual(["launch.yaml"]);
            expect(maestroCommand(device, flows, "/flows")).toContain(`--device=${device}`);
            calls.push(device);
            return Promise.resolve(exits[calls.length - 1] as number);
          },
        }),
      );
      expect(calls).toEqual([OWNED_UDID, "emulator-5554"]);
      expect(gate.exitCode).toBe(exits[0] === null ? 130 : (exits.find((exit) => exit) ?? 0));
      expect(gate.maestroInvoked).toBe(true);
    }
  });

  test("Android device status must be exact and selects first eligible serial", async () => {
    for (const rows of ["bad\toffline", "bad\tunauthorized", "bad\tdeviceish", ""]) {
      const calls: string[] = [];
      await runGate(
        deps({
          runAdb: result(`List of devices attached\n${rows}\n`),
          runMaestro: (device) => {
            calls.push(device);
            return Promise.resolve(0);
          },
        }),
      );
      expect(calls).toEqual([]);
      await runGate(
        deps({
          runAdb: result(`${rows}\nfirst\tdevice\nsecond\tdevice\n`),
          runMaestro: (device) => {
            calls.push(device);
            return Promise.resolve(0);
          },
        }),
      );
      expect(calls).toEqual(["first"]);
    }
  });

  test("developer lookup diagnostics fail loud for identity and malformed listings", async () => {
    for (const message of [
      "clone ID is empty",
      "Unexpected token in JSON",
      "multiple owned simulators",
      "clone ID not found",
    ]) {
      const gate = await runGate(
        deps({ lookupOwnedSimulator: () => Promise.reject(new Error(message)) }),
      );
      expect(gate.exitCode).toBe(1);
      expect(gate.stderr).toContain(message);
      expect(gate.maestroInvoked).toBe(false);
    }
  });
});
