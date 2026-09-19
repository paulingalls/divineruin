import { Socket } from "node:net";

const DEFAULT_DATABASE_URL = "postgresql://divineruin:divineruin_dev@localhost:55432/divineruin";
const OWNER = new URL("./worktree-common.sh", import.meta.url).pathname;
const READY_TIMEOUT_MS = 60_000;
const OWNERSHIP_REFUSAL_EXIT = 78;

export type OwnershipIntent = "settings" | "create" | "reuse" | "destroy" | "ci";

export interface LifecycleDeps {
  authorizeRuntime(databaseUrl: string, redisUrl?: string): Promise<void>;
  authorize(intent: OwnershipIntent): Promise<void>;
  compose(intent: OwnershipIntent, ...args: string[]): Promise<number>;
  reachable(host: string, port: number): Promise<boolean>;
  accepting(user: string): Promise<boolean>;
  sleep(ms: number): Promise<void>;
  now(): number;
}

export function parseHostPort(databaseUrl: string): { host: string; port: number } {
  const url = new URL(databaseUrl);
  return { host: url.hostname, port: Number(url.port) || 5432 };
}

export function parseUser(databaseUrl: string): string {
  return decodeURIComponent(new URL(databaseUrl).username) || "divineruin";
}

export function isCiServiceMode(env: NodeJS.ProcessEnv = process.env): boolean {
  return env.GITHUB_ACTIONS === "true" && env.DIVINERUIN_CI_SERVICE_DB === "1";
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

async function runOwner(...args: string[]): Promise<{ exit: number; stderr: string }> {
  const proc = Bun.spawn(["bash", OWNER, ...args], { stdout: "inherit", stderr: "pipe" });
  const stderr = await new Response(proc.stderr).text();
  return { exit: await proc.exited, stderr };
}

async function authorize(intent: OwnershipIntent): Promise<void> {
  const result = await runOwner("authorize", intent);
  if (result.exit !== 0)
    throw new Error(result.stderr.trim() || `ownership check failed (${result.exit})`);
}

export async function authorizeRuntime(databaseUrl: string, redisUrl?: string): Promise<void> {
  const result = await runOwner("authorize-runtime", databaseUrl, redisUrl ?? "");
  if (result.exit !== 0)
    throw new Error(result.stderr.trim() || `runtime ownership check failed (${result.exit})`);
}

async function compose(intent: OwnershipIntent, ...args: string[]): Promise<number> {
  const result = await runOwner("compose", intent, ...args);
  if (result.stderr) process.stderr.write(result.stderr);
  return result.exit;
}

type OwnerResult = { exit: number; stderr: string };

export async function isAcceptingQueries(
  user: string,
  runner: (...args: string[]) => Promise<OwnerResult> = runOwner,
): Promise<boolean> {
  const result = await runner(
    "compose",
    "reuse",
    "exec",
    "-T",
    "postgres",
    "pg_isready",
    "-U",
    user,
  );
  if (result.exit === OWNERSHIP_REFUSAL_EXIT)
    throw new Error(result.stderr.trim() || "ownership check failed during Postgres readiness");
  return result.exit === 0;
}

const defaults: LifecycleDeps = {
  authorizeRuntime,
  authorize,
  compose,
  reachable: isReachable,
  accepting: isAcceptingQueries,
  sleep: Bun.sleep,
  now: Date.now,
};

export async function ensureDbUp(deps: LifecycleDeps = defaults): Promise<boolean> {
  const databaseUrl = process.env.DATABASE_URL ?? DEFAULT_DATABASE_URL;
  const { host, port } = parseHostPort(databaseUrl);
  const user = parseUser(databaseUrl);
  const ci = isCiServiceMode();
  if (ci) await deps.authorize("ci");
  else await deps.authorizeRuntime(databaseUrl, process.env.REDIS_URL);
  if (await deps.reachable(host, port)) {
    if (!ci) await deps.authorize("reuse");
    return false;
  }
  if (ci)
    throw new Error(
      `CI service Postgres is not reachable at ${host}:${port}; Compose mutation is disabled`,
    );

  console.log(
    `[db-lifecycle] Postgres not reachable at ${host}:${port} — starting owned Compose project...`,
  );
  const upExit = await deps.compose("create", "up", "-d");
  if (upExit !== 0) throw new Error(`owned \`docker compose up -d\` failed (exit ${upExit})`);

  const deadline = deps.now() + READY_TIMEOUT_MS;
  while (deps.now() < deadline) {
    if (await deps.accepting(user)) return true;
    await deps.sleep(1000);
  }
  throw new Error(
    `Postgres at ${host}:${port} did not accept queries within ${READY_TIMEOUT_MS}ms`,
  );
}

export async function stopIfStarted(
  started: boolean,
  deps: LifecycleDeps = defaults,
): Promise<void> {
  if (!started) return;
  if (isCiServiceMode()) throw new Error("CI service mode cannot stop Compose resources");
  const exit = await deps.compose("destroy", "stop");
  if (exit !== 0) throw new Error(`owned \`docker compose stop\` failed (exit ${exit})`);
}
