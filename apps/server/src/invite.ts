import { validateId } from "./livekit.ts";
import { parseJsonBody } from "./middleware.ts";
import { putInvite } from "./invite-store.ts";

const INVITE_TTL_SECONDS = 1800;

/** High-entropy, URL-safe invite code — the capability secret for redeem. */
export function generateCode(): string {
  return Buffer.from(crypto.getRandomValues(new Uint8Array(8))).toString("base64url");
}

export async function handleCreateInvite(req: Request, _playerId: string): Promise<Response> {
  const body = await parseJsonBody<{ room_name?: string }>(req);
  if (!body) {
    return Response.json({ error: "Invalid Content-Type" }, { status: 415 });
  }

  const room_name = body.room_name;
  if (!room_name) {
    return Response.json({ error: "room_name is required" }, { status: 400 });
  }

  const roomNameError = validateId(room_name, "room_name");
  if (roomNameError) {
    return Response.json({ error: roomNameError }, { status: 400 });
  }

  const code = generateCode();
  await putInvite(code, room_name, INVITE_TTL_SECONDS);

  return Response.json({ code, expires_in: INVITE_TTL_SECONDS });
}
