import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { OwnedProcesses } from "./native-transport-processes";

interface AudioRoute {
  guestInput: string;
  guestOutput: string;
  hostInput: string;
  hostOutput: string;
  effectiveOutput: string;
  devices: { uid: string; name: string }[];
}

async function capture(scope: OwnedProcesses, cwd: string, argv: string[], timeout = 20_000) {
  const child = scope.spawn(argv, { cwd, capture: true });
  let timer: ReturnType<typeof setTimeout> | undefined;
  const deadline = new Promise<never>((_resolve, reject) => {
    timer = setTimeout(
      () => reject(new Error(`${argv[0]} audio route command timed out`)),
      timeout,
    );
  });
  try {
    const [stdout, stderr, exit] = await scope.wait(
      Promise.race([
        Promise.all([
          new Response(child.stdout).text(),
          new Response(child.stderr).text(),
          child.exited,
        ]),
        deadline,
      ]),
    );
    if (exit !== 0) throw new Error(`${argv[0]} audio route command exited ${exit}: ${stderr}`);
    return stdout.trim();
  } finally {
    clearTimeout(timer);
    await scope.stop(child);
  }
}

function requireRoute(stage: string, route: AudioRoute, before: AudioRoute, input: string) {
  console.log(`Native audio ${stage}: ${JSON.stringify(route)}`);
  if (
    route.guestInput !== input ||
    route.guestOutput !== before.guestOutput ||
    route.effectiveOutput !== before.effectiveOutput ||
    route.hostInput !== before.hostInput ||
    route.hostOutput !== before.hostOutput
  )
    throw new Error(`Native audio ${stage} input, output or host defaults differ from expected`);
}

export async function withLoopbackInput(
  scope: OwnedProcesses,
  root: string,
  udid: string,
  run: (deviceUID: string) => Promise<void>,
) {
  const directory = await mkdtemp(join(tmpdir(), "divineruin-native-audio-"));
  try {
    const helper = join(directory, "native-audio-route");
    const developerDir = await capture(scope, root, ["xcode-select", "-p"]);
    await capture(scope, root, [
      "xcrun",
      "clang",
      "-fobjc-arc",
      "-framework",
      "Foundation",
      "-framework",
      "CoreAudio",
      join(root, "apps/mobile/scripts/native-audio-route.m"),
      "-o",
      helper,
    ]);
    const route = async (owner: OwnedProcesses, uid?: string): Promise<AudioRoute> =>
      JSON.parse(
        await capture(owner, root, [helper, developerDir, udid, ...(uid ? [uid] : [])]),
      ) as AudioRoute;
    const before = await route(scope);
    console.log(`Native audio before: ${JSON.stringify(before)}`);
    const devices = before.devices.filter((device) => device.name === "BlackHole 2ch");
    const device = devices.at(0);
    if (devices.length !== 1 || !device?.uid)
      throw new Error("Native microphone requires exactly one BlackHole 2ch device");
    if ([before.guestOutput, before.effectiveOutput, before.hostOutput].includes(device.uid))
      throw new Error("Native audio output must stay off the BlackHole loopback");

    const captureJourney = async () => {
      requireRoute("during", await route(scope, device.uid), before, device.uid);
      const witness = await capture(scope, root, ["xcrun", "simctl", "io", udid, "enumerate"]);
      const input = witness.split("\n").find((line) => line.includes("Guest Audio Input ->"));
      console.log(`Native audio simctl ${udid}: ${input?.trim()}`);
      if (input?.trim() !== `Guest Audio Input -> Host Audio Device #${device.uid}`)
        throw new Error("simctl did not confirm BlackHole simulator input");
      await run(device.uid);
    };

    const [journey] = await Promise.allSettled([captureJourney()]);
    // Restore through a separate owner because the journey scope can be cancelled.
    const restoration = new OwnedProcesses();
    const restored = async () => {
      const state = await route(restoration, before.guestInput);
      requireRoute("restored", state, before, before.guestInput);
    };
    const cleanup = await Promise.allSettled([restored()]);
    cleanup.push(...(await Promise.allSettled([restoration.close()])));
    const errors = [journey, ...cleanup].flatMap((result) =>
      result.status === "rejected" ? [result.reason as unknown] : [],
    );
    if (errors.length === 1) throw errors[0];
    if (errors.length > 1)
      throw new AggregateError(errors, "Native journey and audio restoration failed");
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
}
