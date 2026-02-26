import { serve } from "bun";
import { AccessToken, RoomServiceClient } from "livekit-server-sdk";
import index from "./index.html";

const LIVEKIT_URL = process.env.LIVEKIT_URL ?? "";
const LIVEKIT_API_KEY = process.env.LIVEKIT_API_KEY ?? "";
const LIVEKIT_API_SECRET = process.env.LIVEKIT_API_SECRET ?? "";

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

const roomService = createRoomService();

export async function handleLivekitToken(req: Request): Promise<Response> {
  const body = (await req.json()) as {
    player_id?: string;
    room_name?: string;
  };
  const { player_id, room_name } = body;

  if (!player_id || !room_name) {
    return Response.json(
      { error: "player_id and room_name are required" },
      { status: 400 },
    );
  }

  if (!roomService) {
    return Response.json(
      { error: "LiveKit credentials not configured" },
      { status: 500 },
    );
  }

  try {
    await roomService.createRoom({ name: room_name });
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e);
    if (!msg.includes("already exists") && !msg.includes("already being created")) {
      console.error(`Failed to create LiveKit room "${room_name}":`, msg);
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
  });

  const jwt = await token.toJwt();

  return Response.json({
    token: jwt,
    room_name,
    url: LIVEKIT_URL,
  });
}

const server = serve({
  routes: {
    "/*": index,

    "/api/hello": {
      async GET(req) {
        return Response.json({
          message: "Hello, world!",
          method: "GET",
        });
      },
      async PUT(req) {
        return Response.json({
          message: "Hello, world!",
          method: "PUT",
        });
      },
    },

    "/api/hello/:name": async (req) => {
      const name = req.params.name;
      return Response.json({
        message: `Hello, ${name}!`,
      });
    },

    "/api/livekit/token": {
      async POST(req) {
        return handleLivekitToken(req);
      },
    },
  },

  development: process.env.NODE_ENV !== "production" && {
    hmr: true,
    console: true,
  },
});

console.log(`Server running at ${server.url}`);
