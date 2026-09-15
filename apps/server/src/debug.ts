import { DEBUG_HTML } from "./debug-page.ts";
import { getRoomService, DataPacket_Kind } from "./livekit.ts";

export async function handleDebugRooms(): Promise<Response> {
  const roomService = getRoomService();
  if (!roomService) {
    return Response.json({ error: "LiveKit is not configured" }, { status: 503 });
  }
  try {
    const rooms = await roomService.listRooms();
    const list = rooms.map((r) => ({
      name: r.name,
      numParticipants: r.numParticipants,
      creationTime: Number(r.creationTime),
    }));
    return Response.json(list);
  } catch {
    return Response.json({ error: "Failed to list rooms" }, { status: 500 });
  }
}

export async function handleDebugSendEvent(req: Request): Promise<Response> {
  const roomService = getRoomService();
  if (!roomService) {
    return Response.json({ error: "LiveKit is not configured" }, { status: 503 });
  }
  const body = (await req.json()) as { room?: string; event?: { type?: string } };
  if (!body.room) {
    return Response.json({ error: "room is required" }, { status: 400 });
  }
  if (!body.event?.type) {
    return Response.json({ error: "event.type is required" }, { status: 400 });
  }

  try {
    const data = new TextEncoder().encode(JSON.stringify(body.event));
    await roomService.sendData(body.room, data, DataPacket_Kind.RELIABLE, {
      topic: "game_events",
    });
    return Response.json({ ok: true, type: body.event.type, room: body.room });
  } catch {
    return Response.json({ error: "Failed to send event" }, { status: 500 });
  }
}

export function handleDebugPage(): Response {
  return new Response(DEBUG_HTML, {
    headers: {
      "Content-Type": "text/html; charset=utf-8",
      "X-Content-Type-Options": "nosniff",
      "X-Frame-Options": "DENY",
      "Content-Security-Policy":
        "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'",
    },
  });
}
