// Pure invite-link logic (no React Native imports) so bun test can exercise it directly —
// @/utils/api pulls in expo-constants + secure-kv (native-only) and would break at module load.

export const INVITE_SCHEME = "divineruin";
export const INVITE_JOIN_PATH = "join";

export function buildInviteUrl(code: string): string {
  return `${INVITE_SCHEME}://${INVITE_JOIN_PATH}?code=${encodeURIComponent(code)}`;
}

export async function fetchInviteUrl(
  roomName: string,
  apiBase: string,
  headers: Record<string, string>,
): Promise<string> {
  const res = await fetch(`${apiBase}/api/livekit/invite`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...headers },
    body: JSON.stringify({ room_name: roomName }),
  });

  if (!res.ok) {
    const err = (await res.json().catch(() => ({}))) as { error?: string };
    throw new Error(err.error ?? "invite failed");
  }

  const data = (await res.json()) as { code: string; expires_in: number };
  return buildInviteUrl(data.code);
}
