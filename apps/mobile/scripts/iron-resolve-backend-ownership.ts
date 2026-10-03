export async function authorizeIronResolveBackend(root: string): Promise<void> {
  // Match the backend's Bun env-file precedence before opening either service.
  const check = Bun.spawn([process.execPath, "--env-file=.env", import.meta.path], {
    cwd: root,
    env: process.env,
    stdout: "inherit",
    stderr: "pipe",
  });
  const error = await new Response(check.stderr).text();
  if ((await check.exited) !== 0) throw new Error(error.trim() || "Backend ownership refused");
}

if (import.meta.main) {
  if (!process.env.DATABASE_URL || !process.env.REDIS_URL)
    throw new Error("DATABASE_URL and REDIS_URL are required for native verification");
  const check = Bun.spawn(["bash", "scripts/worktree-common.sh", "authorize", "connect"], {
    env: process.env,
    stdout: "inherit",
    stderr: "inherit",
  });
  if ((await check.exited) !== 0) throw new Error("Backend service connection ownership refused");
}
