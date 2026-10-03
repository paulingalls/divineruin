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
  microphone_frames?: number;
  peak_amplitude?: number;
  authenticated_turns?: { identity: string; text: string; generation: number }[];
  commands?: string[];
  receipts?: { name: string; is_error: boolean; output: string }[];
}

export function assertMicrophoneTurns(raw: unknown, identity: string): void {
  const result = raw as MicrophoneTurns;
  if (!(result.microphone_frames! > 0) || !(result.peak_amplitude! >= 500))
    throw new Error("native microphone delivered no voiced stimulus");
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
      probePath: "apps/agent/choir_capstone_probe.py",
      validateResult: (raw, runId, fault) => {
        const result = validateScenarioResult(raw, runId, fault);
        assertMicrophoneTurns(
          (raw as { microphone_turns?: unknown }).microphone_turns,
          result.mobile_identity,
        );
        return result;
      },
    });
  });
}

if (import.meta.main) {
  await verifyChoirMicrophone(resolve(import.meta.dir, "../../.."));
  throw new Error(
    "Microphone prerequisite alone cannot certify the unfinished Choir encounter capstone",
  );
}
