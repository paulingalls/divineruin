import { AgentDispatch, Room } from "@livekit/protocol";
import { ServerError } from "livekit-server-sdk";

process.env.LIVEKIT_URL = "ws://localhost:7880";
process.env.LIVEKIT_API_KEY = "session-test-key";
process.env.LIVEKIT_API_SECRET = "session-test-secret-with-at-least-32-characters";
process.env.JWT_SECRET = "ab".repeat(32);

export type Operation = "create" | "delete" | "dispatch";
export interface Call {
  operation: Operation;
  room: string;
  player?: string;
}
export interface Result {
  status: number;
  body: Record<string, unknown>;
}
export interface Message {
  kind: "ready" | "entered" | "request" | "result" | "call" | "reply";
  id: string;
  player?: string;
  path?: string;
  body?: Record<string, unknown>;
  call?: Call;
  result?: Result;
  error?: string;
}

export function gate() {
  let release!: () => void;
  const promise = new Promise<void>((resolve) => {
    release = resolve;
  });
  return { promise, release };
}

export class Recording {
  calls: Call[] = [];
  live = new Set<string>();
  failure?: Operation;
  absent = false;
  pause?: {
    operation: Operation;
    room: string;
    entered: ReturnType<typeof gate>;
    resume: ReturnType<typeof gate>;
  };
  async invoke(call: Call): Promise<void> {
    this.calls.push(call);
    if (this.pause?.operation === call.operation && this.pause.room === call.room) {
      this.pause.entered.release();
      await this.pause.resume.promise;
    }
    if (this.failure === call.operation) {
      if (this.absent) throw new ServerError("Not Found", "absent", 404, "not_found");
      throw new Error(`injected ${call.operation} failure`);
    }
    if (call.operation === "create") this.live.add(call.room);
    if (call.operation === "delete") this.live.delete(call.room);
  }
  hold(operation: Operation, room: string) {
    this.pause = { operation, room, entered: gate(), resume: gate() };
    return this.pause;
  }
  reset() {
    this.calls = [];
    this.live.clear();
    this.failure = undefined;
    this.absent = false;
    this.pause = undefined;
  }
}

export async function installSeam(invoke: (call: Call) => Promise<void>) {
  const { getLivekitClients } = await import("./livekit.ts");
  const clients = getLivekitClients();
  if (!clients) throw new Error("test LiveKit configuration missing");
  clients.roomService.createRoom = async (options) => {
    await invoke({ operation: "create", room: options.name });
    return new Room({ name: options.name });
  };
  clients.roomService.deleteRoom = async (room) => {
    await invoke({ operation: "delete", room });
  };
  clients.dispatchClient.createDispatch = async (room, agentName, options) => {
    const { player_id: player } = JSON.parse(options?.metadata ?? "{}") as { player_id: string };
    if (agentName !== "divineruin-dm") throw new Error("wrong agent name");
    await invoke({ operation: "dispatch", room, player });
    return new AgentDispatch({ room, agentName });
  };
}

export async function request(
  player: string,
  path: string,
  body: Record<string, unknown>,
): Promise<Result> {
  const { signJwt } = await import("./auth.ts");
  const { handleRequest } = await import("./index.ts");
  const bearer = await signJwt({ accountId: `account_${player}`, playerId: player });
  const response = await handleRequest(
    new Request(`http://localhost/api/livekit/${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${bearer}` },
      body: JSON.stringify(body),
    }),
    crypto.randomUUID(),
  );
  return { status: response.status, body: (await response.json()) as Record<string, unknown> };
}

if (import.meta.main) {
  const pending = new Map<string, { resolve: () => void; reject: (error: Error) => void }>();
  process.on("message", (message: Message) => {
    if (message.kind === "reply") {
      const waiter = pending.get(message.id);
      pending.delete(message.id);
      if (message.error) waiter?.reject(new Error(message.error));
      else waiter?.resolve();
    }
    if (message.kind === "request") {
      const result = request(message.player!, message.path!, message.body!);
      process.send!({ kind: "entered", id: message.id } satisfies Message);
      void result.then((result) => {
        process.send!({ kind: "result", id: message.id, result } satisfies Message);
      });
    }
  });
  await installSeam(
    (call) =>
      new Promise<void>((resolve, reject) => {
        const id = crypto.randomUUID();
        pending.set(id, { resolve, reject });
        process.send!({ kind: "call", id, call } satisfies Message);
      }),
  );
  process.send!({ kind: "ready", id: "ready" } satisfies Message);
}
