import { expect, test } from "bun:test";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

import { withOwnedProcesses } from "../../scripts/native-transport-processes";

const helper = resolve(import.meta.dir, "../../scripts/native-transport-processes.ts");

function alive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ESRCH") return false;
    throw error;
  }
}

function emergencyStop(pid: number): void {
  if (!pid) return;
  try {
    process.kill(-pid, "SIGKILL");
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ESRCH") throw error;
  }
}

async function waitForPid(path: string): Promise<number> {
  for (let attempt = 0; attempt < 250; attempt++) {
    const value = await readFile(path, "utf8").catch(() => "");
    if (/^\d+$/.test(value)) return Number(value);
    await Bun.sleep(20);
  }
  throw new Error(`child did not write its PID: ${path}`);
}

function familySource(pidPath: string, ignoreTerm = false): string {
  const keepAlive = `${ignoreTerm ? 'process.on("SIGTERM", () => {});' : ""} setInterval(() => {}, 1000);`;
  return `
    const child = Bun.spawn([process.execPath, "-e", ${JSON.stringify(keepAlive)}], {stdout:"ignore",stderr:"ignore"});
    await Bun.write(${JSON.stringify(pidPath)}, String(child.pid));
    ${keepAlive}
  `;
}

test("normal completion closes owned descendants and preserves an unrelated process", async () => {
  const scratch = await mkdtemp(join(tmpdir(), "native-process-test-"));
  const sibling = Bun.spawn([process.execPath, "-e", "setInterval(() => {}, 1000)"], {
    stdout: "ignore",
  });
  let parent = 0;
  let descendant = 0;
  try {
    await withOwnedProcesses(async (scope) => {
      const child = scope.spawn([process.execPath, "-e", familySource(join(scratch, "pid"))], {
        cwd: scratch,
      });
      parent = child.pid;
      descendant = await waitForPid(join(scratch, "pid"));
      expect(alive(parent)).toBeTrue();
      expect(alive(descendant)).toBeTrue();
    });
    expect(alive(parent)).toBeFalse();
    expect(alive(descendant)).toBeFalse();
    expect(alive(sibling.pid)).toBeTrue();
  } finally {
    emergencyStop(parent);
    sibling.kill();
    await sibling.exited;
    await rm(scratch, { recursive: true, force: true });
  }
});

test("failed work keeps its error and escalates TERM-resistant owned descendants", async () => {
  const scratch = await mkdtemp(join(tmpdir(), "native-process-test-"));
  let descendant = 0;
  let parent = 0;
  let error: unknown;
  try {
    try {
      await withOwnedProcesses(async (scope) => {
        parent = scope.spawn([process.execPath, "-e", familySource(join(scratch, "pid"), true)], {
          cwd: scratch,
        }).pid;
        descendant = await waitForPid(join(scratch, "pid"));
        await Bun.sleep(100);
        throw new Error("original scenario failure");
      });
    } catch (caught) {
      error = caught;
    }
    expect(error).toBeInstanceOf(Error);
    expect((error as Error).message).toBe("original scenario failure");
    expect(alive(descendant)).toBeFalse();
  } finally {
    emergencyStop(parent);
    await rm(scratch, { recursive: true, force: true });
  }
}, 15_000);

for (const signal of ["SIGINT", "SIGTERM"] as const) {
  test(`${signal} interrupts a wait and cleans the actual subprocess family`, async () => {
    const scratch = await mkdtemp(join(tmpdir(), "native-signal-test-"));
    const grandchildFile = join(scratch, "grandchild");
    const parentFile = join(scratch, "parent");
    const script = join(scratch, "runner.ts");
    await writeFile(
      script,
      `
      import { withOwnedProcesses } from ${JSON.stringify(helper)};
      await withOwnedProcesses(async (scope) => {
        const child = scope.spawn([process.execPath, "-e", ${JSON.stringify(familySource(grandchildFile))}], {cwd:${JSON.stringify(scratch)}});
        await Bun.write(${JSON.stringify(parentFile)}, String(child.pid));
        await scope.wait(new Promise(() => {}));
      });
    `,
    );
    const runner = Bun.spawn([process.execPath, script], { stdout: "ignore", stderr: "pipe" });
    let parent = 0;
    try {
      parent = await waitForPid(parentFile);
      const descendant = await waitForPid(grandchildFile);
      runner.kill(signal);
      expect(await runner.exited).not.toBe(0);
      expect(alive(parent)).toBeFalse();
      expect(alive(descendant)).toBeFalse();
      const stderr = await new Response(runner.stderr).text();
      expect(stderr).toContain(`cancelled by ${signal}`);
    } finally {
      emergencyStop(parent);
      runner.kill();
      await runner.exited;
      await rm(scratch, { recursive: true, force: true });
    }
  }, 15_000);
}

test("a closed scope cannot launch another process", async () => {
  await withOwnedProcesses(async (scope) => {
    await scope.close();
    expect(() =>
      scope.spawn([process.execPath, "-e", "process.exit(0)"], { cwd: tmpdir() }),
    ).toThrow(/closed/);
  });
});

test("cancellation during cleanup cannot return a successful result", async () => {
  let error: unknown;
  try {
    await withOwnedProcesses((scope) => {
      const close = scope.close.bind(scope);
      scope.close = async () => {
        scope.controller.abort(new Error("cancel during cleanup"));
        await close();
      };
      return Promise.resolve("success");
    });
  } catch (caught) {
    error = caught;
  }
  expect(error).toBeInstanceOf(Error);
  expect((error as Error).message).toBe("cancel during cleanup");
});
