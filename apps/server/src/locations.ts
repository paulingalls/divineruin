import type { Location, HiddenElement, LocationExit } from "@divineruin/shared";
import { sql } from "./db.ts";
import { asRecord, parseStringArray } from "./parse-helpers.ts";

// DB-loaded locations (M6 Stage source). Mirrors abilities.ts/archetypes.ts:
// content/locations.json -> locations table, loaded at startup, parsed fail-loud,
// exposed via getLocation/listLocations. listLocations() is the intended single
// source for errand_risk's danger-level band map (that consolidation lands with the
// startup wiring, this story). The Python agent reads the same JSONB rows
// straight from the table; this loader is the TS-side fail-loud guard for the M6
// schema fields hidden_element.attaches_to and exit.requires.

// Runtime-loaded locations, keyed by location id (populated by loadLocations at startup).
let locations: ReadonlyMap<string, Location> = new Map();

// get_location is undefined-on-miss (locations are looked up opportunistically, unlike
// the fail-loud ability/milestone accessors); list_locations enumerates for derived stores.
export function getLocation(id: string): Location | undefined {
  return locations.get(id);
}

export function listLocations(): Location[] {
  return Array.from(locations.values());
}

export function setLocations(map: ReadonlyMap<string, Location>): void {
  locations = map;
}

function parseHiddenElement(raw: unknown, ctx: string): HiddenElement {
  const h = asRecord(raw, ctx);
  if (typeof h.id !== "string") throw new Error(`${ctx}.id is not a string`);
  if (typeof h.discover_skill !== "string")
    throw new Error(`${ctx}.discover_skill is not a string`);
  // Integer (not just number) for parity with the Python loader's int DC — a shared row
  // with a float dc must fail identically on both sides (the cross-language discipline).
  if (typeof h.dc !== "number" || !Number.isInteger(h.dc)) {
    throw new Error(`${ctx}.dc is not an integer`);
  }
  if (typeof h.description !== "string") throw new Error(`${ctx}.description is not a string`);
  if (h.attaches_to !== undefined && typeof h.attaches_to !== "string") {
    throw new Error(`${ctx}.attaches_to is not a string`);
  }
  const el: HiddenElement = {
    id: h.id,
    discover_skill: h.discover_skill,
    dc: h.dc,
    description: h.description,
  };
  if (h.attaches_to !== undefined) el.attaches_to = h.attaches_to;
  return el;
}

function parseExits(raw: unknown, ctx: string): Record<string, LocationExit> {
  const rec = asRecord(raw, ctx);
  const exits: Record<string, LocationExit> = {};
  for (const [direction, value] of Object.entries(rec)) {
    const exitCtx = `${ctx}.${direction}`;
    const e = asRecord(value, exitCtx);
    if (typeof e.destination !== "string")
      throw new Error(`${exitCtx}.destination is not a string`);
    if (e.requires !== undefined && typeof e.requires !== "string") {
      throw new Error(`${exitCtx}.requires is not a string`);
    }
    const exit: LocationExit = { destination: e.destination };
    if (e.requires !== undefined) exit.requires = e.requires;
    exits[direction] = exit;
  }
  return exits;
}

export function parseLocationRow(id: string, raw: unknown): Location {
  const ctx = `locations[${id}]`;
  const data = asRecord(raw, ctx);

  if (typeof data.name !== "string") throw new Error(`${ctx}.name is not a string`);
  if (typeof data.tier !== "number" || (data.tier !== 1 && data.tier !== 2)) {
    throw new Error(`${ctx}.tier is not 1 or 2`);
  }
  if (typeof data.district !== "string") throw new Error(`${ctx}.district is not a string`);
  if (typeof data.region !== "string") throw new Error(`${ctx}.region is not a string`);
  if (typeof data.atmosphere !== "string") throw new Error(`${ctx}.atmosphere is not a string`);

  const location: Location = {
    id,
    name: data.name,
    tier: data.tier,
    district: data.district,
    region: data.region,
    tags: parseStringArray(data.tags, `${ctx}.tags`),
    atmosphere: data.atmosphere,
    exits: parseExits(data.exits, `${ctx}.exits`),
  };

  if (data.description !== undefined) {
    if (typeof data.description !== "string") throw new Error(`${ctx}.description is not a string`);
    location.description = data.description;
  }
  if (data.key_features !== undefined) {
    location.key_features = parseStringArray(data.key_features, `${ctx}.key_features`);
  }
  if (data.hidden_elements !== undefined) {
    if (!Array.isArray(data.hidden_elements)) {
      throw new Error(`${ctx}.hidden_elements is not an array`);
    }
    location.hidden_elements = data.hidden_elements.map((el, i) =>
      parseHiddenElement(el, `${ctx}.hidden_elements[${i}]`),
    );
  }
  if (data.danger_level !== undefined) {
    // Integer (not just number) for parity with the dc guard above and the sibling
    // loaders' int discipline: danger_level is a 0-3 band that numericToDangerLevel /
    // the Python numeric_to_danger only recognize as integers. A float (e.g. 2.7) must
    // fail loud HERE with the location + field context, not later/opaquely at the band map.
    if (typeof data.danger_level !== "number" || !Number.isInteger(data.danger_level)) {
      throw new Error(`${ctx}.danger_level is not an integer`);
    }
    location.danger_level = data.danger_level;
  }
  if (data.ambient_sounds !== undefined) {
    if (typeof data.ambient_sounds !== "string") {
      throw new Error(`${ctx}.ambient_sounds is not a string`);
    }
    location.ambient_sounds = data.ambient_sounds;
  }
  if (data.ambient_sounds_night !== undefined) {
    if (typeof data.ambient_sounds_night !== "string") {
      throw new Error(`${ctx}.ambient_sounds_night is not a string`);
    }
    location.ambient_sounds_night = data.ambient_sounds_night;
  }
  // conditions are a free-form override map (LocationCondition); pass through unvalidated —
  // they are not part of the M6 Stage schema and have no TS consumer (story scope).
  if (data.conditions !== undefined) {
    location.conditions = data.conditions as Location["conditions"];
  }

  return location;
}

export async function loadLocations(): Promise<void> {
  const rows = await sql<{ id: string; data: unknown }[]>`
    SELECT id, data FROM locations
  `;
  // Build the local map then swap in one synchronous step, so a malformed row fails
  // loud WITHOUT wiping an already-loaded map (mirrors loadAbilities' discipline).
  const map = new Map<string, Location>();
  for (const row of rows) {
    map.set(row.id, parseLocationRow(row.id, row.data));
  }
  locations = map;
  console.log(`Loaded ${map.size} locations`);
}
