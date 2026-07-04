const KEY_PREFIX = "invite:";

/** Store code → room mapping in Valkey, expiring after ttlSeconds. */
export async function putInvite(code: string, roomName: string, ttlSeconds: number): Promise<void> {
  await Bun.redis.set(KEY_PREFIX + code, roomName, "EX", ttlSeconds);
}

/** Resolve an invite code to its room name, or null if unknown/expired. */
export async function getInvite(code: string): Promise<string | null> {
  return await Bun.redis.get(KEY_PREFIX + code);
}
