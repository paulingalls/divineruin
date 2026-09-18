import { getAllErrandTemplates, getAllTrainingPrograms } from "./activity_templates.ts";
import { listRecipes, craftingDurationSeconds } from "./recipes.ts";
import { getActivityTypeConfig } from "./training_state_machine.ts";
import { sql } from "./db.ts";
import { parseJsonb } from "./parse-jsonb.ts";
import { logError } from "./env.ts";
import { getArchetypeChassis } from "./archetypes.ts";
import { listSpells } from "./spells.ts";
import {
  displayName,
  computePercentComplete,
  type ActiveStatus,
  type MaterialRequirement,
  type TemplateGroup,
  type TemplateItem,
  isSpellTierUnlocked,
} from "@divineruin/shared";

function formatDuration(minSec: number, maxSec: number): string {
  const minH = Math.round(minSec / 3600);
  const maxH = Math.round(maxSec / 3600);
  if (minH === maxH) return `${minH}h`;
  return `${minH}-${maxH}h`;
}

function activeStatus(
  startTime: string,
  resolveAt: string,
  isAwaitingDecision: boolean,
): ActiveStatus {
  return {
    startTime,
    resolveAtEstimate: resolveAt,
    percentEstimate: computePercentComplete(startTime, resolveAt),
    isAwaitingDecision,
  };
}

/** "6-10h" — a training cycle's both-halves duration range, from its activity type config. */
function trainingDuration(activityTypeId: string, context: string): string {
  const activityType = getActivityTypeConfig(activityTypeId);
  if (!activityType) {
    throw new Error(`${context} references unknown activity type ${activityTypeId}`);
  }
  return formatDuration(
    activityType.first_half_min_seconds + activityType.second_half_min_seconds,
    activityType.first_half_max_seconds + activityType.second_half_max_seconds,
  );
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

    // `state != 'complete'` is countActiveBySlot's training predicate verbatim
    // (activity_create.ts): the rows that lock the launcher must be exactly the rows that
    // make a START 400, or the lock fires when the slot is free — or, worse, not when it isn't.
    const trainingPromise = sql`
      SELECT data, activity_type, state, created_at, transition_at FROM training_activities
      WHERE player_id = ${playerId} AND state != 'complete'
      LIMIT 5
    ` as Promise<
      {
        data: unknown;
        activity_type: string;
        state: string;
        created_at: string;
        transition_at: string;
      }[]
    >;

    const playerPromise = sql<{ class: string | null; level: string | null }[]>`
      SELECT data->>'class' AS class, data->>'level' AS level
      FROM players WHERE player_id = ${playerId}
    `;
    const knownSpellsPromise = sql<{ spell_id: string }[]>`
      SELECT spell_id FROM character_spells WHERE player_id = ${playerId}
    `;

    const [inventoryRows, activeRows, trainingRows, playerRows, knownSpellRows] = await Promise.all(
      [inventoryPromise, activePromise, trainingPromise, playerPromise, knownSpellsPromise],
    );

    // Build owned map
    const owned: Record<string, number> = {};
    for (const row of inventoryRows) {
      owned[row.item_id] = row.quantity;
    }

    // Build active map: template key → ActiveStatus
    const activeMap = new Map<string, ActiveStatus>();
    const allActiveRows = [
      ...activeRows.map((row) => ({ ...row, isAwaitingDecision: false })),
      ...trainingRows.map((row) => ({
        data: {
          activity_type: "training",
          parameters: parseJsonb(row.data),
          start_time: row.created_at,
          resolve_at: row.transition_at,
        },
        isAwaitingDecision: row.state === "awaiting_decision",
      })),
    ];
    for (const row of allActiveRows) {
      const data = parseJsonb(row.data);
      const key = templateKeyFromActivity(data);
      if (key) {
        activeMap.set(
          key,
          activeStatus(
            data.start_time as string,
            data.resolve_at as string,
            row.isAwaitingDecision,
          ),
        );
      }
    }

    const player = playerRows[0];
    const chassis = player?.class ? getArchetypeChassis(player.class) : undefined;
    const level =
      player?.level === null || player?.level === undefined ? NaN : Number(player.level);
    const knownSpellIds = new Set(knownSpellRows.map((row) => row.spell_id));

    const trainingItems: TemplateItem[] = getAllTrainingPrograms().map((p) => {
      const params: Record<string, unknown> = {
        program_id: p.id,
        stat: p.stat,
        skill: p.skill,
      };
      if (p.training_activity_type.startsWith("spell_")) {
        const tier = p.training_activity_type.slice("spell_".length);
        params.studiable_spell_ids =
          chassis && chassis.magic_source !== null && Number.isInteger(level) && level >= 1
            ? listSpells()
                .filter(
                  (spell) =>
                    spell.spell_tier === tier &&
                    (chassis.magic_source === "cross" || chassis.magic_source === spell.source) &&
                    isSpellTierUnlocked(chassis, tier, level) &&
                    !knownSpellIds.has(spell.id),
                )
                .map((spell) => spell.id)
                .sort()
            : [];
      }
      return {
        id: p.id,
        name: p.name,
        duration: trainingDuration(p.training_activity_type, `Training program ${p.id}`),
        params,
        materials: null,
        active: activeMap.get(p.id) ?? null,
      };
    });

    // Every non-terminal training row holds the training slot, but only one naming a listed
    // program has a row to carry its `active`: learn(kind="variant") writes variant_id and no
    // program_id (mentor_variant_tools.py), and no training program carries
    // technique_mentor_variant. Surface the leftovers as active-only rows — without one the
    // launcher's group lock cannot fire and every START 400s on the slot check.
    for (const row of trainingRows) {
      const data = parseJsonb(row.data);
      const key = templateKeyFromActivity({ activity_type: "training", parameters: data });
      const id = key ?? (data.variant_id as string | undefined) ?? row.activity_type;
      if (trainingItems.some((item) => item.id === id)) continue;
      trainingItems.push({
        id,
        name: typeof data.program_name === "string" ? data.program_name : displayName(id),
        duration: trainingDuration(row.activity_type, `Training activity ${row.activity_type}`),
        params: {},
        materials: null,
        active: activeStatus(row.created_at, row.transition_at, row.state === "awaiting_decision"),
      });
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
        items: trainingItems,
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
