import { serve } from "bun";
import { handleLivekitToken } from "./livekit.ts";
import { handleGetCharacter } from "./character.ts";
import { handleRequestCode, handleVerifyCode, handleGetMe, requireAuth } from "./auth.ts";
import { handlePreflight, withCors, checkRateLimit } from "./middleware.ts";
import {
  handleCreateActivity,
  handleListActivities,
  handleGetActivity,
  handleActivityDecision,
  handleAudioFile,
} from "./activities.ts";
import { handleGetCatchUpFeed } from "./catchup.ts";
import { handleImageAsset } from "./image-assets.ts";
import { sql } from "./db.ts";
import { handleGetActivityTemplates } from "./activity-templates-api.ts";
import { handleStorePushToken, handleInternalPush } from "./push.ts";
import { isDev } from "./env.ts";

const enableDebug = isDev && Bun.env.ENABLE_DEBUG_CONSOLE === "true";

const CHARACTER_RE = /^\/api\/character\/([^/]+)$/;
const ACTIVITY_ID_RE = /^\/api\/activities\/([a-zA-Z0-9_]+)$/;
const ACTIVITY_DECIDE_RE = /^\/api\/activities\/([a-zA-Z0-9_]+)\/decide$/;
const AUDIO_FILE_RE = /^\/api\/audio\/([a-zA-Z0-9_.-]+)$/;
const IMAGE_ASSET_RE = /^\/api\/assets\/images\/([a-zA-Z0-9_]+)$/;
const GOD_WHISPER_PLAYED_RE = /^\/api\/god-whispers\/([a-zA-Z0-9_]+)\/played$/;

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

    // --- Catch-up feed ---

    if (path === "/api/catchup" && req.method === "GET") {
      const auth = await requireAuth(req);
      if (auth instanceof Response) return withCors(auth);
      return withCors(await handleGetCatchUpFeed(req, auth.playerId));
    }

    if (
      path.startsWith("/api/god-whispers/") &&
      path.endsWith("/played") &&
      req.method === "POST"
    ) {
      const whisperMatch = path.match(GOD_WHISPER_PLAYED_RE);
      if (whisperMatch) {
        const auth = await requireAuth(req);
        if (auth instanceof Response) return withCors(auth);
        try {
          await sql`
            UPDATE god_whispers
            SET data = jsonb_set(data, '{status}', '"played"'::jsonb)
            WHERE id = ${whisperMatch[1]!} AND player_id = ${auth.playerId}
          `;
          return withCors(Response.json({ ok: true }));
        } catch {
          return withCors(Response.json({ error: "Internal server error" }, { status: 500 }));
        }
      }
    }

    if (path === "/api/activity-templates" && req.method === "GET") {
      const auth = await requireAuth(req);
      if (auth instanceof Response) return withCors(auth);
      return withCors(handleGetActivityTemplates());
    }

    // --- Push notifications ---

    if (path === "/api/push-token" && req.method === "POST") {
      const auth = await requireAuth(req);
      if (auth instanceof Response) return withCors(auth);
      return withCors(await handleStorePushToken(req, auth.playerId));
    }

    if (path === "/api/internal/push" && req.method === "POST") {
      return withCors(await handleInternalPush(req));
    }

    // --- Activity routes (auth required) ---

    if (path === "/api/activities" && req.method === "POST") {
      const auth = await requireAuth(req);
      if (auth instanceof Response) return withCors(auth);
      return withCors(await handleCreateActivity(req, auth.playerId));
    }

    if (path === "/api/activities" && req.method === "GET") {
      const auth = await requireAuth(req);
      if (auth instanceof Response) return withCors(auth);
      return withCors(await handleListActivities(req, auth.playerId));
    }

    if (path.startsWith("/api/activities/") && path.endsWith("/decide") && req.method === "POST") {
      const decideMatch = path.match(ACTIVITY_DECIDE_RE);
      if (decideMatch) {
        const auth = await requireAuth(req);
        if (auth instanceof Response) return withCors(auth);
        return withCors(await handleActivityDecision(req, auth.playerId, decideMatch[1]!));
      }
    }

    if (path.startsWith("/api/activities/") && req.method === "GET") {
      const actMatch = path.match(ACTIVITY_ID_RE);
      if (actMatch) {
        const auth = await requireAuth(req);
        if (auth instanceof Response) return withCors(auth);
        return withCors(await handleGetActivity(req, auth.playerId, actMatch[1]!));
      }
    }

    // --- File serving (unauthenticated) ---

    if (path.startsWith("/api/audio/") && req.method === "GET") {
      const audioMatch = path.match(AUDIO_FILE_RE);
      if (audioMatch) {
        return withCors(await handleAudioFile(audioMatch[1]!));
      }
    }

    if (path.startsWith("/api/assets/images/") && req.method === "GET") {
      const imgMatch = path.match(IMAGE_ASSET_RE);
      if (imgMatch) {
        return withCors(await handleImageAsset(imgMatch[1]!));
      }
    }

    // --- Debug routes (dev-only, auth required) ---

    if (enableDebug) {
      const { handleDebugPage, handleDebugRooms, handleDebugSendEvent } =
        await import("./debug.ts");

      const debugAuth = await requireAuth(req);
      if (debugAuth instanceof Response) return withCors(debugAuth);

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
