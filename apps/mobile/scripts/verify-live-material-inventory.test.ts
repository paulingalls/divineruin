import { expect, test } from "bun:test";
import { OwnedProcesses } from "./native-transport-processes";
import {
  runLiveMaterialInventory,
  phases,
  type LiveMaterialDeps,
} from "./verify-live-material-inventory";

function capture(runId: string) {
  return {
    runId,
    owners: ["one", "two"],
    initial: { one: [], two: [] },
    sender: { isAgent: true, identity: "agent", kind: 4 },
    steps: phases.map((phase) => {
      const event = { type: "inventory_updated", player_id: "one", inventory: [] };
      return {
        phase,
        received: [event],
        received_bytes: [Array.from(new TextEncoder().encode(JSON.stringify(event)))],
        expected: { one: [], two: [] },
      };
    }),
  };
}

function harness() {
  const calls: string[] = [];
  let fixture: unknown;
  const kinds = new Map<number, string>();
  const deps: LiveMaterialDeps = {
    acceptance: (_scope, _path, id) => {
      calls.push("acceptance");
      fixture = capture(id);
      return Promise.resolve();
    },
    readFixture: () => Promise.resolve(fixture),
    resolveSimulator: () => Promise.resolve("owned-simulator"),
    reservePort: () => Promise.resolve(1234),
    start: (scope, kind) => {
      calls.push(`start:${kind}`);
      const child = scope.spawn(["bun", "-e", "setInterval(() => {}, 1000)"], {
        cwd: process.cwd(),
        capture: true,
      });
      kinds.set(child.pid, kind);
      return child;
    },
    ready: (_scope, kind) => {
      calls.push(`ready:${kind}`);
      return Promise.resolve();
    },
    stop: async (scope, child) => {
      const kind = kinds.get(child.pid);
      if (!kind) throw new Error("Unrecognized owned child");
      calls.push(`stop:${kind}`);
      await scope.stop(child);
    },
    serve: () => {
      calls.push("serve");
      return {
        port: 4321,
        stop: () => {
          calls.push("stop:server");
          return Promise.resolve();
        },
      };
    },
    command: (_scope, argv, env) => {
      calls.push(argv[0] === "maestro" ? "panel" : "auth");
      expect(env.IOS_SIMULATOR_UDID).toBe("owned-simulator");
      expect(env.EXPO_PUBLIC_API_URL).toBe("http://127.0.0.1:1234");
      return Promise.resolve({ exitCode: 0 });
    },
  };
  return {
    deps,
    calls,
    setFixture: (value: unknown) => {
      fixture = value;
    },
  };
}

async function execute(deps: LiveMaterialDeps, scope = new OwnedProcesses()) {
  try {
    await runLiveMaterialInventory(scope, deps);
  } finally {
    await scope.close();
  }
}

async function failure(action: Promise<unknown>): Promise<string> {
  try {
    await action;
  } catch (error) {
    return error instanceof Error ? error.message : String(error);
  }
  throw new Error("Expected verification failure");
}

test("executes fresh valid phases through strict preflight and panel", async () => {
  const { deps, calls } = harness();
  await execute(deps);
  expect(calls).toEqual([
    "acceptance",
    "start:backend",
    "ready:backend",
    "auth",
    "serve",
    "start:metro",
    "ready:metro",
    "panel",
    "stop:metro",
    "stop:server",
    "stop:backend",
  ]);
});

test("rejects stale artifact when acceptance produces nothing", async () => {
  const { deps, calls, setFixture } = harness();
  setFixture(capture("old-invocation"));
  deps.acceptance = () => Promise.resolve();
  expect(await failure(execute(deps))).toContain("invocation");
  expect(calls).toEqual([]);
});

