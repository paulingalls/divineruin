import { sql } from "./db.ts";
import { parseJsonb } from "./parse-jsonb.ts";
import { logError } from "./env.ts";
import {
  VALID_ACTIVITY_TYPES,
  getTrainingProgram,
  getErrandTemplate,
} from "./activity_templates.ts";
import { getRecipe, recipeMaterialIds, craftingDurationSeconds } from "./recipes.ts";
import { displayName } from "@divineruin/shared";
import { validateSlotAvailability, type SlotCounts } from "./slot_validation.ts";
import { validateErrandDispatch } from "./errand_risk.ts";
import { accessibleWorkspaceTier } from "./workspace.ts";
import { startTrainingCycle } from "./training_state_machine.ts";

// Worker-internal bookkeeping kept in async_activities.data that must never reach
// clients. resolving_at/resolve_attempts are the transient CAS markers that
// mark_resolved strips in SQL on the terminal write, but they're present during the
// in_progress/resolving retry window. narration_segments is the worker's cached
// per-character TTS breakdown (dialogue_parser.Segment: character/emotion/text); it
// is NOT stripped by mark_resolved, so it persists verbatim on resolved rows — the
// client only needs narration_audio_url + narration_text. Add any future worker-only
// field here (concern 06edbc8f3eef).
// 'slot' is the internal slot-accounting marker (the slot the activity consumes;
// stamped 'training' for an Artificer borrowed-slot craft). countActiveBySlot reads it
// from the DB; clients have no use for it and key off activity_type.
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

async function countActiveBySlot(playerId: string, tx: typeof sql): Promise<SlotCounts> {
  const rows: { training: number; crafting: number; companion: number }[] = await tx`
    SELECT
      COALESCE(SUM(CASE WHEN src = 'training' THEN 1 ELSE 0 END), 0)::int AS training,
      COALESCE(SUM(CASE WHEN src = 'crafting' THEN 1 ELSE 0 END), 0)::int AS crafting,
      COALESCE(SUM(CASE WHEN src IN ('companion', 'companion_errand') THEN 1 ELSE 0 END), 0)::int AS companion
    FROM (
      -- Bucket by the slot actually consumed. The Artificer Portable-Lab exception
      -- stamps data.slot='training' on a craft that borrows the training slot, so it
      -- must count toward training, not crafting (ADR 0005, debt 95de7fa141df).
      -- COALESCE to activity_type keeps pre-stamp legacy rows behaving unchanged.
      SELECT COALESCE(data->>'slot', data->>'activity_type') AS src
      FROM async_activities
      WHERE player_id = ${playerId} AND data->>'status' IN ('in_progress', 'resolving')
      UNION ALL
      SELECT 'training' AS src
      FROM training_activities
      WHERE player_id = ${playerId} AND state != 'complete'
    ) combined
  `;
  const row = rows[0];
  return {
    training: row?.training ?? 0,
    crafting: row?.crafting ?? 0,
    companion: row?.companion ?? 0,
  };
}

function randomInt(min: number, max: number): number {
  return Math.floor(Math.random() * (max - min + 1)) + min;
}

