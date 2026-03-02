import { serve } from "bun";
import { handleLivekitToken } from "./livekit.ts";

const server = serve({
  port: Number(process.env.PORT ?? 3001),
  routes: {
    "/api/livekit/token": {
      async POST(req) {
        return handleLivekitToken(req);
      },
    },
  },
});

console.log(`Server running at ${server.url}`);