for (const phase of [0, 1, 2, 3, 4, 5, 6]) {
  for (const fault of [
    "missing",
    "duplicate",
    "empty",
    "malformed",
    "mismatch",
    "byte",
    "fraction",
    "negative",
    "kind",
    "identity",
    "count",
    "session_init",
    "expectations",
    "sender",
  ]) {
    test(`rejects missing and unusable required phases: ${phase} ${fault}`, async () => {
      const { deps, calls, setFixture } = harness();
      deps.acceptance = (_scope, _path, id) => {
        const fixture = capture(id);
        if (fault === "missing") fixture.steps.splice(phase, 1);
        if (fault === "duplicate")
          fixture.steps[phase].phase = fixture.steps[(phase + 1) % 7].phase;
        if (fault === "empty") {
          fixture.steps[phase].received_bytes = [];
          fixture.steps[phase].received = [];
        }
        if (fault === "malformed") fixture.steps[phase].received_bytes = [[123]];
        if (fault === "mismatch") fixture.steps[phase].received[0].player_id = "different-owner";
        if (fault === "byte") fixture.steps[phase].received_bytes[0][0] = 379;
        if (fault === "fraction") fixture.steps[phase].received_bytes[0][0] = 123.5;
        if (fault === "negative") fixture.steps[phase].received_bytes[0][0] = -133;
        if (fault === "kind") fixture.sender.kind = 0;
        if (fault === "identity") fixture.sender.identity = "";
        if (fault === "count") fixture.steps[phase].received.push(fixture.steps[phase].received[0]);
        if (fault === "session_init") {
          fixture.steps[phase].received[0].type = "session_init";
          fixture.steps[phase].received_bytes[0] = Array.from(
            new TextEncoder().encode(JSON.stringify(fixture.steps[phase].received[0])),
          );
        }
        if (fault === "expectations")
          delete (fixture.steps[phase].expected as Record<string, unknown>).two;
        if (fault === "sender") fixture.sender.isAgent = false;
        setFixture(fixture);
        return Promise.resolve();
      };
      expect(await failure(execute(deps))).toContain("usable");
      expect(calls).toEqual([]);
    });
  }
}

test("aborts panel execution when native auth preflight fails", async () => {
  const { deps, calls } = harness();
  deps.command = () => Promise.resolve({ exitCode: 8 });
  expect(await failure(execute(deps))).toContain("status 8");
  expect(calls).not.toContain("panel");
  expect(calls).toContain("stop:backend");
});

for (const result of [
  { exitCode: 9 },
  { exitCode: null, signal: "SIGINT" },
  { exitCode: 0, signal: "SIGTERM" },
]) {
  test(`rejects nonzero and interrupted Maestro results: ${JSON.stringify(result)}`, async () => {
    const { deps, calls } = harness();
    deps.command = (_scope, argv) =>
      Promise.resolve(argv[0] === "maestro" ? result : { exitCode: 0 });
    expect(await failure(execute(deps))).toContain("status");
    expect(calls.slice(-3)).toEqual(["stop:metro", "stop:server", "stop:backend"]);
  });
}

for (const kind of ["backend", "metro"] as const) {
  for (const cancellation of [false, true]) {
    test(`cleans ${kind} after readiness fails${cancellation ? " during cancellation" : ""}`, async () => {
      const { deps, calls } = harness();
      const scope = new OwnedProcesses();
      const previousApi = process.env.EXPO_PUBLIC_API_URL;
      const previousSimulator = process.env.IOS_SIMULATOR_UDID;
      const children: ReturnType<OwnedProcesses["spawn"]>[] = [];
      if (cancellation)
        deps.start = (owned, name) => {
          calls.push(`start:${name}`);
          const child = owned.spawn(["bun", "-e", "setInterval(() => {}, 1000)"], {
            cwd: process.cwd(),
            capture: true,
          });
          children.push(child);
          return child;
        };
      deps.ready = async (owned, name) => {
        if (name !== kind) return;
        if (cancellation) {
          setTimeout(() => owned.controller.abort(new Error("cancelled readiness")), 20);
          await new Promise(() => {});
        }
        throw new Error("readiness failed");
      };
      if (cancellation) deps.stop = (owned, process) => owned.stop(process);
      try {
        expect(
          await failure(
            Promise.race([
              runLiveMaterialInventory(scope, deps),
              Bun.sleep(1000).then(() => {
                throw new Error("cancellation did not settle");
              }),
            ]),
          ),
        ).toContain(cancellation ? "cancelled" : "readiness");
        for (const child of children) {
          expect(() => process.kill(-child.pid, 0)).toThrow();
          await child.exited;
        }
      } finally {
        await scope.close();
      }
      if (!children.length) {
        expect(calls).toContain(`stop:${kind}`);
      }
      expect(process.env.EXPO_PUBLIC_API_URL).toBe(previousApi);
      expect(process.env.IOS_SIMULATOR_UDID).toBe(previousSimulator);
      expect(calls).not.toContain("panel");
      if (kind === "metro") expect(calls).toContain("stop:server");
    });
  }
}

