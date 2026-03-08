import { sql } from "./db.ts";
import { logError } from "./env.ts";
import {
  CRAFTING_RECIPES,
  TRAINING_PROGRAMS,
  ERRAND_TEMPLATES,
  VALID_ACTIVITY_TYPES,
} from "./activity_templates.ts";

const MAX_CONCURRENT = 4;

function randomInt(min: number, max: number): number {
  return Math.floor(Math.random() * (max - min + 1)) + min;
}

export async function handleCreateActivity(req: Request, playerId: string): Promise<Response> {
  try {
    const body = (await req.json().catch(() => null)) as {
      type?: string;
      parameters?: Record<string, unknown>;
    } | null;

    if (!body?.type) {
      return Response.json({ error: "type is required" }, { status: 400 });
    }

    if (!VALID_ACTIVITY_TYPES.has(body.type)) {
      return Response.json({ error: "Invalid activity type" }, { status: 400 });
    }

    const params = body.parameters ?? {};

    // Validate type-specific parameters before entering the transaction
    let durationMin: number;
    let durationMax: number;
    let activityParams: Record<string, unknown>;
    let materialsToConsume: string[] = [];

    if (body.type === "crafting") {
      const recipeId = params.recipe_id as string | undefined;
      if (!recipeId) {
        return Response.json({ error: "recipe_id is required for crafting" }, { status: 400 });
      }
      const recipe = CRAFTING_RECIPES[recipeId];
      if (!recipe) {
        return Response.json({ error: "Unknown recipe" }, { status: 400 });
      }

      durationMin = recipe.duration_min_seconds;
      durationMax = recipe.duration_max_seconds;
      materialsToConsume = recipe.required_materials;
      activityParams = {
        recipe_id: recipe.id,
        result_item_id: recipe.result_item_id,
        result_item_name: recipe.result_item_name,
        required_materials: recipe.required_materials,
        skill: recipe.skill,
        dc: recipe.dc,
        npc_id: recipe.npc_id,
      };
    } else if (body.type === "training") {
      const programId = params.program_id as string | undefined;
      if (!programId) {
        return Response.json({ error: "program_id is required for training" }, { status: 400 });
      }
      const program = TRAINING_PROGRAMS[programId];
      if (!program) {
        return Response.json({ error: "Unknown training program" }, { status: 400 });
      }

      durationMin = program.duration_min_seconds;
      durationMax = program.duration_max_seconds;
      activityParams = {
        program_id: program.id,
        stat: program.stat,
        skill: program.skill,
        dc: program.dc,
        mentor_id: program.mentor_id,
      };
    } else {
      // companion_errand
      const errandType = params.errand_type as string | undefined;
      const destination = params.destination as string | undefined;
      if (!errandType) {
        return Response.json({ error: "errand_type is required" }, { status: 400 });
      }
      const template = ERRAND_TEMPLATES[errandType];
      if (!template) {
        return Response.json({ error: "Unknown errand type" }, { status: 400 });
      }
      if (!destination) {
        return Response.json({ error: "destination is required" }, { status: 400 });
      }
      if (!template.valid_destinations.includes(destination)) {
        return Response.json({ error: "Invalid destination for errand type" }, { status: 400 });
      }

      durationMin = template.duration_min_seconds;
      durationMax = template.duration_max_seconds;
      activityParams = {
        errand_type: errandType,
        destination,
      };
    }

    // Atomic transaction: check concurrent count, verify+consume materials, insert activity
    const txnResult = await sql.begin(async (tx) => {
      // Lock player's in-progress activities to prevent race conditions
      const countRows: { cnt: number }[] = await tx`
        SELECT COUNT(*)::int AS cnt FROM async_activities
        WHERE player_id = ${playerId} AND data->>'status' = 'in_progress'
        FOR UPDATE
      `;
      const activeCount = countRows[0]?.cnt ?? 0;
      if (activeCount >= MAX_CONCURRENT) {
        return { error: `Maximum ${MAX_CONCURRENT} concurrent activities allowed` } as const;
      }

      // Verify and consume materials atomically for crafting
      if (materialsToConsume.length > 0) {
        const ownedRows: { item_id: string }[] = await tx`
          SELECT item_id FROM player_inventory
          WHERE player_id = ${playerId} AND item_id = ANY(${materialsToConsume})
          FOR UPDATE
        `;
        const ownedSet = new Set(ownedRows.map((r) => r.item_id));
        for (const matId of materialsToConsume) {
          if (!ownedSet.has(matId)) {
            return { error: `Missing required material: ${matId}` } as const;
          }
        }
        // Consume materials
        for (const matId of materialsToConsume) {
          await tx`
            DELETE FROM player_inventory
            WHERE player_id = ${playerId} AND item_id = ${matId}
          `;
        }
      }

      const now = new Date();
      const durationSeconds = randomInt(durationMin, durationMax);
      const resolveAt = new Date(now.getTime() + durationSeconds * 1000);
      const activityId = `activity_${crypto.randomUUID().replace(/-/g, "").slice(0, 12)}`;

      const data = {
        status: "in_progress",
        activity_type: body.type,
        start_time: now.toISOString(),
        duration_min_seconds: durationMin,
        duration_max_seconds: durationMax,
        resolve_at: resolveAt.toISOString(),
        parameters: activityParams,
        outcome: null,
        narration_text: null,
        narration_audio_url: null,
        decision_options: null,
      };

      await tx`
        INSERT INTO async_activities (id, player_id, data)
        VALUES (${activityId}, ${playerId}, ${JSON.stringify(data)})
      `;

      return { activityId, resolveAt: resolveAt.toISOString() } as const;
    });

    if ("error" in txnResult) {
      return Response.json({ error: txnResult.error }, { status: 400 });
    }

    return Response.json({
      activity_id: txnResult.activityId,
      status: "in_progress",
      resolve_at_estimate: txnResult.resolveAt,
    });
  } catch (err) {
    logError("[activities] create failed:", err);
    return Response.json({ error: "Internal server error" }, { status: 500 });
  }
}

