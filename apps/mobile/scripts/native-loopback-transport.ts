import { join } from "node:path";
import { assertMicrophoneMarker } from "../src/audio/native-transport-observation";
import { stimulateMicrophone } from "./native-microphone-stimulus";
import { validateScenarioResult, type NativeTransportDeps } from "./verify-native-transport";

export function loopbackTransport(deviceUID: string, results: string) {
  return {
    acousticMarker: true,
    stimulateMicrophone: (scope, root, run) =>
      stimulateMicrophone(scope, root, { ...run, loopbackUID: deviceUID }),
    validateResult: async (raw, runId, fault) => {
      const result = validateScenarioResult(raw, runId, fault);
      assertMicrophoneMarker(result);
      await requireLoopbackPlayback(results, runId, deviceUID);
      return result;
    },
  } satisfies Pick<
    NativeTransportDeps,
    "acousticMarker" | "stimulateMicrophone" | "validateResult"
  >;
}

async function requireLoopbackPlayback(results: string, runId: string, deviceUID: string) {
  const receipt = (await Bun.file(join(results, runId, "stimulus-playback.json")).json()) as {
    run_id?: string;
    device_uid?: string;
    device_index?: number;
    playback_count?: number;
    played_turns?: number[];
    waveform?: { sample_rate?: number; channels?: number; pcm_bits?: number };
  };
  if (
    receipt.run_id !== runId ||
    receipt.device_uid !== deviceUID ||
    typeof receipt.device_index !== "number" ||
    !Number.isInteger(receipt.device_index) ||
    receipt.device_index < 0 ||
    receipt.playback_count !== 1 ||
    JSON.stringify(receipt.played_turns) !== "[1]" ||
    receipt.waveform?.sample_rate !== 48000 ||
    receipt.waveform.channels !== 1 ||
    receipt.waveform.pcm_bits !== 16
  )
    throw new Error(
      "Native transport requires one current-run playback into the routed BlackHole device",
    );
}
