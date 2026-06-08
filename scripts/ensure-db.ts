// Test-harness DB lifecycle: make the test gate self-heal when docker isn't up.
//
// Both unit lanes in test-all.ts connect to the docker-compose Postgres at
// :55432 (the canonical dev DB) — the TS DB/integration suites and many Python
// non-acceptance tests. When that DB isn't running, the gate fails with
// connection errors. ensureDbUp() detects reachability and, only if the DB is
// down, runs `docker compose up -d` and waits for readiness; stopIfStarted()
// stops ONLY what this run started (never `down -v`, so a pre-existing dev DB
// and its volumes survive). The Python session conftest mirrors this for bare
// `pytest` runs (apps/agent/tests/_db_lifecycle.py).

import { Socket } from "node:net";

// Mirrors scripts/seed_content.py's default so the helper works even if
// DATABASE_URL isn't set in the environment.
const DEFAULT_DATABASE_URL = "postgresql://divineruin:divineruin_dev@localhost:55432/divineruin";
const COMPOSE_FILE = new URL("../docker-compose.yml", import.meta.url).pathname;
const READY_TIMEOUT_MS = 60_000;

export function parseHostPort(databaseUrl: string): { host: string; port: number } {
  const url = new URL(databaseUrl);
  return { host: url.hostname, port: Number(url.port) || 5432 };
}

export function parseUser(databaseUrl: string): string {
  return decodeURIComponent(new URL(databaseUrl).username) || "divineruin";
}

export function isReachable(host: string, port: number, timeoutMs = 1000): Promise<boolean> {
  return new Promise((resolve) => {
    const socket = new Socket();
    const finish = (ok: boolean) => {
      socket.destroy();
      resolve(ok);
    };
    socket.setTimeout(timeoutMs);
    socket.once("connect", () => finish(true));
    socket.once("timeout", () => finish(false));
    socket.once("error", () => finish(false));
    try {
      socket.connect(port, host);
    } catch {
      finish(false);
    }
  });
}

async function compose(...args: string[]): Promise<number> {
  const proc = Bun.spawn(["docker", "compose", "-f", COMPOSE_FILE, ...args], {
    stdout: "inherit",
    stderr: "inherit",
  });
  return proc.exited;
}

// True if Postgres accepts queries (not just listening). On a cold start the
// container opens the TCP port while still recovering and rejects queries with
// 'the database system is starting up'; pg_isready inside the container reports
// actual query-readiness, closing that race.
async function isAcceptingQueries(user: string): Promise<boolean> {
  const proc = Bun.spawn(
    ["docker", "compose", "-f", COMPOSE_FILE, "exec", "-T", "postgres", "pg_isready", "-U", user],
    {
      stdout: "ignore",
      stderr: "ignore",
    },
  );
  return (await proc.exited) === 0;
}

// Returns true iff THIS call started docker compose — pass it to stopIfStarted
// so a pre-existing dev DB is never stopped.
export async function ensureDbUp(): Promise<boolean> {
  const databaseUrl = process.env.DATABASE_URL ?? DEFAULT_DATABASE_URL;
  const { host, port } = parseHostPort(databaseUrl);
  const user = parseUser(databaseUrl);
  if (await isReachable(host, port)) return false;

  console.log(
    `[db-lifecycle] Postgres not reachable at ${host}:${port} — starting docker compose...`,
  );
  const upExit = await compose("up", "-d");
  if (upExit !== 0) {
    throw new Error(`\`docker compose up -d\` failed (exit ${upExit})`);
  }

  const deadline = Date.now() + READY_TIMEOUT_MS;
  while (Date.now() < deadline) {
    if (await isAcceptingQueries(user)) {
      console.log("[db-lifecycle] Postgres ready.");
      return true;
    }
    await Bun.sleep(1000);
  }
  throw new Error(
    `Postgres at ${host}:${port} did not accept queries within ${READY_TIMEOUT_MS}ms`,
  );
}

export async function stopIfStarted(started: boolean): Promise<void> {
  if (!started) return;
  console.log("[db-lifecycle] Stopping docker compose services this run started...");
  await compose("stop");
}