export async function handleListActivities(req: Request, playerId: string): Promise<Response> {
  try {
    const url = new URL(req.url);
    const statusFilter = url.searchParams.get("status");

    let rows: { id: string; data: unknown }[];
    if (statusFilter) {
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
      const data = (typeof row.data === "string" ? JSON.parse(row.data) : row.data) as Record<
        string,
        unknown
      >;
      return { id: row.id, ...data };
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

    const data = (typeof row.data === "string" ? JSON.parse(row.data) : row.data) as Record<
      string,
      unknown
    >;
    return Response.json({ id: row.id, ...data });
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

    const data = (typeof row.data === "string" ? JSON.parse(row.data) : row.data) as Record<
      string,
      unknown
    >;
    if (data.status !== "resolved") {
      return Response.json({ error: "Activity is not resolved yet" }, { status: 400 });
    }

    const options = (data.decision_options as { id: string }[] | null) ?? [];
    const chosen = options.find((opt) => opt.id === body.decision_id);
    if (!chosen) {
      return Response.json({ error: "Invalid decision" }, { status: 400 });
    }

    // Apply effects based on outcome
    const outcome = data.outcome as Record<string, unknown> | null;
    if (outcome && data.activity_type === "crafting") {
      const craftedItemId = outcome.crafted_item_id as string | null;
      if (craftedItemId && body.decision_id === "keep") {
        await sql`
          INSERT INTO player_inventory (player_id, item_id, data)
          VALUES (${playerId}, ${craftedItemId}, ${JSON.stringify({ quantity: 1, equipped: false })})
          ON CONFLICT (player_id, item_id)
          DO UPDATE SET data = jsonb_set(
            player_inventory.data,
            '{quantity}',
            (COALESCE((player_inventory.data->>'quantity')::int, 0) + 1)::text::jsonb
          )
        `;
      }
    }

    // Update status to collected
    await sql`
      UPDATE async_activities
      SET data = jsonb_set(
        jsonb_set(data, '{status}', '"collected"'),
        '{decision}', ${JSON.stringify(body.decision_id)}::jsonb
      )
      WHERE id = ${activityId}
    `;

    return Response.json({
      id: activityId,
      status: "collected",
      decision: body.decision_id,
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
