export const TERRAIN_PROPERTIES = {
  ancient_forest: {
    resonance_base: 0.1,
    is_natural: true,
    is_earth_or_stone: true,
    region_type: "wilderness",
  },
  forest: {
    resonance_base: 0.2,
    is_natural: true,
    is_earth_or_stone: true,
    region_type: "wilderness",
  },
  grassland: {
    resonance_base: 0.2,
    is_natural: true,
    is_earth_or_stone: true,
    region_type: "wilderness",
  },
  mountain: {
    resonance_base: 0.2,
    is_natural: true,
    is_earth_or_stone: true,
    region_type: "wilderness",
  },
  coast: {
    resonance_base: 0.2,
    is_natural: true,
    is_earth_or_stone: false,
    region_type: "wilderness",
  },
  wetland: {
    resonance_base: 0.2,
    is_natural: true,
    is_earth_or_stone: false,
    region_type: "wilderness",
  },
  underground: {
    resonance_base: 0.2,
    is_natural: true,
    is_earth_or_stone: true,
    region_type: "dungeon",
  },
  farmland: {
    resonance_base: 0.3,
    is_natural: true,
    is_earth_or_stone: true,
    region_type: "wilderness",
  },
  village: {
    resonance_base: 0.4,
    is_natural: false,
    is_earth_or_stone: false,
    region_type: "city",
  },
  city: { resonance_base: 0.5, is_natural: false, is_earth_or_stone: false, region_type: "city" },
} as const;
export type TerrainType = keyof typeof TERRAIN_PROPERTIES;
export const TERRAIN_TYPE_VALUES = Object.keys(TERRAIN_PROPERTIES) as TerrainType[];

export function terrainProperties(value: string) {
  if (!Object.hasOwn(TERRAIN_PROPERTIES, value)) throw new Error(`Unknown terrain ${value}`);
  return TERRAIN_PROPERTIES[value as TerrainType];
}

export function resonanceBase(value: string) {
  return terrainProperties(value).resonance_base;
}

export function isNatural(value: string) {
  return terrainProperties(value).is_natural;
}

export function isEarthOrStone(value: string) {
  return terrainProperties(value).is_earth_or_stone;
}

export function regionType(value: string) {
  return terrainProperties(value).region_type;
}
