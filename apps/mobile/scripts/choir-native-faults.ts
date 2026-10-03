import { readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";

export async function prepareChoirFault(
  repoRoot: string,
  fault: string,
): Promise<() => Promise<void>> {
  if (fault !== "deactivate-session") return () => Promise.resolve();
  const path = join(repoRoot, "apps/mobile/src/audio/sfx-player.ts");
  const original = await readFile(path, "utf8");
  const setting = "keepAudioSessionActive: true";
  if (original.split(setting).length !== 2)
    throw new Error("missing unique SFX session preservation binding");
  await writeFile(path, original.replace(setting, "keepAudioSessionActive: false"));
  return async () => {
    const current = await readFile(path, "utf8");
    if (current.split("keepAudioSessionActive: false").length !== 2)
      throw new Error("SFX fault source changed before restoration");
    await writeFile(path, current.replace("keepAudioSessionActive: false", setting));
  };
}
