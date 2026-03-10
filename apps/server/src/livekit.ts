import {
  AccessToken,
  AgentDispatchClient,
  RoomServiceClient,
  DataPacket_Kind,
} from "livekit-server-sdk";
import { TrackSource } from "@livekit/protocol";
import { logError } from "./env.ts";
import { parseJsonBody } from "./middleware.ts";
export { DataPacket_Kind };

// --- Lazy LiveKit client initialization ---
// Clients are created on first use so the server can start without LiveKit credentials
// (e.g. in CI/e2e where only the REST API is needed).

interface LivekitClients {
  url: string;
  apiKey: string;
  apiSecret: string;
  roomService: RoomServiceClient;
  dispatchClient: AgentDispatchClient;
}

let _clients: LivekitClients | null = null;

function getLivekitClients(): LivekitClients | null {
  if (_clients) return _clients;
  const url = Bun.env.LIVEKIT_URL;
  const apiKey = Bun.env.LIVEKIT_API_KEY;
  const apiSecret = Bun.env.LIVEKIT_API_SECRET;
  if (!url || !apiKey || !apiSecret) return null;
  _clients = {
    url,
    apiKey,
    apiSecret,
    roomService: new RoomServiceClient(url.replace("wss://", "https://"), apiKey, apiSecret),
    dispatchClient: new AgentDispatchClient(url, apiKey, apiSecret),
  };
  return _clients;
}

export function getRoomService(): RoomServiceClient | null {
  return getLivekitClients()?.roomService ?? null;
}

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

export async function handleLivekitToken(req: Request, playerId: string): Promise<Response> {
  const clients = getLivekitClients();
  if (!clients) {
    return Response.json(
      { error: "LiveKit is not configured (LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET)" },
      { status: 503 },
    );
  }

  const body = await parseJsonBody<{ room_name?: string }>(req);
  if (!body) {
    return Response.json({ error: "Invalid Content-Type" }, { status: 415 });
  }
  const room_name = body.room_name;
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
    await clients.roomService.createRoom({ name: room_name });
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e);
    if (!msg.includes("already exists") && !msg.includes("already being created")) {
      logError(`Failed to create LiveKit room "${room_name}":`, e);
    }
  }

  const token = new AccessToken(clients.apiKey, clients.apiSecret, {
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
    await clients.dispatchClient.createDispatch(room_name, "divineruin-dm", {
      metadata: JSON.stringify({ player_id }),
    });
    console.log(`Dispatched DM agent to room "${room_name}"`);
  } catch (e: unknown) {
    logError("Failed to dispatch DM agent:", e);
  }

  return Response.json({
    token: jwt,
    room_name,
    url: clients.url,
  });
}
