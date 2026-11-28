import { parseJsonb } from "./parse-jsonb.ts";

type Favor = { patron?: unknown; level?: unknown; max?: unknown };

export function captureCraftBlessing(rawFavor: unknown) {
  const favor = parseJsonb<Favor | null | undefined>(rawFavor);
  if (favor == null) return undefined;

  const { patron, level, max } = favor;
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
