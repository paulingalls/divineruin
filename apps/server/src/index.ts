import { serve } from "bun";
import { handleLivekitToken } from "./livekit.ts";
import { handleGetCharacter } from "./character.ts";
import { handlePreflight, withCors, checkRateLimit } from "./middleware.ts";

const isDev = process.env.NODE_ENV !== "production";
const enableDebug = isDev && Bun.env.ENABLE_DEBUG_CONSOLE === "true";

const CHARACTER_RE = /^\/api\/character\/([^/]+)$/;

const server = serve({
  port: Number(process.env.PORT ?? 3001),
  async fetch(req) {
    const url = new URL(req.url);
    const path = url.pathname;

    if (req.method === "OPTIONS") {
      return handlePreflight();
    }

    const ip = server.requestIP(req)?.address ?? "unknown";
    const rateLimited = checkRateLimit(ip, path);
    if (rateLimited) return rateLimited;

    if (path === "/api/livekit/token" && req.method === "POST") {
      return withCors(await handleLivekitToken(req));
    }

    const charMatch = path.match(CHARACTER_RE);
    if (charMatch && req.method === "GET") {
      return withCors(await handleGetCharacter(req, charMatch[1]!));
    }

    if (enableDebug) {
      const { handleDebugPage, handleDebugRooms, handleDebugSendEvent } =
        await import("./debug.ts");

      if (path === "/debug" && req.method === "GET") {
        return withCors(handleDebugPage());
      }
      if (path === "/api/debug/rooms" && req.method === "GET") {
        return withCors(await handleDebugRooms());
      }
      if (path === "/api/debug/event" && req.method === "POST") {
        return withCors(await handleDebugSendEvent(req));
      }
    }

    return withCors(Response.json({ error: "Not found" }, { status: 404 }));
  },
});

console.log(`Server running at ${server.url.href}`);
