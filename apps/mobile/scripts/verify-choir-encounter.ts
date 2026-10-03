import { prepareChoirFault } from "./choir-native-faults";
import { stimulateMicrophone } from "./native-microphone-stimulus";
import { resolve } from "node:path";
import { withOwnedProcesses } from "./native-transport-processes";
import { createRealOwnedSimulatorDeps, resolveOwnedSimulator } from "./owned-simulator";
import {
  buildCurrentNativeApp,
  requireTargetSimulator,
  runNativeTransport,
  validateScenarioResult,
} from "./verify-native-transport";

interface MicrophoneTurns {
  acoustic_sources?: { run_id: string; turn: number; source: string }[];
  microphone_frames?: number;
  peak_amplitude?: number;
  authenticated_turns?: { identity: string; text: string; generation: number }[];
  commands?: string[];
  receipts?: { name: string; is_error: boolean; output: string }[];
}

export function assertMicrophoneTurns(raw: unknown, identity: string, runId: string): void {
  const result = raw as MicrophoneTurns;
  if (!(result.microphone_frames! > 0) || !(result.peak_amplitude! >= 500))
    throw new Error("native microphone delivered no voiced stimulus");
  const sources = result.acoustic_sources;
  if (
    sources?.length !== 2 ||
    sources.some(
      (receipt, index) =>
        receipt.run_id !== runId ||
        receipt.turn !== index + 1 ||
        receipt.source !== "owned-acoustic-marker",
    )
  )
    throw new Error("missing owned acoustic source for native commands");
  const turns = result.authenticated_turns;
  if (turns?.length !== 2)
    throw new Error("missing separate authenticated native microphone turns");
  if (turns.some((turn) => turn.identity !== identity || !(turn.generation > 0)))
    throw new Error("native microphone turns are not authenticated to this player");
  if (turns[0].text !== "capstone turn 1" || turns[1].text !== "capstone turn 2")
    throw new Error("native microphone turns are not distinct");
  if (JSON.stringify(result.commands) !== JSON.stringify(["declare_phase", "check"]))
    throw new Error("native microphone commands did not execute public dispatch");
  const receipts = result.receipts;
  if (receipts?.length !== 2) throw new Error("missing native microphone command receipts");
  if (
    receipts[0].name !== "declare_phase" ||
    !receipts[0].is_error ||
    !receipts[0].output.includes("silenced")
  )
    throw new Error("missing actual silenced refusal");
  if (receipts[1].name !== "check" || receipts[1].is_error || !receipts[1].output.trim())
    throw new Error("missing subsequent legal command receipt");
}

export const CHOIR_STEPS = [
  "entry",
  "cast-aura",
  "aura-break",
  "search",
  "redirect",
  "silence",
  "refusal",
  "silenced-command",
  "deafened",
  "deafened-command",
  "expiry",
  "destruction",
  "replay",
];

