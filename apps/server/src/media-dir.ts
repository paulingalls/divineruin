import { isAbsolute, resolve } from "node:path";
import { mkdir, open, unlink } from "node:fs/promises";

export function mediaDir(): string {
  const configured = Bun.env.MEDIA_DIR?.trim();
  if (!configured) return resolve(`${import.meta.dir}/../../../assets/generated`);
  // Each process would resolve it against its own cwd: narration written to one tree, served from another.
  if (!isAbsolute(configured)) throw new Error(`MEDIA_DIR must be an absolute path: ${configured}`);
  return resolve(configured);
}

export async function validateMediaDir(): Promise<void> {
  const production = Bun.env.NODE_ENV === "production";
  if (production && !Bun.env.MEDIA_DIR?.trim()) {
    throw new Error("MEDIA_DIR is required in production");
  }
  const root = mediaDir();
  try {
    if (!production) await mkdir(root, { recursive: true });
    for (const directory of [root, `${root}/audio`, `${root}/portraits`]) {
      // Probe the root before creating children: production never creates its root.
      const path = `${directory}/.probe-${crypto.randomUUID()}`;
      if (directory !== root) await mkdir(directory, { recursive: true });
      const file = await open(path, "wx");
      try {
        await file.writeFile("media startup probe");
      } finally {
        await file.close();
        await unlink(path);
      }
    }
  } catch (error) {
    throw new Error(`MEDIA_DIR is not writable: ${root}`, { cause: error });
  }
}
