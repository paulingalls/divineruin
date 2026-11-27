import gods from "../../../content/gods.json";
import { type God, validateGods } from "../../../packages/shared/src/entities/god.ts";
import { parseJsonb } from "./parse-jsonb.ts";

const craftingPatrons = validateGods(gods);
const commonBondId = "aelora_common_bond_crafting";

type Favor = { patron?: unknown; level?: unknown; max?: unknown };

function captureCraftBlessing({ patron, level, max }: Favor) {
  if (
    typeof level !== "number" ||
    typeof max !== "number" ||
    max <= 0 ||
    level < 0 ||
    level > max
  ) {
    throw new Error("Invalid divine favor for crafting");
  }
  if (patron !== "aelora") return undefined;

  // Match patron_favor.tier_index: favor thresholds round up against the patron's maximum.
  const tier =
    level >= Math.ceil((max * 75) / 100)
      ? "Exalted"
      : level >= Math.ceil((max * 40) / 100)
        ? "Devoted"
        : "Acknowledged";
  return { id: "aelora_craft_blessing", name: "Craft Blessing", patron, tier };
}

export function captureCraftingPatrons(
  rawFavor: unknown,
  archetype: string | undefined,
  catalog: God[] = craftingPatrons,
) {
  const favor = parseJsonb<Favor | null | undefined>(rawFavor);
  if (favor == null) return {};

  const blessing = captureCraftBlessing(favor);
  const patron = catalog.find((god) => god.god_id === favor.patron);
  const row = patron?.layer_4_synergy_matrix[archetype ?? ""];
  const commonBond = row?.clauses.some(
    (clause) =>
      clause.status === "active" &&
      clause.resolution === "engine" &&
      clause.implementation_id === commonBondId,
  )
    ? { id: commonBondId, name: row.name, bonus: 1 }
    : undefined;
  return { blessing, commonBond };
}
