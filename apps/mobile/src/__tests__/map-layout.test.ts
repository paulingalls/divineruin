import { expect, test } from "bun:test";
import locations from "../../../../content/locations.json";
import { MAP_LAYOUT } from "../data/map-layout";

test("every catalog location has exactly one map node with no orphans", () => {
  const catalogIds = new Set(locations.map(({ id }) => id));
  const layoutIds = new Set(MAP_LAYOUT.map(({ id }) => id));
  expect(catalogIds.size).toBeGreaterThan(0);
  expect(layoutIds.size).toBeGreaterThan(0);
  expect(catalogIds.size).toBe(locations.length);
  expect(layoutIds.size).toBe(MAP_LAYOUT.length);
  expect([...layoutIds].sort()).toEqual([...catalogIds].sort());
});

test("every location has bounded coordinates and all map positions are unique", () => {
  for (const { id } of locations) {
    const node = MAP_LAYOUT.find((entry) => entry.id === id);
    expect(node, id).toBeDefined();
    for (const coordinate of [node!.x, node!.y]) {
      expect(Number.isFinite(coordinate), id).toBe(true);
      expect(coordinate, id).toBeGreaterThanOrEqual(0);
      expect(coordinate, id).toBeLessThanOrEqual(1000);
    }
  }
  expect(new Set(MAP_LAYOUT.map(({ x, y }) => `${x},${y}`)).size).toBe(MAP_LAYOUT.length);
});