function makeActivityId(prefix: string): string {
  return `${prefix}_${crypto.randomUUID().replace(/-/g, "").slice(0, 12)}`;
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

    // Capture into a const so the narrowed string type survives into the
    // sql.begin() async closures below (TS widens body.type back to
    // string | undefined across the closure boundary otherwise).
    const activityType = body.type;
    const params = body.parameters ?? {};

    // Training uses its own table and transaction — handle separately and return early
    if (body.type === "training") {
      const programId = params.program_id as string | undefined;
      if (!programId) {
        return Response.json({ error: "program_id is required for training" }, { status: 400 });
      }
      const program = getTrainingProgram(programId);
      if (!program) {
        return Response.json({ error: "Unknown training program" }, { status: 400 });
      }

      const txnResult = await sql.begin(async (tx) => {
        await tx`
          SELECT id FROM async_activities
          WHERE player_id = ${playerId} AND data->>'status' = 'in_progress'
          FOR UPDATE
        `;
        await tx`
          SELECT id FROM training_activities
          WHERE player_id = ${playerId} AND state != 'complete'
          FOR UPDATE
        `;
        const slotCounts = await countActiveBySlot(playerId, tx);
        // archetype/hasPortableLab intentionally omitted: the Artificer
        // training-slot exception is deferred to Phase 5 (see ADR 0005).
        const slotCheck = validateSlotAvailability(slotCounts, activityType);
        if (!slotCheck.valid) {
          return { error: slotCheck.error! } as const;
        }

        const now = new Date();
        const cycle = startTrainingCycle(program.training_activity_type, now);
        const activityId = makeActivityId("train");

        const data = {
          program_id: program.id,
          program_name: program.name,
          first_half_seconds: cycle.first_half_seconds,
          stat: program.stat,
          skill: program.skill ?? null,
          dc: program.dc,
          mentor_id: program.mentor_id,
        };

        await tx`
          INSERT INTO training_activities (id, player_id, activity_type, state, data, transition_at)
          VALUES (${activityId}, ${playerId}, ${program.training_activity_type}, ${cycle.state}, ${data}, ${cycle.transition_at})
        `;

        return { activityId, state: cycle.state, transitionAt: cycle.transition_at } as const;
      });

      if ("error" in txnResult) {
        return Response.json({ error: txnResult.error }, { status: 400 });
      }

      return Response.json({
        activity_id: txnResult.activityId,
        status: "in_progress",
        state: txnResult.state,
        transition_at: txnResult.transitionAt,
      });
    }

    // Crafting and companion_errand — both go through async_activities
    let durationMin: number;
    let durationMax: number;
    let activityParams: Record<string, unknown>;
    let materialsToConsume: string[] = [];
    // Slot-validation inputs for the Artificer exception (story-006); set in the
    // crafting branch, read at the shared validateSlotAvailability call in the txn.
    let archetype: string | undefined;
    let hasPortableLab = false;

    if (body.type === "crafting") {
      const recipeId = params.recipe_id as string | undefined;
      if (!recipeId) {
        return Response.json({ error: "recipe_id is required for crafting" }, { status: 400 });
      }
      const recipe = getRecipe(recipeId);
      if (!recipe) {
        return Response.json({ error: "Unknown recipe" }, { status: 400 });
      }

      const duration = craftingDurationSeconds(recipe);
      durationMin = duration.min;
      durationMax = duration.max;
      materialsToConsume = recipeMaterialIds(recipe);

      // Capture the resolution gate inputs (story-005) so resolve_crafting can
      // re-check workspace access + tainted-Expert at completion — the live REST
      // path skips pre-flight, so these are its only gate evidence. Snapshot reads
      // outside the txn (parity with the in-memory recipe fetch); mirrors the
      // Python producer (crafting_tools.py) for a byte-identical parameters shape.
      // workspace_access is sorted so the stored JSONB is deterministic.
      const playerRows = await sql<{ location_id: string | null; class: string | null }[]>`
        SELECT data->>'location_id' AS location_id, data->>'class' AS class
        FROM players WHERE player_id = ${playerId}
      `;
      const locationId = playerRows[0]?.location_id ?? "unknown";
      archetype = playerRows[0]?.class ?? undefined;

      // Artificer Portable-Lab ownership (story-006): ONE inventory read, used for both
      // the workspace grant (accessibleWorkspaceTier) and the slot exception
      // (validateSlotAvailability). A real source — false until the lab becomes craftable
      // (M5.4); honest wiring of ADR 0005's seam, not a hardcoded false.
      const labRows = await sql<{ owned: number }[]>`
        SELECT 1 AS owned FROM player_inventory
        WHERE player_id = ${playerId} AND item_id = 'artificers_portable_lab'
          AND COALESCE((data->>'quantity')::int, 1) >= 1
        LIMIT 1
      `;
      hasPortableLab = labRows.length > 0;
      const workspaceAccess = [
        ...(await accessibleWorkspaceTier(playerId, locationId, { hasPortableLab })),
      ].sort();

      // Workspace gate (story-006, AC#3): reject before the txn — before any material
      // consumption — when the recipe's required workspace is not accessible. Exact-type
      // membership, matching the agent-tool pre-flight Check 3 (crafting_gates.workspace_accessible).
      if (!workspaceAccess.includes(recipe.workspace_required)) {
        return Response.json(
          { error: `no access to a ${recipe.workspace_required} workspace` },
          { status: 400 },
        );
      }

      // Mirror Python get_single_skill_advancement: default to "untrained" when
      // the player has no crafting skill_advancement row.
      const skillRows = await sql<{ tier: string }[]>`
        SELECT tier FROM skill_advancement WHERE player_id = ${playerId} AND skill_id = 'crafting'
      `;
      const craftingTier = skillRows[0]?.tier ?? "untrained";

      // skill/npc_id are intentionally omitted — the resolver defaults them
      // (arcana / grimjaw_blacksmith). Per-recipe skill+NPC were dropped from the
      // M5.1 Recipe schema; revisit in M5.2 (decision crafting-check-skill).
      activityParams = {
        recipe_id: recipe.id,
        result_item_id: recipe.output_item,
        result_item_name: recipe.name,
        required_materials: materialsToConsume,
        dc: recipe.crafting_dc,
        workspace_required: recipe.workspace_required,
        workspace_access: workspaceAccess,
        crafting_tier: craftingTier,
        tainted_materials: recipe.tainted_materials,
      };
    } else {
      // companion_errand
      const errandType = params.errand_type as string | undefined;
      const destination = params.destination as string | undefined;
      if (!errandType) {
        return Response.json({ error: "errand_type is required" }, { status: 400 });
      }
      const template = getErrandTemplate(errandType);
      if (!template) {
        return Response.json({ error: "Unknown errand type" }, { status: 400 });
      }
      if (!destination) {
        return Response.json({ error: "destination is required" }, { status: 400 });
      }
      if (!template.valid_destinations.includes(destination)) {
        return Response.json({ error: "Invalid destination for errand type" }, { status: 400 });
      }

      const companionId = (params.companion_id as string) || "companion_kael";
      const validation = validateErrandDispatch(errandType, destination, companionId);
      if (!validation.valid) {
        return Response.json({ error: validation.error }, { status: 400 });
      }

      durationMin = template.duration_min_seconds;
      durationMax = template.duration_max_seconds;
      // Risk is rolled by the Python worker at resolution (ADR 0006), not here.
      activityParams = {
        errand_type: errandType,
        destination,
      };
    }

    // Atomic transaction: check slot availability, verify+consume materials, insert activity
    const txnResult = await sql.begin(async (tx) => {
      await tx`
        SELECT id FROM async_activities
        WHERE player_id = ${playerId} AND data->>'status' = 'in_progress'
        FOR UPDATE
      `;
      await tx`
        SELECT id FROM training_activities
        WHERE player_id = ${playerId} AND state != 'complete'
        FOR UPDATE
      `;
      const slotCounts = await countActiveBySlot(playerId, tx);
      // Artificer Portable-Lab exception (story-006, ADR 0005): an Artificer who owns
      // a Portable Lab may craft on the training slot when the crafting slot is full.
      const slotCheck = validateSlotAvailability(
        slotCounts,
        activityType,
        archetype,
        hasPortableLab,
      );
      if (!slotCheck.valid) {
        return { error: slotCheck.error! } as const;
      }

      // Verify and consume materials atomically for crafting. materialsToConsume
      // is the recipe's material-id list flattened by quantity, so tally it into
      // required counts and check/decrement owned quantities — a recipe needing
      // 2 iron_ingot must not be craftable with 1 (debt 2f7e39e1806a).
      if (materialsToConsume.length > 0) {
        const required: Record<string, number> = {};
        for (const matId of materialsToConsume) {
          required[matId] = (required[matId] ?? 0) + 1;
        }
        const requiredIds = Object.keys(required);
        const ownedRows: { item_id: string; quantity: number }[] = await tx`
          SELECT item_id, COALESCE((data->>'quantity')::int, 1) AS quantity
          FROM player_inventory
          WHERE player_id = ${playerId} AND item_id IN ${sql(requiredIds)}
          FOR UPDATE
        `;
        const owned: Record<string, number> = {};
        for (const row of ownedRows) {
          owned[row.item_id] = row.quantity;
        }
        for (const [matId, need] of Object.entries(required)) {
          const have = owned[matId] ?? 0;
          if (have < need) {
            return {
              error: `Insufficient material: ${displayName(matId)} (need ${need}, have ${have})`,
            } as const;
          }
        }
        // Consume by decrementing each stack; delete rows that hit zero.
        for (const [matId, need] of Object.entries(required)) {
          const remaining = (owned[matId] ?? 0) - need;
          if (remaining > 0) {
            await tx`
              UPDATE player_inventory
              SET data = jsonb_set(data, '{quantity}', ${remaining}::text::jsonb)
              WHERE player_id = ${playerId} AND item_id = ${matId}
            `;
          } else {
            await tx`
              DELETE FROM player_inventory
              WHERE player_id = ${playerId} AND item_id = ${matId}
            `;
          }
        }
      }

      const now = new Date();
      const durationSeconds = randomInt(durationMin, durationMax);
      const resolveAt = new Date(now.getTime() + durationSeconds * 1000);
      const activityId = makeActivityId("activity");

      const data = {
        status: "in_progress",
        activity_type: activityType,
        // The slot actually consumed. Normally === activityType's natural slot, but
        // the Artificer Portable-Lab exception borrows the training slot for a craft
        // (slotCheck.slot === "training"). countActiveBySlot buckets by this field
        // (COALESCE to activity_type for legacy rows) so a borrowed-slot craft
        // consumes the training slot and blocks a later training activity (ADR 0005,
        // debt 95de7fa141df).
        slot: slotCheck.slot,
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
        VALUES (${activityId}, ${playerId}, ${data})
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
