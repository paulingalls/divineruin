import { serve } from "bun";
import { handleLivekitToken } from "./livekit.ts";
import { handleGetCharacter } from "./character.ts";

const isDev = process.env.NODE_ENV !== "production";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const routes: Record<string, any> = {
  "/api/livekit/token": {
    async POST(req: Request) {
      return handleLivekitToken(req);
    },
  },
  "/api/character/:playerId": {
    async GET(req: Request & { params: { playerId: string } }) {
      return handleGetCharacter(req, req.params.playerId);
    },
  },
};

if (isDev) {
  const { handleDebugPage, handleDebugRooms, handleDebugSendEvent } = await import("./debug.ts");
  routes["/debug"] = {
    GET() {
      return handleDebugPage();
    },
  };
  routes["/api/debug/rooms"] = {
    async GET() {
      return handleDebugRooms();
    },
  };
  routes["/api/debug/event"] = {
    async POST(req: Request) {
      return handleDebugSendEvent(req);
    },
  };
}

const server = serve({
  port: Number(process.env.PORT ?? 3001),
  routes,
});

console.log(`Server running at ${server.url.href}`);
