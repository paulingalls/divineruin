import { expect, test } from "bun:test";
import { mkdtemp, chmod, writeFile, rm, mkdir, copyFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve, dirname } from "node:path";

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
    const checkout = join(dir, "checkout");
    try {
      const env: NodeJS.ProcessEnv = { ...process.env, PATH: `${dir}:${process.env.PATH ?? ""}` };
      for (const name of [
        "DATABASE_URL",
        "REDIS_URL",
        "WT_PORT_OFFSET",
        "GIT_DIR",
        "GIT_WORK_TREE",
      ]) {
        delete env[name];
      }
      for (const file of [
        "apps/mobile/scripts/verify-iron-resolve.ts",
        "apps/mobile/scripts/iron-resolve-backend-ownership.ts",
        "apps/mobile/scripts/owned-simulator.ts",
        "apps/mobile/scripts/native-transport-processes.ts",
        "scripts/worktree-common.sh",
        "scripts/worktree-docker.sh",
      ]) {
        await mkdir(dirname(join(checkout, file)), { recursive: true });
        await copyFile(join(root, file), join(checkout, file));
      }
      const git = Bun.spawn(["git", "init", "--quiet"], { cwd: checkout, env });
      expect(await git.exited).toBe(0);
      const settings = Bun.spawn(["bash", "scripts/worktree-common.sh", "expected-env"], {
        cwd: checkout,
        env,
        stdout: "pipe",
        stderr: "pipe",
      });
      const [ownedEnv, settingsError, settingsExit] = await Promise.all([
        new Response(settings.stdout).text(),
        new Response(settings.stderr).text(),
        settings.exited,
      ]);
      expect(settingsExit, settingsError).toBe(0);
      await writeFile(join(checkout, ".env"), ownedEnv);
      for (const name of ["bun", "xcrun", "docker"]) {
        const script =
          name === "docker"
            ? "#!/bin/sh\nexit 1\n"
            : '#!/bin/sh\nprintf started > "$IRON_RESOLVE_START_MARKER"\nexit 1\n';
        await writeFile(join(dir, name), script);
        await chmod(join(dir, name), 0o755);
      }
      env.IRON_RESOLVE_START_MARKER = marker;
      if (key === "DATABASE_URL") env.DATABASE_URL = "postgresql://sentinel@127.0.0.1:1/foreign";
      if (key === "REDIS_URL") env.REDIS_URL = "redis://127.0.0.1:1";
      if (key === "empty DATABASE_URL") env.DATABASE_URL = "";
      if (key === "empty REDIS_URL") env.REDIS_URL = "";
      const child = Bun.spawn([process.execPath, "apps/mobile/scripts/verify-iron-resolve.ts"], {
        cwd: checkout,
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
