import { CRAFTING_RECIPES, TRAINING_PROGRAMS, ERRAND_TEMPLATES } from "./activity_templates.ts";
import { sql } from "./db.ts";
import { logError } from "./env.ts";

function formatDuration(minSec: number, maxSec: number): string {
  const minH = Math.round(minSec / 3600);
  const maxH = Math.round(maxSec / 3600);
  if (minH === maxH) return `${minH}h`;
  return `${minH}-${maxH}h`;
}

function displayName(itemId: string): string {
  return itemId
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

/** Aggregate ["iron_ingot", "iron_ingot", "leather_strip"] → { iron_ingot: 2, leather_strip: 1 } */
function countMaterials(materials: string[]): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const m of materials) {
    counts[m] = (counts[m] ?? 0) + 1;
  }
  return counts;
}

interface MaterialRequirement {
  itemId: string;
  name: string;
  required: number;
  owned: number;
}

interface ActiveStatus {
  startTime: string;
  resolveAtEstimate: string;
  percentEstimate: number;
}

interface TemplateItem {
  id: string;
  name: string;
  duration: string;
  params: Record<string, unknown>;
  materials: MaterialRequirement[] | null;
  active: ActiveStatus | null;
}

interface TemplateGroup {
  type: string;
  label: string;
  items: TemplateItem[];
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

function computePercent(startTime: string, resolveAt: string): number {
  const now = Date.now();
  const start = new Date(startTime).getTime();
  const end = new Date(resolveAt).getTime();
  const total = end - start;
  if (total <= 0) return 100;
  return Math.min(100, Math.max(0, Math.round(((now - start) / total) * 100)));
}

export async function handleGetActivityTemplates(playerId: string): Promise<Response> {
  try {
    // Run inventory + active activity queries in parallel
    const allMaterialIds = new Set<string>();
    for (const recipe of Object.values(CRAFTING_RECIPES)) {
      for (const m of recipe.required_materials) {
        allMaterialIds.add(m);
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
      WHERE player_id = ${playerId} AND data->>'status' = 'in_progress'
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
      const data = (typeof row.data === "string" ? JSON.parse(row.data) : row.data) as Record<
        string,
        unknown
      >;
      const key = templateKeyFromActivity(data);
      if (key) {
        const startTime = data.start_time as string;
        const resolveAt = data.resolve_at as string;
        activeMap.set(key, {
          startTime,
          resolveAtEstimate: resolveAt,
          percentEstimate: computePercent(startTime, resolveAt),
        });
      }
    }

    const groups: TemplateGroup[] = [
      {
        type: "crafting",
        label: "Crafting",
        items: Object.values(CRAFTING_RECIPES).map((r) => {
          const counts = countMaterials(r.required_materials);
          const materials: MaterialRequirement[] = Object.entries(counts).map(
            ([itemId, required]) => ({
              itemId,
              name: displayName(itemId),
              required,
              owned: owned[itemId] ?? 0,
            }),
          );
          return {
            id: r.id,
            name: r.name,
            duration: formatDuration(r.duration_min_seconds, r.duration_max_seconds),
            params: {
              recipe_id: r.id,
              required_materials: r.required_materials,
              skill: r.skill,
              dc: r.dc,
            },
            materials,
            active: activeMap.get(r.id) ?? null,
          };
        }),
      },
      {
        type: "training",
        label: "Training",
        items: Object.values(TRAINING_PROGRAMS).map((p) => ({
          id: p.id,
          name: p.name,
          duration: formatDuration(p.duration_min_seconds, p.duration_max_seconds),
          params: {
            program_id: p.id,
            stat: p.stat,
            skill: p.skill,
          },
          materials: null,
          active: activeMap.get(p.id) ?? null,
        })),
      },
      {
        type: "companion_errand",
        label: "Companion Errands",
        items: Object.values(ERRAND_TEMPLATES).map((e) => ({
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
