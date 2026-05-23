import { getAllErrandTemplates, getAllTrainingPrograms } from "./activity_templates.ts";
import { listRecipes, craftingDurationSeconds } from "./recipes.ts";
import { getActivityTypeConfig } from "./training_state_machine.ts";
import { sql } from "./db.ts";
import { parseJsonb } from "./parse-jsonb.ts";
import { logError } from "./env.ts";
import {
  displayName,
  computePercentComplete,
  type ActiveStatus,
  type MaterialRequirement,
  type TemplateGroup,
} from "@divineruin/shared";

function formatDuration(minSec: number, maxSec: number): string {
  const minH = Math.round(minSec / 3600);
  const maxH = Math.round(maxSec / 3600);
  if (minH === maxH) return `${minH}h`;
  return `${minH}-${maxH}h`;
}

/** Map template key (recipe_id, program_id, errand_type) from in-progress activity data. */
function templateKeyFromActivity(data: Record<string, unknown>): string | null {
  const params = (data.parameters ?? {}) as Record<string, unknown>;
  const type = data.activity_type as string;
  if (type === "crafting") return (params.recipe_id as string | undefined) ?? null;
  if (type === "training") return (params.program_id as string | undefined) ?? null;
  if (type === "companion_errand") return (params.errand_type as string | undefined) ?? null;
  return null;
}

export async function handleGetActivityTemplates(playerId: string): Promise<Response> {
  try {
    // Run inventory + active activity queries in parallel
    const allMaterialIds = new Set<string>();
    for (const recipe of listRecipes()) {
      for (const m of recipe.materials) {
        allMaterialIds.add(m.material_id);
      }
    }

    const inventoryPromise =
      allMaterialIds.size > 0
        ? (sql`
            SELECT item_id,
              COALESCE((data->>'quantity')::int, 1) AS quantity
            FROM player_inventory
            WHERE player_id = ${playerId} AND item_id IN ${sql([...allMaterialIds])}
          ` as Promise<{ item_id: string; quantity: number }[]>)
        : Promise.resolve([] as { item_id: string; quantity: number }[]);

    const activePromise = sql`
      SELECT data FROM async_activities
      WHERE player_id = ${playerId} AND data->>'status' IN ('in_progress', 'resolving')
      LIMIT 50
    ` as Promise<{ data: unknown }[]>;

    const [inventoryRows, activeRows] = await Promise.all([inventoryPromise, activePromise]);

    // Build owned map
    const owned: Record<string, number> = {};
    for (const row of inventoryRows) {
      owned[row.item_id] = row.quantity;
    }

    // Build active map: template key → ActiveStatus
    const activeMap = new Map<string, ActiveStatus>();
    for (const row of activeRows) {
      const data = parseJsonb(row.data);
      const key = templateKeyFromActivity(data);
      if (key) {
        const startTime = data.start_time as string;
        const resolveAt = data.resolve_at as string;
        activeMap.set(key, {
          startTime,
          resolveAtEstimate: resolveAt,
          percentEstimate: computePercentComplete(startTime, resolveAt),
        });
      }
    }

    const groups: TemplateGroup[] = [
      {
        type: "crafting",
        label: "Crafting",
        items: listRecipes().map((r) => {
          const materials: MaterialRequirement[] = r.materials.map((m) => ({
            itemId: m.material_id,
            name: displayName(m.material_id),
            required: m.quantity,
            owned: owned[m.material_id] ?? 0,
          }));
          const duration = craftingDurationSeconds(r);
          return {
            id: r.id,
            name: r.name,
            duration: formatDuration(duration.min, duration.max),
            params: {
              recipe_id: r.id,
              dc: r.crafting_dc,
            },
            materials,
            active: activeMap.get(r.id) ?? null,
          };
        }),
      },
      {
        type: "training",
        label: "Training",
        items: getAllTrainingPrograms().map((p) => {
          const activityType = getActivityTypeConfig(p.training_activity_type);
          if (!activityType) {
            throw new Error(
              `Training program ${p.id} references unknown activity type ${p.training_activity_type}`,
            );
          }
          const minSec = activityType.first_half_min_seconds + activityType.second_half_min_seconds;
          const maxSec = activityType.first_half_max_seconds + activityType.second_half_max_seconds;
          return {
            id: p.id,
            name: p.name,
            duration: formatDuration(minSec, maxSec),
            params: {
              program_id: p.id,
              stat: p.stat,
              skill: p.skill,
            },
            materials: null,
            active: activeMap.get(p.id) ?? null,
          };
        }),
      },
      {
        type: "companion_errand",
        label: "Companion Errands",
        items: getAllErrandTemplates().map((e) => ({
          id: e.id,
          name: e.name,
          duration: formatDuration(e.duration_min_seconds, e.duration_max_seconds),
          params: {
            errand_type: e.id,
            valid_destinations: e.valid_destinations,
          },
          materials: null,
          active: activeMap.get(e.id) ?? null,
        })),
      },
    ];

    return Response.json({ groups });
  } catch (err) {
    logError("[activity-templates] failed:", err);
    return Response.json({ groups: [] });
  }
}
