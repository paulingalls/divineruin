import { sql } from "./db.ts";
import { parseJsonb } from "./parse-jsonb.ts";
import { logError } from "./env.ts";

// Worker-internal bookkeeping kept in async_activities.data that must never reach
// clients. resolving_at/resolve_attempts are the transient CAS markers that
// mark_resolved strips in SQL on the terminal write, but they're present during the
// in_progress/resolving retry window. narration_segments is the worker's cached
// per-character TTS breakdown (dialogue_parser.Segment: character/emotion/text); it
// is NOT stripped by mark_resolved, so it persists verbatim on resolved rows — the
// client only needs narration_audio_url + narration_text. Add any future worker-only
// field here (concern 06edbc8f3eef).
// 'slot' is the internal slot-accounting marker (the slot the activity consumes;
// stamped 'training' for an Artificer borrowed-slot craft). countActiveBySlot in
// activity_create.ts reads it from the DB; clients have no use for it and key off
// activity_type.
const INTERNAL_ONLY_FIELDS = [
  "resolving_at",
  "resolve_attempts",
  "narration_segments",
  "slot",
] as const;

/**
 * Sanitize an async-activity row on the way out to clients: normalize the
 * worker-internal 'resolving' transient state to 'in_progress' (typed consumers
 * only know in_progress/resolved), and drop worker-internal bookkeeping fields.
 * Defense-in-depth at the API egress boundary.
 */
function normalizeActivityStatus<T extends Record<string, unknown>>(activity: T): T {
  const sanitized: Record<string, unknown> = { ...activity };
  if (sanitized.status === "resolving") {
    sanitized.status = "in_progress";
  }
  for (const field of INTERNAL_ONLY_FIELDS) {
    delete sanitized[field];
  }
  return sanitized as T;
}

export async function handleListActivities(req: Request, playerId: string): Promise<Response> {
  try {
    const url = new URL(req.url);
    const statusFilter = url.searchParams.get("status");

    let rows: { id: string; data: unknown }[];
    if (statusFilter === "in_progress") {
      // Widen to also match worker-claimed rows so clients polling for
      // in_progress don't miss activities mid-resolution.
      rows = await sql`
        SELECT id, data FROM async_activities
        WHERE player_id = ${playerId} AND data->>'status' IN ('in_progress', 'resolving')
        ORDER BY created_at DESC
        LIMIT 100
      `;
    } else if (statusFilter) {
      rows = await sql`
        SELECT id, data FROM async_activities
        WHERE player_id = ${playerId} AND data->>'status' = ${statusFilter}
        ORDER BY created_at DESC
        LIMIT 100
      `;
    } else {
      rows = await sql`
        SELECT id, data FROM async_activities
        WHERE player_id = ${playerId}
        ORDER BY created_at DESC
        LIMIT 100
      `;
    }

    const activities = rows.map((row) => {
      const data = parseJsonb(row.data);
      return normalizeActivityStatus({ id: row.id, ...data });
    });

    return Response.json({ activities });
  } catch (err) {
    logError("[activities] list failed:", err);
    return Response.json({ error: "Internal server error" }, { status: 500 });
  }
}

export async function handleGetActivity(
  _req: Request,
  playerId: string,
  activityId: string,
): Promise<Response> {
  try {
    const rows: { id: string; player_id: string; data: unknown }[] = await sql`
      SELECT id, player_id, data FROM async_activities WHERE id = ${activityId}
    `;

    if (rows.length === 0) {
      return Response.json({ error: "Activity not found" }, { status: 404 });
    }

    const row = rows[0]!;
    if (row.player_id !== playerId) {
      return Response.json({ error: "Activity not found" }, { status: 404 });
    }

    const data = parseJsonb(row.data);
    return Response.json(normalizeActivityStatus({ id: row.id, ...data }));
  } catch (err) {
    logError("[activities] get failed:", err);
    return Response.json({ error: "Internal server error" }, { status: 500 });
  }
}

export async function handleActivityDecision(
  req: Request,
  playerId: string,
  activityId: string,
): Promise<Response> {
  try {
    const body = (await req.json().catch(() => null)) as {
      decision_id?: string;
    } | null;

    if (!body?.decision_id) {
      return Response.json({ error: "decision_id is required" }, { status: 400 });
    }

    const txnResult = await sql.begin(async (tx) => {
      const rows: { id: string; player_id: string; data: unknown }[] = await tx`
        SELECT id, player_id, data FROM async_activities WHERE id = ${activityId} FOR UPDATE
      `;

      if (rows.length === 0) {
        return { error: "Activity not found", httpStatus: 404 } as const;
      }

      const row = rows[0]!;
      if (row.player_id !== playerId) {
        return { error: "Activity not found", httpStatus: 404 } as const;
      }

      const data = parseJsonb(row.data);
      if (data.status !== "resolved") {
        return { error: "Activity is not resolved yet", httpStatus: 400 } as const;
      }

      const options = (data.decision_options as { id: string }[] | null) ?? [];
      const chosen = options.find((opt) => opt.id === body.decision_id);
      if (!chosen) {
        return { error: "Invalid decision", httpStatus: 400 } as const;
      }

      const outcome = data.outcome as Record<string, unknown> | null;
      if (outcome && data.activity_type === "crafting") {
        const craftedItemId = outcome.crafted_item_id as string | null;
        if (craftedItemId && body.decision_id === "keep") {
          await tx`
            INSERT INTO player_inventory (player_id, item_id, data)
            VALUES (${playerId}, ${craftedItemId}, ${{ quantity: 1, equipped: false }})
            ON CONFLICT (player_id, item_id)
            DO UPDATE SET data = jsonb_set(
              player_inventory.data,
              '{quantity}',
              (COALESCE((player_inventory.data->>'quantity')::int, 0) + 1)::text::jsonb
            )
          `;
        }
      }

      await tx`
        UPDATE async_activities
        SET data = jsonb_set(
          jsonb_set(data, '{status}', '"collected"'),
          '{decision}', ${JSON.stringify(body.decision_id)}::jsonb
        )
        WHERE id = ${activityId}
      `;

      return { activityId, decision: body.decision_id } as const;
    });

    if ("error" in txnResult) {
      return Response.json({ error: txnResult.error }, { status: txnResult.httpStatus });
    }

    return Response.json({
      id: txnResult.activityId,
      status: "collected",
      decision: txnResult.decision,
    });
  } catch (err) {
    logError("[activities] decision failed:", err);
    return Response.json({ error: "Internal server error" }, { status: 500 });
  }
}

const AUDIO_DIR = Bun.env.ASYNC_AUDIO_DIR ?? `${import.meta.dir}/../../audio`;

export async function handleAudioFile(filename: string): Promise<Response> {
  // Reject path traversal: only allow alphanumeric, underscores, hyphens, and a single dot for extension
  if (!/^[a-zA-Z0-9_-]+\.[a-zA-Z0-9]+$/.test(filename)) {
    return Response.json({ error: "Invalid filename" }, { status: 400 });
  }

  const file = Bun.file(`${AUDIO_DIR}/${filename}`);
  if (!(await file.exists())) {
    return Response.json({ error: "File not found" }, { status: 404 });
  }

  const contentType = filename.endsWith(".mp3") ? "audio/mpeg" : "audio/wav";
  return new Response(file, {
    headers: {
      "Content-Type": contentType,
      "Cache-Control": "public, max-age=86400",
    },
  });
}
