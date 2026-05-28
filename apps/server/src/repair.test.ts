import { beforeEach, describe, expect, mock, test } from "bun:test";

// --- module mocks (db sql call-sequence + items.getItem) ---------------------

let mockCallHandler: (strings: TemplateStringsArray, ...values: unknown[]) => Promise<unknown[]>;
let lastQueryValues: unknown[] = [];

void mock.module("./db.ts", () => {
  const mockSql = Object.assign(
    (strings: TemplateStringsArray, ...values: unknown[]) => {
      lastQueryValues = values;
      return mockCallHandler(strings, ...values);
    },
    { close: () => Promise.resolve() },
  );
  return { sql: mockSql };
});

function setMockResults(...results: unknown[][]) {
  let callIndex = 0;
  mockCallHandler = () => {
    const result = results[callIndex] ?? [];
    callIndex++;
    return Promise.resolve(result);
  };
}

// items.ts is intentionally NOT mock.module'd: that mock is process-global in Bun
// and would leak a partial module (only getItem, no parseItemRow) into
// items-load.test.ts run in the same process. handleRepairQuote takes an injected
// getItemFn instead, so these tests control the item without touching the registry.
import type { Item } from "@divineruin/shared";

import { setPricing } from "./pricing.ts";

let mockItem: Partial<Item> | undefined;
const stubGetItem = (_id: string): Item | undefined => mockItem as Item | undefined;

const { handleRepairQuote, repairQuote, resolveDisposition } = await import("./repair.ts");

function repairReq(itemId: string, npc?: string): Request {
  const q = npc === undefined ? "" : `?npc=${npc}`;
  return new Request(`http://localhost/api/repair/${itemId}${q}`);
}

beforeEach(() => {
  setMockResults();
  mockItem = undefined;
  // repairQuote reads the DB-loaded pricing singleton; seed it for the unit run.
  setPricing({
    repairCostSp: { common: 2, uncommon: 10, rare: 50, legendary: 200 },
    dispositionMultipliers: { friendly: 0.8, trusted: 0.6 },
    silverPerGold: 10,
  });
});

// repairQuote mirrors the Python durability.calculate_repair_cost +
// workspace.compute_rental_price so the REST quote == the agent tool's charge.
describe("repairQuote", () => {
  test("neutral pays the flat rarity sp value", () => {
    expect(repairQuote("common", "neutral")).toEqual({ available: true, priceSp: 2, reason: "" });
    expect(repairQuote("rare", "neutral").priceSp).toBe(50);
    expect(repairQuote("legendary", "neutral").priceSp).toBe(200);
  });

  test("friendly = 0.8x, trusted = 0.6x", () => {
    expect(repairQuote("uncommon", "friendly").priceSp).toBeCloseTo(8); // 10 * 0.8
    expect(repairQuote("common", "trusted").priceSp).toBeCloseTo(1.2); // 2 * 0.6
  });

  test("cautious aliases neutral (full price)", () => {
    expect(repairQuote("common", "cautious").priceSp).toBe(2);
  });

  test("disposition is case-insensitive (mirrors Python .lower())", () => {
    expect(repairQuote("uncommon", "Friendly").priceSp).toBeCloseTo(8); // not full 10
    expect(repairQuote("rare", "NEUTRAL").priceSp).toBe(50);
    expect(repairQuote("rare", "Wary").available).toBe(false);
  });

  test("below Neutral refuses (unavailable, no charge)", () => {
    for (const disposition of ["wary", "hostile"]) {
      const q = repairQuote("rare", disposition);
      expect(q.available).toBe(false);
      expect(q.priceSp).toBe(0);
      expect(q.reason).toBeTruthy();
    }
  });

  test("throws on unknown rarity or disposition", () => {
    expect(() => repairQuote("mythic", "neutral")).toThrow();
    expect(() => repairQuote("common", "smitten")).toThrow();
  });
});

describe("resolveDisposition", () => {
  test("returns the per-player standing when present", async () => {
    setMockResults([{ data: JSON.stringify({ disposition: "friendly" }) }]);
    expect(await resolveDisposition("grimjaw", "player_1")).toBe("friendly");
    expect(lastQueryValues).toEqual(["grimjaw", "player_1"]);
  });

  test("falls back to the NPC's default_disposition when no standing", async () => {
    setMockResults([], [{ data: { default_disposition: "wary" } }]);
    expect(await resolveDisposition("grimjaw", "player_1")).toBe("wary");
  });

  test("falls back to neutral when neither exists", async () => {
    setMockResults([], []);
    expect(await resolveDisposition("grimjaw", "player_1")).toBe("neutral");
  });
});

describe("handleRepairQuote", () => {
  test("prices a rare item at a neutral blacksmith (priceSp 50)", async () => {
    mockItem = { id: "blade_rare", rarity: "rare", durability_tier: "reinforced" };
    setMockResults([{ data: JSON.stringify({ disposition: "neutral" }) }]);
    const resp = await handleRepairQuote(
      repairReq("blade_rare", "grimjaw"),
      "player_1",
      "blade_rare",
      stubGetItem,
    );
    expect(resp.status).toBe(200);
    expect(await resp.json()).toEqual({
      itemId: "blade_rare",
      rarity: "rare",
      disposition: "neutral",
      available: true,
      priceSp: 50,
      reason: "",
    });
  });

  test("below-Neutral blacksmith refuses (available:false)", async () => {
    mockItem = { id: "blade_rare", rarity: "rare", durability_tier: "reinforced" };
    setMockResults([{ data: JSON.stringify({ disposition: "wary" }) }]);
    const body = (await (
      await handleRepairQuote(
        repairReq("blade_rare", "grimjaw"),
        "player_1",
        "blade_rare",
        stubGetItem,
      )
    ).json()) as {
      available: boolean;
      priceSp: number;
    };
    expect(body.available).toBe(false);
    expect(body.priceSp).toBe(0);
  });

  test("404 on an unknown item", async () => {
    mockItem = undefined;
    const resp = await handleRepairQuote(
      repairReq("ghost", "grimjaw"),
      "player_1",
      "ghost",
      stubGetItem,
    );
    expect(resp.status).toBe(404);
  });

  test("400 on a non-durable item", async () => {
    mockItem = { id: "potion", rarity: "common" }; // no durability_tier
    const resp = await handleRepairQuote(
      repairReq("potion", "grimjaw"),
      "player_1",
      "potion",
      stubGetItem,
    );
    expect(resp.status).toBe(400);
  });

  test("400 when the npc query param is missing", async () => {
    mockItem = { id: "blade_rare", rarity: "rare", durability_tier: "reinforced" };
    const resp = await handleRepairQuote(
      repairReq("blade_rare"),
      "player_1",
      "blade_rare",
      stubGetItem,
    );
    expect(resp.status).toBe(400);
  });
});
