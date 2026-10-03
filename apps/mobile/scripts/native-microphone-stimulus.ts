import { join } from "node:path";
import type { OwnedProcesses } from "./native-transport-processes";

export interface StimulusRun {
  controlPath: string;
  runId: string;
  artifactDir: string;
  sequence?: boolean;
}

export async function stimulateMicrophone(
  scope: OwnedProcesses,
  repoRoot: string,
  run: StimulusRun,
): Promise<void> {
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
    ],
    { cwd: repoRoot },
  );
  const exit = await scope.wait(child.exited);
  if (exit !== 0) throw new Error(`owned microphone stimulus failed with status ${exit}`);
}
