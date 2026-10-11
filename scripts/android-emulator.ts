// Create (once) and boot the project's standard Android emulator.
//
// One lightweight AVD for everyone: API 36 (the app's compileSdk), Google APIs
// without the Play Store, 4 GB RAM. The settings are re-applied on every run,
// so hand edits in Android Studio can't drift it back to the 2 GB defaults
// that leave System UI unresponsive. Animations are switched off after boot,
// which speeds the emulator up and steadies Maestro.
//
//   bun run android:emulator
import { existsSync } from "node:fs";
import { homedir } from "node:os";

export const AVD_NAME = "divineruin-api36";
const API_LEVEL = 36;
const DEVICE_PROFILE = "medium_phone";
const BOOT_TIMEOUT_MS = 5 * 60_000;

export const AVD_SETTINGS: Record<string, string> = {
  "hw.ramSize": "4096",
  "vm.heapSize": "512",
  "hw.cpu.ncore": "4",
  "hw.gpu.enabled": "yes",
  "hw.gpu.mode": "host",
  "hw.keyboard": "yes",
  "PlayStore.enabled": "false",
  "disk.dataPartition.size": "6G",
};

const ANIMATION_SCALES = [
  "window_animation_scale",
  "transition_animation_scale",
  "animator_duration_scale",
];

export function systemImage(arch: string): string {
  const abi = { x64: "x86_64", arm64: "arm64-v8a" }[arch];
  if (!abi) throw new Error(`Unsupported host architecture: ${arch}`);
  return `system-images;android-${API_LEVEL};google_apis;${abi}`;
}

// Rewrite `key=value` lines in an AVD config.ini, appending keys it lacks.
export function applyConfig(text: string, settings: Record<string, string>): string {
  const pending = new Map(Object.entries(settings));
  const lines = text.split("\n");
  if (lines.at(-1) === "") lines.pop();
  const out = lines.map((line) => {
    const key = line.split("=")[0]!.trim();
    const value = pending.get(key);
    if (value === undefined) return line;
    pending.delete(key);
    return `${key}=${value}`;
  });
  for (const [key, value] of pending) out.push(`${key}=${value}`);
  return out.join("\n") + "\n";
}

// `emulator -list-avds` can interleave log lines; keep only bare AVD names.
export function parseAvdNames(raw: string): string[] {
  return raw
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => /^[\w.-]+$/.test(line));
}

export function sdkTools(androidHome: string) {
  return {
    sdkmanager: `${androidHome}/cmdline-tools/latest/bin/sdkmanager`,
    avdmanager: `${androidHome}/cmdline-tools/latest/bin/avdmanager`,
    emulator: `${androidHome}/emulator/emulator`,
    adb: `${androidHome}/platform-tools/adb`,
  };
}

async function run(command: string[], stdin?: string): Promise<string> {
  const child = Bun.spawn(command, {
    stdin: stdin === undefined ? "ignore" : new Blob([stdin]),
    stdout: "pipe",
    stderr: "pipe",
  });
  const [stdout, stderr, exit] = await Promise.all([
    new Response(child.stdout).text(),
    new Response(child.stderr).text(),
    child.exited,
  ]);
  if (exit !== 0)
    throw new Error(`${command[0]} exited ${exit}: ${stderr.trim() || stdout.trim()}`);
  return stdout;
}

// Serial of the running emulator for this AVD, if any.
async function runningSerial(adb: string): Promise<string | undefined> {
  const serials = [...(await run([adb, "devices"])).matchAll(/^(emulator-\d+)\s+device$/gm)].map(
    (m) => m[1]!,
  );
  for (const serial of serials) {
    const name = (await run([adb, "-s", serial, "emu", "avd", "name"])).split("\n")[0]!.trim();
    if (name === AVD_NAME) return serial;
  }
  return undefined;
}

async function waitForBoot(adb: string): Promise<string> {
  const deadline = Date.now() + BOOT_TIMEOUT_MS;
  while (Date.now() < deadline) {
    const serial = await runningSerial(adb).catch(() => undefined);
    if (serial) {
      const booted = await run([adb, "-s", serial, "shell", "getprop", "sys.boot_completed"]).catch(
        () => "",
      );
      if (booted.trim() === "1") return serial;
    }
    await Bun.sleep(2000);
  }
  throw new Error(`${AVD_NAME} did not finish booting within ${BOOT_TIMEOUT_MS / 60_000} minutes`);
}

async function main(): Promise<void> {
  const androidHome = process.env.ANDROID_HOME ?? `${homedir()}/Library/Android/sdk`;
  const tools = sdkTools(androidHome);
  if (!existsSync(tools.avdmanager)) {
    throw new Error(
      `Android SDK command-line tools not found at ${androidHome}/cmdline-tools/latest. ` +
        "Install them from Android Studio: Settings > Languages & Frameworks > Android SDK > " +
        'SDK Tools > "Android SDK Command-line Tools (latest)".',
    );
  }

  const avds = parseAvdNames(await run([tools.emulator, "-list-avds"]));
  if (!avds.includes(AVD_NAME)) {
    const image = systemImage(process.arch);
    console.log(`Installing ${image}...`);
    await run([tools.sdkmanager, "--install", image], "y\n".repeat(20));
    console.log(`Creating ${AVD_NAME}...`);
    await run(
      [tools.avdmanager, "create", "avd", "-n", AVD_NAME, "-k", image, "-d", DEVICE_PROFILE],
      "no\n",
    );
  }

  const configPath = `${homedir()}/.android/avd/${AVD_NAME}.avd/config.ini`;
  const config = Bun.file(configPath);
  await Bun.write(config, applyConfig(await config.text(), AVD_SETTINGS));

  if (await runningSerial(tools.adb).catch(() => undefined)) {
    console.log(`${AVD_NAME} is already running; settings apply on its next boot.`);
  } else {
    console.log(`Booting ${AVD_NAME}...`);
    Bun.spawn([tools.emulator, "-avd", AVD_NAME, "-no-boot-anim"], {
      stdin: "ignore",
      stdout: "ignore",
      stderr: "ignore",
    }).unref();
  }

  const serial = await waitForBoot(tools.adb);
  for (const scale of ANIMATION_SCALES) {
    await run([tools.adb, "-s", serial, "shell", "settings", "put", "global", scale, "0"]);
  }
  console.log(`${AVD_NAME} is ready on ${serial} (animations off).`);
}

if (import.meta.main) {
  main().catch((error: unknown) => {
    console.error(error instanceof Error ? error.message : String(error));
    process.exit(1);
  });
}
