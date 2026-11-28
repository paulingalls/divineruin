import { expect, test } from "bun:test";
import items from "../../../content/items.json";
import pools from "../../../content/inventory_pools.json";
import npcs from "../../../content/npcs.json";
import roles from "../../../content/role_archetypes.json";
import cases from "../../../packages/shared/fixtures/inventory-pool-cases.json";
import legacy from "../../../packages/shared/fixtures/legacy-inventory-pools.json";
import { parseItemRow } from "./items.ts";
import { boundInventoryPools, parseInventoryPools } from "./inventory_pools.ts";

const rows = <T extends { id: string }>(data: T[]) =>
  data.map((row) => ({ id: row.id, data: row }));
const itemRows = rows(items);

test("matches the tiered spec pools, stock catalog, and bindings", () => {
  const catalog = parseInventoryPools(rows(pools), itemRows);
  expect<unknown>(Object.fromEntries(catalog)).toEqual(
    Object.fromEntries(cases.pools.map((row) => [row.id, row])),
  );
  boundInventoryPools(rows(npcs), catalog);
  expect(
    Object.fromEntries(
      npcs.filter((npc) => npc.inventory_pool !== null).map((npc) => [npc.id, npc.inventory_pool]),
    ),
  ).toEqual(cases.npc_bindings);
  expect(Object.fromEntries(roles.map((role) => [role.id, role.inventory_pool]))).toEqual(
    cases.role_bindings,
  );

  const authored = new Map(Object.entries(cases.items));
  const stocked = new Set<string>();
  for (const pool of catalog.values()) {
    const ids = [
      ...pool.tier_1_items,
      ...[...pool.tier_2_items, ...pool.tier_3_items].map((row) => row.item_id),
    ];
    for (const id of ids) {
      const expected = authored.get(id);
      if (!expected) continue;
      const item = parseItemRow(
        id,
        items.find((row) => row.id === id),
      );
      expect({ value_base: item.value_base, rarity: item.rarity, type: item.type }).toEqual(
        expected,
      );
      expect(pool.buys === "all" || pool.buys.includes(item.type)).toBe(true);
      expect(pool.buys_rarities).toContain(item.rarity);
      stocked.add(id);
    }
  }
  expect(stocked).toEqual(new Set(authored.keys()));
});

test("the masterwork rotation mirrors the standard weapon stock", () => {
  const catalog = parseInventoryPools(rows(pools), itemRows);
  const weapons = [catalog.get("weapons_armor_basic")!, catalog.get("weapons_armor_quality")!];
  const byId = new Map<string, unknown>(items.map((row) => [row.id, row]));
  const variants = Object.entries(cases.masterwork_variants);
  expect(variants).toHaveLength(15);
  expect(new Set(variants.map(([, variant]) => variant)).size).toBe(15);
  const standard = weapons
    .flatMap((pool) => pool.tier_2_items)
    .map((row) => row.item_id)
    .filter((id) => parseItemRow(id, byId.get(id)).type === "weapon");
  expect(new Set(standard)).toEqual(new Set(variants.map(([base]) => base)));

  const rotation = weapons
    .flatMap((pool) => pool.tier_3_items)
    .filter((row) => row.rotation_group === "masterwork_weapons");
  expect(rotation.map((row) => row.item_id).sort()).toEqual(
    variants.map(([, variant]) => variant).sort(),
  );
  for (const row of rotation) {
    expect(row.settlements).toEqual(["city", "capital"]);
    expect(row.presence_chance).toBe(1);
    expect(row.restock_check).toBe("weekly");
  }
  for (const [baseId, variantId] of variants) {
    const base = parseItemRow(baseId, byId.get(baseId));
    const variant = parseItemRow(variantId, byId.get(variantId));
    expect(variant).toHaveProperty("damage_bonus", 1);
    expect(variant.description).toContain("well-balanced");
    expect(variant.value_base).toBeGreaterThan(base.value_base);
    for (const field of [
      "weapon_category",
      "weapon_range",
      "weapon_kind",
      "damage_dice",
      "properties",
    ] as const) {
      expect(variant[field]).toEqual(base[field]);
    }
    expect(variant.effects).toEqual(base.effects);
  }
});

for (const row of cases.malformed) {
  test(`refuses ${row.pool} ${row.path.join(".")} ${row.remove ? "missing" : JSON.stringify(row.value)}`, () => {
    const source = structuredClone(pools.find((pool) => pool.id === row.pool)!);
    const target = row.path
      .slice(0, -1)
      .reduce<Record<string, unknown>>((node, key) => node[key] as Record<string, unknown>, source);
    const field = row.path.at(-1)!;
    if (row.remove) delete target[field];
    else target[field] = row.value;
    expect(() => parseInventoryPools(rows([source]), itemRows)).toThrow(
      `inventory_pools[${row.pool}]${row.diagnostic}`,
    );
  });
}

test("refuses a historical flat pool", () => {
  expect(() => parseInventoryPools(rows(legacy.pools), itemRows)).toThrow(
    /inventory_pools\[.*\]\.(location|items|restock_interval_hours)/,
  );
});

test("refuses an empty item catalog", () => {
  expect(() => parseInventoryPools(rows(pools), [])).toThrow("items produced no rows");
});
