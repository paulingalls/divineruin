import { resolve } from "node:path";
import { mediaDir } from "./media-dir.ts";

export const TRACKED_IMAGE_DIR = resolve(import.meta.dir, "../../../assets/images");

export function portraitDir(): string {
  return `${mediaDir()}/portraits`;
}

export async function findAssetPath(assetId: string): Promise<string | undefined> {
  for (const directory of [portraitDir(), TRACKED_IMAGE_DIR]) {
    const path = `${directory}/${assetId}.png`;
    if (await Bun.file(path).exists()) return path;
  }
}
