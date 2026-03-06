import {
  AccessToken,
  AgentDispatchClient,
  RoomServiceClient,
  DataPacket_Kind,
} from "livekit-server-sdk";
import { TrackSource } from "@livekit/protocol";
import { requireEnv, logError } from "./env.ts";
export { DataPacket_Kind };

const LIVEKIT_URL = requireEnv("LIVEKIT_URL");
const LIVEKIT_API_KEY = requireEnv("LIVEKIT_API_KEY");
const LIVEKIT_API_SECRET = requireEnv("LIVEKIT_API_SECRET");

const VALID_ID = /^[a-zA-Z0-9_-]+$/;
const MAX_ID_LENGTH = 128;

function validateId(value: string, field: string): string | null {
  if (value.length > MAX_ID_LENGTH) {
    return `${field} exceeds maximum length of ${MAX_ID_LENGTH} characters`;
  }
  if (!VALID_ID.test(value)) {
    return `${field} contains invalid characters (allowed: a-z, A-Z, 0-9, _, -)`;
  }
  return null;
}

export const roomService = new RoomServiceClient(
  LIVEKIT_URL.replace("wss://", "https://"),
  LIVEKIT_API_KEY,
  LIVEKIT_API_SECRET,
);

const dispatchClient = new AgentDispatchClient(LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET);

export async function handleLivekitToken(req: Request, playerId: string): Promise<Response> {
  const body = (await req.json()) as {
    room_name?: string;
  };
  const { room_name } = body;
  const player_id = playerId;

  if (!room_name) {
    return Response.json({ error: "room_name is required" }, { status: 400 });
  }

  const playerIdError = validateId(player_id, "player_id");
  if (playerIdError) {
    return Response.json({ error: playerIdError }, { status: 400 });
  }

  const roomNameError = validateId(room_name, "room_name");
  if (roomNameError) {
    return Response.json({ error: roomNameError }, { status: 400 });
  }

  try {
    await roomService.createRoom({ name: room_name });
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e);
    if (!msg.includes("already exists") && !msg.includes("already being created")) {
      logError(`Failed to create LiveKit room "${room_name}":`, e);
    }
  }

  const token = new AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET, {
    identity: player_id,
    name: player_id,
  });
  token.addGrant({
    roomJoin: true,
    room: room_name,
    canPublish: true,
    canSubscribe: true,
    canPublishData: false,
    canPublishSources: [TrackSource.MICROPHONE],
  });

  const jwt = await token.toJwt();

  try {
    await dispatchClient.createDispatch(room_name, "divineruin-dm", {
      metadata: JSON.stringify({ player_id }),
    });
    console.log(`Dispatched DM agent to room "${room_name}"`);
  } catch (e: unknown) {
    logError("Failed to dispatch DM agent:", e);
  }

  return Response.json({
    token: jwt,
    room_name,
    url: LIVEKIT_URL,
  });
}
