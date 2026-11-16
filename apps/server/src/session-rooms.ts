import { ServerError, type AgentDispatchClient, type RoomServiceClient } from "livekit-server-sdk";
import { logError, requireEnv } from "./env.ts";

const OWNERSHIP_SECONDS = 7200;
// Four bounded RPCs include dispatch-failure cleanup after a takeover.
const LEASE_SECONDS = 60;
const CONTENTION_MS = 35000;
const playerKey = (player: string) => `player_room:${player}`;
const ownerKey = (room: string) => `room_owner:${room}`;
const markerKey = (room: string) => `room_dispatched:${room}`;
const playerLock = (player: string) => `session_lock:player:${player}`;
const roomLock = (room: string) => `session_lock:room:${room}`;

async function evalLua(script: string, keys: string[], args: string[] = []): Promise<unknown> {
  requireEnv("REDIS_URL");
  return Bun.redis.send("EVAL", [script, String(keys.length), ...keys, ...args]);
}

const CLAIM = `
local old = redis.call('GET', KEYS[1]) or ''
local locks = {KEYS[3], KEYS[4]}
if old ~= '' then table.insert(locks, 'session_lock:room:' .. old) end
for _, key in ipairs(locks) do
  if redis.call('EXISTS', key) == 1 then return {'busy'} end
end
local owner = redis.call('GET', KEYS[2])
if owner and owner ~= ARGV[1] then return {'foreign'} end
for _, key in ipairs(locks) do redis.call('SET', key, ARGV[2], 'EX', ARGV[3]) end
return {'claimed', old}
`;
const FENCE = `
for _, key in ipairs(KEYS) do
  if redis.call('GET', key) ~= ARGV[1] then return 0 end
end
`;

class TransitionError extends Error {
  constructor(
    message: string,
    readonly status = 503,
  ) {
    super(message);
  }
}

async function claim(player: string, room: string) {
  const token = crypto.randomUUID();
  const deadline = Date.now() + CONTENTION_MS;
  while (Date.now() < deadline) {
    const [status, old = ""] = (await evalLua(
      CLAIM,
      [playerKey(player), ownerKey(room), playerLock(player), roomLock(room)],
      [player, token, String(LEASE_SECONDS)],
    )) as string[];
    if (status === "foreign")
      throw new TransitionError("This room belongs to another player.", 403);
    if (status === "claimed") {
      const locks = [
        ...new Set([playerLock(player), roomLock(room), ...(old ? [roomLock(old)] : [])]),
      ];
      const mutate = async (script = "return 1", args: string[] = []) => {
        const result = await evalLua(FENCE + script, locks, [token, ...args]);
        if (Number(result) !== 1)
          throw new TransitionError("The room transition expired. Try again.");
      };
      return {
        old,
        mutate,
        release: () =>
          evalLua(
            `
        for _, key in ipairs(KEYS) do
          if redis.call('GET', key) == ARGV[1] then redis.call('DEL', key) end
        end
        return 1`,
            locks,
            [token],
          ),
      };
    }
    await Bun.sleep(25);
  }
  throw new TransitionError("Another room request is still running. Try again.");
}

export async function ownsDispatchedRoom(player: string, room: string): Promise<boolean> {
  return (
    Number(
      await evalLua(
        `
    if redis.call('GET', KEYS[1]) == ARGV[1]
      and redis.call('GET', KEYS[2]) == ARGV[2]
      and redis.call('GET', KEYS[3]) == ARGV[2] then return 1 end
    return 0`,
        [playerKey(player), ownerKey(room), markerKey(room)],
        [room, player],
      ),
    ) === 1
  );
}

interface Clients {
  roomService: RoomServiceClient;
  dispatchClient: AgentDispatchClient;
}

export async function joinPlayerRoom(
  clients: Clients,
  player: string,
  room: string,
  mint: () => Promise<string>,
): Promise<{ token: string } | { error: string; status: number }> {
  let transition: Awaited<ReturnType<typeof claim>> | undefined;
  let provisional = false;
  let created = false;
  try {
    transition = await claim(player, room);
    const { old, mutate } = transition;
    const rpc = async (operation: () => Promise<unknown>) => {
      await mutate();
      await operation();
      await mutate();
    };
    const removeRoom = async (name: string) =>
      rpc(async () => {
        try {
          await clients.roomService.deleteRoom(name);
        } catch (error) {
          if (!(error instanceof ServerError && error.code === "not_found")) throw error;
        }
      });
    if (!(await ownsDispatchedRoom(player, room))) {
      if (old && old !== room) {
        await removeRoom(old);
        await mutate(
          `
          if redis.call('GET', ARGV[2]) == ARGV[3] then redis.call('DEL', ARGV[2]) end
          if redis.call('GET', ARGV[4]) == ARGV[5] then redis.call('DEL', ARGV[4], ARGV[6]) end
          return 1`,
          [playerKey(player), old, ownerKey(old), player, markerKey(old)],
        );
      }
      await mutate(
        `
        redis.call('SET', ARGV[2], ARGV[3], 'EX', ARGV[6])
        redis.call('SET', ARGV[4], ARGV[5], 'EX', ARGV[6])
        redis.call('DEL', ARGV[7])
        return 1`,
        [
          playerKey(player),
          room,
          ownerKey(room),
          player,
          String(OWNERSHIP_SECONDS),
          markerKey(room),
        ],
      );
      provisional = true;
      await rpc(() => clients.roomService.createRoom({ name: room }));
      created = true;
      try {
        await rpc(() =>
          clients.dispatchClient.createDispatch(room, "divineruin-dm", {
            metadata: JSON.stringify({ player_id: player }),
          }),
        );
      } catch (error) {
        logError(`Failed to dispatch DM to "${room}":`, error);
        throw new TransitionError("The DM could not join. Try again.");
      }
      await mutate(
        `
        for _, key in ipairs({ARGV[2], ARGV[3], ARGV[4]}) do
          redis.call('EXPIRE', key, ARGV[6])
        end
        redis.call('SET', ARGV[4], ARGV[5], 'EX', ARGV[6])
        return 1`,
        [playerKey(player), ownerKey(room), markerKey(room), player, String(OWNERSHIP_SECONDS)],
      );
      provisional = false;
    }
    await mutate();
    const token = await mint();
    await mutate();
    return { token };
  } catch (error) {
    logError(`Room transition failed for "${room}":`, error);
    if (transition && provisional) {
      try {
        await transition.mutate();
        if (created) {
          try {
            await clients.roomService.deleteRoom(room);
          } catch (cleanupError) {
            if (!(cleanupError instanceof ServerError && cleanupError.code === "not_found")) {
              logError(`Failed to clean up LiveKit room "${room}":`, cleanupError);
            }
          }
        }
        await transition.mutate(
          `
          if redis.call('GET', ARGV[2]) == ARGV[3] then redis.call('DEL', ARGV[2]) end
          if redis.call('GET', ARGV[4]) == ARGV[5] then redis.call('DEL', ARGV[4], ARGV[6]) end
          return 1`,
          [playerKey(player), room, ownerKey(room), player, markerKey(room)],
        );
      } catch (cleanupError) {
        logError(`Room cleanup lost authority for "${room}":`, cleanupError);
      }
    }
    return {
      status: error instanceof TransitionError ? error.status : 503,
      error:
        error instanceof TransitionError
          ? error.message
          : "The room could not be opened. Try again.",
    };
  } finally {
    await transition?.release();
  }
}
