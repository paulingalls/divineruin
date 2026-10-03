import { randomBytes } from "node:crypto";

export async function withChoirServices<T>(
  root: string,
  run: (env: Record<string, string>) => Promise<T>,
): Promise<T> {
  const names: string[] = [];
  const controller = new AbortController();
  const cancel = () => controller.abort(new Error("Choir service run interrupted"));
  process.on("SIGINT", cancel);
  process.on("SIGTERM", cancel);
  const env: Record<string, string> = {};
  for (const key of ["PATH", "HOME", "TMPDIR", "USER", "SHELL", "DEVELOPER_DIR"]) {
    if (process.env[key]) env[key] = process.env[key]!;
  }
  const command = async (args: string[], childEnv = env, cleanup = false) => {
    if (!cleanup) controller.signal.throwIfAborted();
    const child = Bun.spawn(args, { cwd: root, env: childEnv, stdout: "pipe", stderr: "pipe" });
    const [out, error, status] = await Promise.all([
      new Response(child.stdout).text(),
      new Response(child.stderr).text(),
      child.exited,
    ]);
    if (!cleanup) controller.signal.throwIfAborted();
    if (status !== 0) throw new Error(`Choir service command ${args[0]} failed: ${error}`);
    return out.trim();
  };
  const start = async (kind: string, args: string[]) => {
    const name = `choir-${crypto.randomUUID()}-${kind}`;
    names.push(name);
    await command(["docker", "run", "-d", "--name", name, ...args]);
    return name;
  };
  const port = async (name: string, internal: string) => {
    const mapping = await command(["docker", "port", name, internal]);
    if (!/^127\.0\.0\.1:\d+$/.test(mapping))
      throw new Error("Choir service is not loopback isolated");
    return mapping.split(":")[1];
  };
  let result: T | undefined;
  let failure: Error | undefined;
  const cleanupFailures: unknown[] = [];
  try {
    const password = randomBytes(32).toString("hex");
    const pg = await start("pg", [
      "-p",
      "127.0.0.1:0:5432",
      "-e",
      "POSTGRES_USER=choir",
      "-e",
      `POSTGRES_PASSWORD=${password}`,
      "-e",
      "POSTGRES_DB=choir",
      "postgres:16-alpine",
    ]);
    const redis = await start("redis", ["-p", "127.0.0.1:0:6379", "valkey/valkey:8-alpine"]);
    const reservation = Bun.serve({ hostname: "127.0.0.1", port: 0, fetch: () => new Response() });
    const udpPort = reservation.port!;
    await reservation.stop(true);
    const key = randomBytes(16).toString("hex");
    const secret = randomBytes(32).toString("hex");
    const livekit = await start("livekit", [
      "-p",
      "127.0.0.1:0:7880",
      "-p",
      `127.0.0.1:${udpPort}:${udpPort}/udp`,
      "livekit/livekit-server:v1.11.0",
      "--dev",
      "--bind",
      "0.0.0.0",
      "--keys",
      `${key}: ${secret}`,
      "--config-body",
      `rtc:\n  udp_port: ${udpPort}\n  node_ip: 127.0.0.1\n  use_external_ip: false\n`,
    ]);
    Object.assign(env, {
      DATABASE_URL: `postgresql://choir:${password}@127.0.0.1:${await port(pg, "5432/tcp")}/choir`,
      REDIS_URL: `redis://127.0.0.1:${await port(redis, "6379/tcp")}`,
      LIVEKIT_URL: `ws://127.0.0.1:${await port(livekit, "7880/tcp")}`,
      LIVEKIT_API_KEY: key,
      LIVEKIT_API_SECRET: secret,
      JWT_SECRET: randomBytes(32).toString("hex"),
      SERVER_HOST: "127.0.0.1",
    });
    let ready = false;
    for (let attempt = 0; attempt < 60; attempt++) {
      try {
        await command(["docker", "exec", pg, "pg_isready", "-U", "choir", "-d", "choir"]);
        await command(["docker", "exec", redis, "valkey-cli", "ping"]);
        const response = await fetch(env.LIVEKIT_URL.replace("ws:", "http:"));
        if (response.status < 500) {
          ready = true;
          break;
        }
      } catch {
        /* Containers can publish their ports before becoming ready. */
      }
      await Bun.sleep(1000);
    }
    if (!ready) throw new Error("Choir disposable services did not become ready");
    await command(["bun", "--no-env-file", "scripts/migrate.ts"]);
    await command([
      "uv",
      "run",
      "--project",
      "scripts",
      "--frozen",
      "python",
      "scripts/seed_content.py",
    ]);
    result = await run(env);
  } catch (error) {
    failure =
      error instanceof Error ? error : new Error("Choir service run failed", { cause: error });
  } finally {
    const cleanup = await Promise.allSettled(
      names.reverse().map((name) => command(["docker", "rm", "-f", name], env, true)),
    );
    process.off("SIGINT", cancel);
    process.off("SIGTERM", cancel);
    for (const item of cleanup) {
      if (item.status === "rejected") cleanupFailures.push(item.reason as unknown);
    }
  }
  if (cleanupFailures.length) {
    throw new AggregateError([failure, ...cleanupFailures], "Choir service cleanup failed");
  }
  if (failure !== undefined) throw failure;
  return result as T;
}
