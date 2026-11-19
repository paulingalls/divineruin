import { join } from "node:path";
import type { OwnedProcesses } from "./native-transport-processes";

export interface StimulusRun {
  controlPath: string;
  runId: string;
  artifactDir: string;
  sequence?: boolean;
  loopbackUID?: string;
}

export function stimulateMicrophone(scope: OwnedProcesses, repoRoot: string, run: StimulusRun) {
  const child = scope.spawn(
    [
      "python3",
      join(repoRoot, "scripts/native-microphone-stimulus.py"),
      "--control",
      run.controlPath,
      "--run-id",
      run.runId,
      "--artifacts",
      run.artifactDir,
      ...(run.sequence ? ["--sequence"] : []),
      ...(run.loopbackUID ? ["--loopback-uid", run.loopbackUID] : []),
    ],
    { cwd: repoRoot },
  );
  return child;
}
