/**
 * Maps MVP location IDs to bundled image assets and categories.
 * Images are pre-generated via `bun run scripts/generate_art.ts --batch mvp`
 * then copied to apps/mobile/assets/images/locations/.
 */

type LocationArtEntry = {
  bundled: number;
  category: "town" | "interior" | "wilderness" | "corrupted";
};

/* eslint-disable @typescript-eslint/no-unsafe-assignment */
const LOCATION_ART: Partial<Record<string, LocationArtEntry>> = {
  // --- Accord of Tides (town) ---
  accord_market_square: {
    bundled: require("@/../assets/images/locations/accord_market_square.png"),
    category: "town",
  },
  accord_guild_hall: {
    bundled: require("@/../assets/images/locations/accord_guild_hall.png"),
    category: "town",
  },
  accord_temple_row: {
    bundled: require("@/../assets/images/locations/accord_temple_row.png"),
    category: "town",
  },
  accord_dockside: {
    bundled: require("@/../assets/images/locations/accord_dockside.png"),
    category: "town",
  },

  // --- Accord interiors ---
  accord_hearthstone_tavern: {
    bundled: require("@/../assets/images/locations/accord_hearthstone_tavern.png"),
    category: "interior",
  },
  accord_forge: {
    bundled: require("@/../assets/images/locations/accord_forge.png"),
    category: "interior",
  },
  torin_quarters: {
    bundled: require("@/../assets/images/locations/torin_quarters.png"),
    category: "interior",
  },
  emris_study: {
    bundled: require("@/../assets/images/locations/emris_study.png"),
    category: "interior",
  },
  grimjaw_quarters: {
    bundled: require("@/../assets/images/locations/grimjaw_quarters.png"),
    category: "interior",
  },

  // --- Greyvale roads / wilderness ---
  greyvale_south_road: {
    bundled: require("@/../assets/images/locations/greyvale_south_road.png"),
    category: "wilderness",
  },
  greyvale_wilderness_north: {
    bundled: require("@/../assets/images/locations/greyvale_wilderness_north.png"),
    category: "wilderness",
  },
  greyvale_ruins_exterior: {
    bundled: require("@/../assets/images/locations/greyvale_ruins_exterior.png"),
    category: "wilderness",
  },

  // --- Millhaven ---
  millhaven: {
    bundled: require("@/../assets/images/locations/millhaven.png"),
    category: "town",
  },
  millhaven_inn: {
    bundled: require("@/../assets/images/locations/millhaven_inn.png"),
    category: "interior",
  },
  yanna_farmhouse: {
    bundled: require("@/../assets/images/locations/yanna_farmhouse.png"),
    category: "interior",
  },

  // --- Corrupted / dungeon ---
  greyvale_ruins_entrance: {
    bundled: require("@/../assets/images/locations/greyvale_ruins_entrance.png"),
    category: "corrupted",
  },
  greyvale_ruins_inner: {
    bundled: require("@/../assets/images/locations/greyvale_ruins_inner.png"),
    category: "corrupted",
  },
  hollow_incursion_site: {
    bundled: require("@/../assets/images/locations/hollow_incursion_site.png"),
    category: "corrupted",
  },
};

/** Bundled loading screen image for connecting / transition states. */
export const LOADING_ART = require("@/../assets/images/locations/loading_abstract.png") as number;
/* eslint-enable @typescript-eslint/no-unsafe-assignment */

/**
 * Resolve a location ID to a bundled image asset.
 * Returns the require() number for known IDs, null for unknown/dynamic locations.
 */
export function resolveLocationArt(locationId: string): number | null {
  return LOCATION_ART[locationId]?.bundled ?? null;
}