test("cleanup failure retains readiness failure", async () => {
  const { deps } = harness();
  deps.ready = () => Promise.reject(new Error("readiness failed"));
  deps.stop = () => Promise.reject(new Error("cleanup failed"));
  try {
    await execute(deps);
    throw new Error("resolved");
  } catch (error) {
    expect(error).toBeInstanceOf(AggregateError);
    expect(String((error as AggregateError).errors)).toContain("readiness failed");
    expect(String((error as AggregateError).errors)).toContain("cleanup failed");
  }
});

for (const fault of ["initial", "same-owner", "extra-owner"]) {
  test(`rejects unusable owner manifest: ${fault}`, async () => {
    const { deps, calls, setFixture } = harness();
    deps.acceptance = (_scope, _path, id) => {
      const fixture = capture(id);
      if (fault === "initial") delete (fixture.initial as Record<string, unknown>).two;
      if (fault === "same-owner") fixture.owners[1] = fixture.owners[0];
      if (fault === "extra-owner") fixture.owners.push(fixture.owners[0]);
      setFixture(fixture);
      return Promise.resolve();
    };
    expect(await failure(execute(deps))).toContain("usable");
    expect(calls).toEqual([]);
  });
}

for (const type of [undefined, null, 4, false, {}, []]) {
  test(`rejects a received event with non-string type: ${JSON.stringify(type)}`, async () => {
    const { deps, calls, setFixture } = harness();
    deps.acceptance = (_scope, _path, id) => {
      const fixture = capture(id);
      const step = fixture.steps[0];
      const event = { ...step.received[0], type };
      (step.received as unknown[])[0] = event;
      step.received_bytes[0] = Array.from(new TextEncoder().encode(JSON.stringify(event)));
      setFixture(fixture);
      return Promise.resolve();
    };
    expect(await failure(execute(deps))).toContain("usable");
    expect(calls).toEqual([]);
  });
}

test("rejects invalid UTF-8 even when permissive decoding matches the event", async () => {
  const { deps, calls, setFixture } = harness();
  deps.acceptance = (_scope, _path, id) => {
    const fixture = capture(id);
    const step = fixture.steps[0];
    step.received[0].player_id = "\uFFFD";
    const bytes = new TextEncoder().encode(JSON.stringify({ ...step.received[0], player_id: "x" }));
    bytes[bytes.indexOf("x".charCodeAt(0))] = 255;
    step.received_bytes[0] = Array.from(bytes);
    setFixture(fixture);
    return Promise.resolve();
  };
  expect(await failure(execute(deps))).toContain("usable");
  expect(calls).toEqual([]);
});

test("cancellation during successful cleanup cannot report verification success", async () => {
  const { deps } = harness();
  const stop = deps.stop.bind(deps);
  deps.stop = async (scope, child) => {
    scope.controller.abort(new Error("cancelled cleanup"));
    await stop(scope, child);
  };
  expect(await failure(execute(deps))).toContain("cancelled cleanup");
});
