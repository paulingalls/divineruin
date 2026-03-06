import { serve } from "bun";
import { handleLivekitToken } from "./livekit.ts";
import { handleGetCharacter } from "./character.ts";
import { handleRequestCode, handleVerifyCode, handleGetMe, requireAuth } from "./auth.ts";
import { handlePreflight, withCors, checkRateLimit } from "./middleware.ts";
import { isDev } from "./env.ts";

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

    // --- Unauthenticated routes ---

    if (path === "/api/auth/request-code" && req.method === "POST") {
      return withCors(await handleRequestCode(req));
    }
    if (path === "/api/auth/verify-code" && req.method === "POST") {
      return withCors(await handleVerifyCode(req));
    }

    // --- Authenticated routes ---

    if (path === "/api/me" && req.method === "GET") {
      return withCors(await handleGetMe(req));
    }

    if (path === "/api/livekit/token" && req.method === "POST") {
      const auth = await requireAuth(req);
      if (auth instanceof Response) return withCors(auth);
      return withCors(await handleLivekitToken(req, auth.playerId));
    }

    if (path.startsWith("/api/character/") && req.method === "GET") {
      const charMatch = path.match(CHARACTER_RE);
      if (charMatch) {
        const auth = await requireAuth(req);
        if (auth instanceof Response) return withCors(auth);
        return withCors(await handleGetCharacter(req, auth.playerId));
      }
    }

    // --- Debug routes (dev-only, no auth) ---

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
