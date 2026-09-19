interface SpawnOptions {
  cwd: string;
  env?: Record<string, string>;
  capture?: boolean;
}

function groupExists(pid: number): boolean {
  try {
    process.kill(-pid, 0);
    return true;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ESRCH") return false;
    if ((error as NodeJS.ErrnoException).code === "EPERM") return true;
    throw error;
  }
}

function signalGroup(pid: number, signal: NodeJS.Signals): void {
  try {
    process.kill(-pid, signal);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ESRCH") throw error;
  }
}

type Child = ReturnType<OwnedProcesses["spawn"]>;

export class OwnedProcesses {
  readonly controller = new AbortController();
  private readonly children = new Set<Child>();
  private closed = false;

  get signal(): AbortSignal {
    return this.controller.signal;
  }

  spawn(command: string[], options: SpawnOptions) {
    this.signal.throwIfAborted();
    if (this.closed) throw new Error("native transport process scope is closed");
    const child = Bun.spawn(command, {
      cwd: options.cwd,
      env: options.env,
      detached: true,
      stdin: "ignore",
      stdout: options.capture ? "pipe" : "inherit",
      stderr: options.capture ? "pipe" : "inherit",
    });
    this.children.add(child);
    return child;
  }

  async wait<T>(pending: Promise<T>): Promise<T> {
    this.signal.throwIfAborted();
    let rejectAbort: () => void = () => {};
    const aborted = new Promise<never>((_resolve, reject) => {
      rejectAbort = () => reject(this.signal.reason as Error);
      this.signal.addEventListener("abort", rejectAbort, { once: true });
    });
    try {
      return await Promise.race([pending, aborted]);
    } finally {
      this.signal.removeEventListener("abort", rejectAbort);
    }
  }

  async stop(child: Child | undefined): Promise<void> {
    if (!child || !this.children.has(child)) return;
    signalGroup(child.pid, "SIGTERM");
    const deadline = Date.now() + 5_000;
    while (groupExists(child.pid) && Date.now() < deadline) await Bun.sleep(20);
    if (groupExists(child.pid)) signalGroup(child.pid, "SIGKILL");
    await child.exited;
    const killDeadline = Date.now() + 2_000;
    while (groupExists(child.pid) && Date.now() < killDeadline) await Bun.sleep(20);
    if (groupExists(child.pid))
      throw new Error(`owned process group ${child.pid} survived cleanup`);
    this.children.delete(child);
  }

  async close(): Promise<void> {
    this.closed = true;
    const results = await Promise.allSettled([...this.children].map((child) => this.stop(child)));
    const failures = results.flatMap((result) =>
      result.status === "rejected" ? [result.reason as Error] : [],
    );
    if (failures.length) throw new AggregateError(failures, "native transport cleanup failed");
  }
}

export async function withOwnedProcesses<T>(
  run: (scope: OwnedProcesses) => Promise<T>,
): Promise<T> {
  const scope = new OwnedProcesses();
  const interrupt = () => scope.controller.abort(new Error("native transport cancelled by SIGINT"));
  const terminate = () =>
    scope.controller.abort(new Error("native transport cancelled by SIGTERM"));
  process.on("SIGINT", interrupt);
  process.on("SIGTERM", terminate);
  const outcome = await Promise.resolve()
    .then(() => run(scope))
    .then(
      (value) => ({ ok: true as const, value }),
      (error: unknown) => ({ ok: false as const, error }),
    );
  const cleanup = await scope.close().then(
    () => ({ ok: true as const }),
    (error: unknown) => ({ ok: false as const, error }),
  );
  process.off("SIGINT", interrupt);
  process.off("SIGTERM", terminate);
  if (!outcome.ok && !cleanup.ok) {
    throw new AggregateError(
      [outcome.error, cleanup.error],
      "native transport failed and cleanup failed",
      { cause: outcome.error },
    );
  }
  if (!outcome.ok) throw outcome.error;
  if (!cleanup.ok) throw cleanup.error;
  scope.signal.throwIfAborted();
  return outcome.value;
}
