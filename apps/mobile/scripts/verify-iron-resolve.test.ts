import { expect, test } from "bun:test";
import { mkdtemp, chmod, writeFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

const root = resolve(import.meta.dir, "../../..");

for (const key of [
  "DATABASE_URL",
  "REDIS_URL",
  "service ownership",
  "empty DATABASE_URL",
  "empty REDIS_URL",
]) {
  test(`native verification refuses foreign ${key} before simulator or backend start`, async () => {
    const dir = await mkdtemp(join(tmpdir(), "iron-resolve-ownership-"));
    const marker = join(dir, "started");
    try {
      for (const name of ["bun", "xcrun", "docker"]) {
        const script =
          name === "docker"
            ? "#!/bin/sh\nexit 1\n"
            : `#!/bin/sh\nprintf started > '${marker}'\nexit 1\n`;
        await writeFile(join(dir, name), script);
        await chmod(join(dir, name), 0o755);
      }
      const env: NodeJS.ProcessEnv = { ...process.env, PATH: `${dir}:${process.env.PATH ?? ""}` };
      delete env.DATABASE_URL;
      delete env.REDIS_URL;
      if (key === "DATABASE_URL") env.DATABASE_URL = "postgresql://sentinel@127.0.0.1:1/foreign";
      if (key === "REDIS_URL") env.REDIS_URL = "redis://127.0.0.1:1";
      if (key === "empty DATABASE_URL") env.DATABASE_URL = "";
      if (key === "empty REDIS_URL") env.REDIS_URL = "";
      const child = Bun.spawn([process.execPath, "apps/mobile/scripts/verify-iron-resolve.ts"], {
        cwd: root,
        env,
        stdout: "pipe",
        stderr: "pipe",
      });
      const stderr = await new Response(child.stderr).text();
      expect(await child.exited).not.toBe(0);
      expect(stderr).toContain(
        key.startsWith("empty")
          ? "DATABASE_URL and REDIS_URL are required"
          : key === "service ownership"
            ? "connection ownership refused"
            : `runtime ${key}`,
      );
      expect(await Bun.file(marker).exists()).toBe(false);
    } finally {
      await rm(dir, { recursive: true, force: true });
    }
  });
}