export function assertChoirEncounter(raw: unknown, identity: string, runId: string): void {
  const result = raw as MicrophoneTurns & {
    checkpoints?: Record<
      string,
      {
        phase?: string;
        owner?: string;
        core_hp?: number;
        player_hp?: number;
        xp?: number;
        refused?: boolean;
      }
    >;
    native_checkpoints?: Record<
      string,
      {
        player?: string;
        events?: { type?: string }[];
        combat_active?: boolean;
        combat?: {
          combatants: { id: string; hpCurrent: number; conditions: { type: string }[] }[];
        } | null;
        xp?: number;
        resonance?: string;
      }
    >;
  };
  const sources = result.acoustic_sources;
  const turns = result.authenticated_turns;
  const receipts = result.receipts;
  if (
    !sources ||
    sources.length <= 2 ||
    turns?.length !== sources.length ||
    receipts?.length !== sources.length ||
    result.commands?.length !== sources.length
  )
    throw new Error("missing complete authenticated Choir command receipts");
  for (let index = 0; index < sources.length; index++) {
    if (
      sources[index].run_id !== runId ||
      sources[index].turn !== index + 1 ||
      sources[index].source !== "owned-acoustic-marker" ||
      turns[index].identity !== identity ||
      turns[index].generation <= 0 ||
      turns[index].text !== `capstone turn ${index + 1}` ||
      receipts[index].name !== result.commands[index] ||
      !receipts[index].output.trim()
    )
      throw new Error("uncorrelated native Choir command receipt");
  }
  for (const field of ["checkpoints", "native_checkpoints"] as const) {
    const checkpoints = result[field];
    if (
      !checkpoints ||
      JSON.stringify(Object.keys(checkpoints).sort()) !== JSON.stringify([...CHOIR_STEPS].sort())
    )
      throw new Error("missing named Choir encounter checkpoint");
    for (const step of CHOIR_STEPS) {
      const checkpoint: unknown = checkpoints[step];
      if (!checkpoint || typeof checkpoint !== "object" || Object.keys(checkpoint).length === 0)
        throw new Error("empty Choir encounter checkpoint");
    }
  }
  for (const step of CHOIR_STEPS) {
    const checkpoint = result.native_checkpoints![step];
    if (checkpoint.player !== identity || !checkpoint.events?.length)
      throw new Error("missing actual native receiver checkpoint");
    const expected = result.checkpoints![step];
    if (step === "destruction" || step === "replay") {
      if (
        checkpoint.combat_active !== false ||
        checkpoint.combat !== null ||
        checkpoint.xp !== result.checkpoints!.destruction.xp ||
        !checkpoint.events.some((event) => event.type === "combat_ended")
      )
        throw new Error("native receiver retained destroyed combat or missed award");
      if (
        step === "destruction" &&
        (expected.phase !== "destroyed" || !expected.owner || !(expected.xp! > 0))
      )
        throw new Error("missing committed destruction");
      if (step === "replay" && expected.refused !== true) throw new Error("missing replay refusal");
    } else {
      const actors = checkpoint.combat?.combatants;
      if (
        checkpoint.combat_active !== true ||
        !actors?.length ||
        !expected.owner ||
        !["search", "exposed"].includes(expected.phase ?? "") ||
        actors.find((actor) => actor.id === identity)?.hpCurrent !== expected.player_hp ||
        actors.find((actor) => actor.id === expected.owner)?.hpCurrent !== expected.core_hp ||
        !Number.isFinite(expected.player_hp) ||
        !Number.isFinite(expected.core_hp)
      )
        throw new Error("native receiver differs from committed Choir state");
      if (
        step === "deafened" &&
        !actors
          .find((actor) => actor.id === identity)
          ?.conditions.some((condition) => condition.type === "deafened")
      )
        throw new Error("native receiver missed Deafened");
      if (
        step === "cast-aura" &&
        !["stable", "flickering", "overreach"].includes(checkpoint.resonance ?? "")
      )
        throw new Error("native receiver missed Resonance");
    }
  }
  if (
    !receipts.some(
      (receipt) =>
        receipt.name === "declare_phase" && receipt.is_error && receipt.output.includes("silenced"),
    ) ||
    !receipts.some((receipt) => receipt.name === "check" && !receipt.is_error)
  )
    throw new Error("missing Choir refusal and legal commands");
}

export const CHOIR_FAULTS = [
  "deactivate-session",
  "drop-gameplay",
  "bypass-receiver",
  "skip-encounter",
  "withhold-microphone",
  "dm-tone-only",
  "unrelated-burst",
];

