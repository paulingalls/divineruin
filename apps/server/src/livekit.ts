import {
  AccessToken,
  AgentDispatchClient,
  RoomServiceClient,
  DataPacket_Kind,
} from "livekit-server-sdk";
import { TrackSource } from "@livekit/protocol";
export { DataPacket_Kind };

function requireEnv(name: string): string {
  const value = Bun.env[name];
  if (!value) {
    throw new Error(`${name} is not set`);
  }
  return value;
}

const LIVEKIT_URL = requireEnv("LIVEKIT_URL");
const LIVEKIT_API_KEY = requireEnv("LIVEKIT_API_KEY");
const LIVEKIT_API_SECRET = requireEnv("LIVEKIT_API_SECRET");

const isDev = process.env.NODE_ENV !== "production";

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

function createRoomService(): RoomServiceClient | null {
  if (!LIVEKIT_URL || !LIVEKIT_API_KEY || !LIVEKIT_API_SECRET) {
    return null;
  }
  return new RoomServiceClient(
    LIVEKIT_URL.replace("wss://", "https://"),
    LIVEKIT_API_KEY,
    LIVEKIT_API_SECRET,
  );
}

export const roomService = createRoomService();

function createDispatchClient(): AgentDispatchClient | null {
  if (!LIVEKIT_URL || !LIVEKIT_API_KEY || !LIVEKIT_API_SECRET) {
    return null;
  }
  return new AgentDispatchClient(LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET);
}

const dispatchClient = createDispatchClient();

export async function handleLivekitToken(req: Request): Promise<Response> {
  const body = (await req.json()) as {
    player_id?: string;
    room_name?: string;
  };
  const { player_id, room_name } = body;

  if (!player_id || !room_name) {
    return Response.json({ error: "player_id and room_name are required" }, { status: 400 });
  }

  const playerIdError = validateId(player_id, "player_id");
  if (playerIdError) {
    return Response.json({ error: playerIdError }, { status: 400 });
  }

  const roomNameError = validateId(room_name, "room_name");
  if (roomNameError) {
    return Response.json({ error: roomNameError }, { status: 400 });
  }

  if (!roomService) {
    return Response.json({ error: "LiveKit credentials not configured" }, { status: 500 });
  }

  try {
    await roomService.createRoom({ name: room_name });
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e);
    if (!msg.includes("already exists") && !msg.includes("already being created")) {
      if (isDev) {
        console.error(`Failed to create LiveKit room "${room_name}":`, e);
      } else {
        console.error(`Failed to create LiveKit room "${room_name}":`, msg);
      }
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

  if (dispatchClient) {
    try {
      await dispatchClient.createDispatch(room_name, "divineruin-dm", {
        metadata: JSON.stringify({ player_id }),
      });
      console.log(`Dispatched DM agent to room "${room_name}"`);
    } catch (e: unknown) {
      if (isDev) {
        console.error("Failed to dispatch DM agent:", e);
      } else {
        console.error("Failed to dispatch DM agent:", e instanceof Error ? e.message : "unknown");
      }
    }
  }

  return Response.json({
    token: jwt,
    room_name,
    url: LIVEKIT_URL,
  });
}
