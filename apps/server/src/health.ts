import { RedisClient, SQL } from "bun";
import { requireEnv } from "./env.ts";

const DEADLINE_MS = 1_000;

async function probe(
  run: () => Promise<boolean>,
  close: () => void | Promise<void>,
): Promise<boolean> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    return await Promise.race([
      Promise.resolve().then(run),
      new Promise<false>((resolve) => {
        timer = setTimeout(() => resolve(false), DEADLINE_MS);
      }),
    ]);
  } catch {
    return false;
  } finally {
    clearTimeout(timer);
    await close();
  }
}

function postgres(): Promise<boolean> {
  let client: SQL | undefined;
  return probe(
    async () => {
      client = new SQL({
        url: requireEnv("DATABASE_URL"),
        max: 1,
        connectionTimeout: DEADLINE_MS / 1_000,
      });
      const [row] = await client<{ alive: unknown }[]>`SELECT 1 AS alive`;
      return row?.alive === 1;
    },
    () => client?.close({ timeout: 0 }),
  );
}

function valkey(): Promise<boolean> {
  let client: RedisClient | undefined;
  return probe(
    async () => {
      client = new RedisClient(requireEnv("REDIS_URL"), {
        connectionTimeout: DEADLINE_MS,
        autoReconnect: false,
        maxRetries: 0,
        enableOfflineQueue: false,
      });
      await client.connect();
      const reply: unknown = await client.ping();
      return reply === "PONG";
    },
    () => client?.close(),
  );
}

export async function handleHealth(): Promise<Response> {
  const [pg, redis] = await Promise.all([postgres(), valkey()]);
  const ok = pg && redis;
  return Response.json(
    {
      status: ok ? "ok" : "unavailable",
      dependencies: {
        postgres: pg ? "ok" : "unavailable",
        valkey: redis ? "ok" : "unavailable",
      },
    },
    { status: ok ? 200 : 503 },
  );
}