export function assertChoirFault(
  raw: unknown,
  identity: string,
  runId: string,
  fault: string,
): void {
  const result = raw as MicrophoneTurns & {
    fault?: string;
    fault_failure?: string;
    checkpoints?: Record<string, unknown>;
  };
  const diagnostics: Record<string, string> = {
    "deactivate-session": "missing separate authenticated turn 2 and gameplay receipt",
    "drop-gameplay": "missing Choir gameplay delivery: combat_started",
    "bypass-receiver": "native receiver did not apply combat",
    "skip-encounter": "missing named Choir encounter checkpoint",
    "withhold-microphone": "missing separate authenticated turn 1 and gameplay receipt",
    "dm-tone-only": "missing separate authenticated turn 1 and gameplay receipt",
    "unrelated-burst": "missing separate authenticated turn 1 and gameplay receipt",
  };
  if (
    !CHOIR_FAULTS.includes(fault) ||
    result.fault !== fault ||
    result.fault_failure !== diagnostics[fault] ||
    !(result.microphone_frames! >= 5)
  )
    throw new Error("wrong native Choir fault diagnostic");
  const count = ["withhold-microphone", "dm-tone-only", "unrelated-burst"].includes(fault) ? 0 : 1;
  if (
    result.acoustic_sources?.length !== count ||
    result.authenticated_turns?.length !== count ||
    result.receipts?.length !== count ||
    result.commands?.length !== count
  )
    throw new Error("native fault lost unaffected command evidence");
  if (
    count &&
    (result.acoustic_sources[0].run_id !== runId ||
      result.authenticated_turns[0].identity !== identity ||
      result.authenticated_turns[0].generation <= 0 ||
      result.receipts[0].name !== "enter_mode" ||
      result.receipts[0].is_error)
  )
    throw new Error("native fault did not reach actual public encounter entry");
}

export async function verifyChoirMicrophone(repoRoot: string): Promise<void> {
  await withOwnedProcesses(async (scope) => {
    const reservation = Bun.serve({ hostname: "127.0.0.1", port: 0, fetch: () => new Response() });
    const port = reservation.port!;
    await reservation.stop(true);
    const origin = `http://127.0.0.1:${port}`;
    const env = Object.fromEntries(
      Object.entries({
        ...process.env,
        PORT: String(port),
        EXPO_PUBLIC_API_URL: origin,
        JWT_SECRET: "ab".repeat(32),
        NODE_ENV: "development",
        EMAIL_TRANSPORT: "mock",
        RATE_LIMIT_BYPASS: "1",
        CI: "1",
      }),
    );
    const backend = scope.spawn(["bun", "apps/server/src/index.ts"], { cwd: repoRoot, env });
    let backendExit: number | undefined;
    void backend.exited.then((code) => {
      backendExit = code;
    });
    const deadline = Date.now() + 90000;
    let ready = false;
    while (!ready && Date.now() < deadline) {
      scope.signal.throwIfAborted();
      if (backendExit !== undefined)
        throw new Error(`owned backend exited with status ${backendExit}`);
      try {
        ready =
          (await fetch(`${origin}/api/inventory`, { signal: AbortSignal.timeout(1000) })).status ===
          401;
      } catch {
        scope.signal.throwIfAborted();
      }
      if (!ready) await scope.wait(Bun.sleep(200));
    }
    if (!ready) throw new Error("owned native backend did not become ready");
    const owned = createRealOwnedSimulatorDeps(repoRoot);
    await runNativeTransport(repoRoot, env, "none", {
      resolveOwned: (requested) => resolveOwnedSimulator(owned, requested),
      prepareNativeApp: buildCurrentNativeApp,
      requireTarget: requireTargetSimulator,
      choir: true,
      prepareScenario: prepareChoirFault,
      choirFaults: ["none", ...CHOIR_FAULTS],
      stimulateMicrophone: (scope, root, run) =>
        stimulateMicrophone(scope, root, { ...run, sequence: true }),
      probePath: "apps/agent/choir_capstone_probe.py",
      validateResult: (raw, runId, fault) => {
        const result = validateScenarioResult(raw, runId, fault);
        const turns = (raw as { microphone_turns?: { fault?: string } }).microphone_turns;
        if (turns?.fault === "none") assertChoirEncounter(turns, result.mobile_identity, runId);
        else assertChoirFault(turns, result.mobile_identity, runId, turns?.fault ?? "");
        return result;
      },
    });
  });
}

if (import.meta.main) {
  await verifyChoirMicrophone(resolve(import.meta.dir, "../../.."));
}
