/**
 * Static map node positions for the 16 MVP locations.
 * Coordinates are in a 0–1000 space, scaled to container at render time.
 * Connections derived from content/locations.json exits.
 */

export interface MapLayoutNode {
  id: string;
  label: string;
  x: number;
  y: number;
  region: string;
}

export const MAP_LAYOUT: MapLayoutNode[] = [
  // --- Accord (central hub) ---
  { id: "accord_market_square", label: "Market Square", x: 500, y: 400, region: "Accord" },
  { id: "accord_guild_hall", label: "Guild Hall", x: 500, y: 280, region: "Accord" },
  { id: "accord_temple_row", label: "Temple Row", x: 650, y: 400, region: "Accord" },
  { id: "accord_dockside", label: "Dockside", x: 500, y: 520, region: "Accord" },
  {
    id: "accord_hearthstone_tavern",
    label: "Hearthstone Tavern",
    x: 350,
    y: 400,
    region: "Accord",
  },
  { id: "torin_quarters", label: "Torin's Quarters", x: 430, y: 200, region: "Accord" },
  { id: "emris_study", label: "Emris's Study", x: 580, y: 580, region: "Accord" },

  // --- Greyvale South Road (connector) ---
  { id: "greyvale_south_road", label: "South Road", x: 500, y: 650, region: "Greyvale" },

  // --- Millhaven ---
  { id: "millhaven", label: "Millhaven", x: 400, y: 770, region: "Millhaven" },
  { id: "millhaven_inn", label: "Millhaven Inn", x: 500, y: 830, region: "Millhaven" },
  { id: "yanna_farmhouse", label: "Yanna's Farm", x: 310, y: 830, region: "Millhaven" },

  // --- Greyvale Wilderness ---
  {
    id: "greyvale_wilderness_north",
    label: "Wilderness North",
    x: 350,
    y: 880,
    region: "Greyvale",
  },
  { id: "hollow_incursion_site", label: "Hollow Incursion", x: 280, y: 950, region: "Greyvale" },

  // --- Greyvale Ruins ---
  { id: "greyvale_ruins_exterior", label: "Ruins Exterior", x: 470, y: 920, region: "Greyvale" },
  { id: "greyvale_ruins_entrance", label: "Ruins Entrance", x: 520, y: 960, region: "Greyvale" },
  { id: "greyvale_ruins_inner", label: "Ruins Inner", x: 570, y: 1000, region: "Greyvale" },
];

/** Lookup table for quick coordinate access. */
export const MAP_LAYOUT_BY_ID = new Map(MAP_LAYOUT.map((n) => [n.id, n]));
