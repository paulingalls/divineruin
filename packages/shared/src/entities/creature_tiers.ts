export const TIER_LEVEL_RANGES: Record<number, readonly [number, number]> = {
  1: [1, 4],
  2: [5, 8],
  3: [9, 14],
  4: [15, 20],
};

export function playerLevelRangeForTier(tier: number): readonly [number, number] {
  const band = TIER_LEVEL_RANGES[tier];
  if (!band) throw new Error(`unknown creature tier ${tier}`);
  return band;
}

export function tierForPlayerLevel(level: number): number {
  const matches = Object.entries(TIER_LEVEL_RANGES)
    .filter(([, [low, high]]) => Number.isInteger(level) && low <= level && level <= high)
    .map(([tier]) => Number(tier));
  if (matches.length !== 1)
    throw new Error(`player level ${level} maps to ${matches.length} creature tiers`);
  return matches[0]!;
}
