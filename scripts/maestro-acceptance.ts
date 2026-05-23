// Maestro acceptance lane gate.
//
// Mirrors the REQUIRE_DOCKER pattern in apps/agent/tests/acceptance/conftest.py
// (lines 77-83) for the mobile native lane: skip-by-default when no booted iOS
// simulator or attached Android device is present, hard-fail when
// REQUIRE_EMULATOR=1. Without this gate, `bun run test:e2e:mobile` either
// errors confusingly on headless dev machines or stalls /xp-free-close.
//
// Core logic is a pure async function `runGate({env, runSimctl, runAdb,
// runMaestro})` so unit tests inject fakes; the CLI bottom wires the real
// Bun.spawn invocations.

export interface GateDeps {
  env: Record<string, string | undefined>;
  runSimctl: () => Promise<string>;
  runAdb: () => Promise<string>;
  runMaestro: (flows: string[]) => Promise<number>;
}

// Flows that can run against a launched-but-offline app (no apps/server).
const OFFLINE_SAFE_FLOWS = ["launch.yaml"];
// Flows that require apps/server reachable from the device — gated by
// REQUIRE_BACKEND=1 so default skip-cleanly is preserved.
const BACKEND_REQUIRED_FLOWS = ["auth-form.yaml"];

export interface GateResult {
  exitCode: number;
  stdout: string;
  stderr: string;
  maestroInvoked: boolean;
}

const SIMCTL_BOOTED_PATTERN = /\(Booted\)/;
// "List of devices attached" header word "devices" must NOT match — match only
// rows like `emulator-5554  device` or `1234abcd  device`. The trailing-tab
// anchor distinguishes the column-aligned status from the header word.
const ADB_DEVICE_LINE = /^\S+\s+device\b/m;

// Detection returns the device-present boolean plus an optional diagnostic
// when the underlying probe failed for a reason other than "tool missing".
// REQUIRE_EMULATOR=1 surfaces these diagnostics so a wedged adb daemon or a
// broken simctl install doesn't masquerade as "no device, boot one".
interface DetectionResult {
  present: boolean;
  diagnostic?: string;
}

function isToolMissing(err: unknown): boolean {
  // Bun.spawn rejects with an ENOENT-style error when the binary isn't on PATH.
  const msg = err instanceof Error ? err.message : String(err);
  return /ENOENT|not found|No such file/i.test(msg);
}

async function detectIosBooted(deps: GateDeps): Promise<DetectionResult> {
  try {
    const out = await deps.runSimctl();
    return { present: SIMCTL_BOOTED_PATTERN.test(out) };
  } catch (err) {
    if (isToolMissing(err)) return { present: false };
    return {
      present: false,
      diagnostic: `xcrun simctl probe failed: ${err instanceof Error ? err.message : String(err)}`,
    };
  }
}

async function detectAndroidAttached(deps: GateDeps): Promise<DetectionResult> {
  try {
    const out = await deps.runAdb();
    return { present: ADB_DEVICE_LINE.test(out) };
  } catch (err) {
    if (isToolMissing(err)) return { present: false };
    return {
      present: false,
      diagnostic: `adb devices probe failed: ${err instanceof Error ? err.message : String(err)}`,
    };
  }
}

export async function runGate(deps: GateDeps): Promise<GateResult> {
  const requireEmulator = deps.env.REQUIRE_EMULATOR === "1";
  const [ios, android] = await Promise.all([
    detectIosBooted(deps),
    detectAndroidAttached(deps),
  ]);

  if (!ios.present && !android.present) {
    const diagnostics = [ios.diagnostic, android.diagnostic].filter(
      (d): d is string => Boolean(d),
    );
    if (requireEmulator) {
      const base =
        "REQUIRE_EMULATOR=1 but no booted iOS simulator or attached " +
        "Android device was found. Boot one (e.g. `xcrun simctl boot " +
        "'iPhone 15'` or `adb devices`) and rerun.";
      const stderr =
        diagnostics.length > 0
          ? `${base}\nDetection diagnostics:\n  - ${diagnostics.join("\n  - ")}`
          : base;
      return { exitCode: 1, stdout: "", stderr, maestroInvoked: false };
    }
    return {
      exitCode: 0,
      stdout:
        "Maestro acceptance: skipped (no booted iOS simulator or attached " +
        "Android device). Set REQUIRE_EMULATOR=1 to hard-fail.",
      stderr: "",
      maestroInvoked: false,
    };
  }

  const flows = [...OFFLINE_SAFE_FLOWS];
  if (deps.env.REQUIRE_BACKEND === "1") {
    flows.push(...BACKEND_REQUIRED_FLOWS);
  }

  const exit = await deps.runMaestro(flows);
  // Bun.spawn .exited can resolve to null on signal termination; coerce to a
  // non-zero exit so CI / pre-push doesn't read a Ctrl-C'd run as success.
  const exitCode = typeof exit === "number" ? exit : 130;
  return { exitCode, stdout: "", stderr: "", maestroInvoked: true };
}

// Bun.spawn helper — returns stdout as text. Drains stderr concurrently so a
// chatty child (e.g. xcrun simctl on a host with many runtimes emitting
// CoreSimulator warnings) can't deadlock on a full ~64KB pipe buffer; mirrors
// the stdout+stderr drain pattern in scripts/test-all.ts. Throws on non-zero
// exit so a broken adb daemon doesn't masquerade as 'no device'.
async function spawnText(cmd: string[]): Promise<string> {
  const proc = Bun.spawn(cmd, { stdout: "pipe", stderr: "pipe" });
  const [stdout, stderr, exit] = await Promise.all([
    new Response(proc.stdout).text(),
    new Response(proc.stderr).text(),
    proc.exited,
  ]);
  if (exit !== 0) {
    throw new Error(`${cmd[0]} exited ${String(exit)}: ${stderr.trim()}`);
  }
  return stdout;
}

async function spawnInherit(cmd: string[], cwd: string): Promise<number> {
  const proc = Bun.spawn(cmd, { stdout: "inherit", stderr: "inherit", cwd });
  const exit = await proc.exited;
  // Coerce null (signal termination) so callers always see a numeric code.
  return typeof exit === "number" ? exit : 130;
}

// CLI entrypoint — invoked when this file is run directly (Bun.main check).
// Wires the pure runGate to the actual detection + Maestro commands.
if (import.meta.main) {
  const repoRoot = new URL("..", import.meta.url).pathname;
  const mobileDir = `${repoRoot}apps/mobile`;
  const maestroDir = `${mobileDir}/.maestro`;

  const result = await runGate({
    env: process.env,
    runSimctl: () => spawnText(["xcrun", "simctl", "list", "devices"]),
    runAdb: () => spawnText(["adb", "devices"]),
    // Pin cwd to apps/mobile so any future cwd-relative maestro output
    // (junit reports, screenshots) lands in a predictable directory
    // regardless of where `bun run test:e2e:mobile` was invoked from.
    runMaestro: (flows) =>
      spawnInherit(
        ["maestro", "test", ...flows.map((f) => `${maestroDir}/${f}`)],
        mobileDir,
      ),
  });
  if (result.stdout) console.log(result.stdout);
  if (result.stderr) console.error(result.stderr);
  process.exit(result.exitCode);
}
