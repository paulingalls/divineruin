export const REGION_IDS = [
  "greyvale",
  "thornveld",
  "drathian_steppe",
  "sunward_coast",
  "keldaran_mountains",
  "ashmark",
  "underground",
] as const;

export type RegionId = (typeof REGION_IDS)[number];
