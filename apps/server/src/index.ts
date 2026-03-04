import { serve } from "bun";
import { handleLivekitToken } from "./livekit.ts";
import { handleGetCharacter } from "./character.ts";

const server = serve({
  port: Number(process.env.PORT ?? 3001),
  routes: {
    "/api/livekit/token": {
      async POST(req) {
        return handleLivekitToken(req);
      },
    },
    "/api/character/:playerId": {
      async GET(req) {
        return handleGetCharacter(req, req.params.playerId);
      },
    },
  },
});

console.log(`Server running at ${server.url}`);
