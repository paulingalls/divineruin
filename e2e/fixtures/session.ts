import { type Page } from "@playwright/test";
import { test as characterTest, type TestCharacter, TEST_CHARACTER } from "./character.js";

/** Mirrors DataChannelEvent from the mobile app — kept inline to avoid cross-project imports. */
interface GameEvent {
  type: string;
  [key: string]: unknown;
}

export interface SessionPage {
  page: Page;
  injectEvent: (event: GameEvent) => Promise<void>;
  injectSessionInit: (overrides?: Record<string, unknown>) => Promise<void>;
  openPanel: (tab: string) => Promise<void>;
  closePanel: () => Promise<void>;
}

export const test = characterTest.extend<{
  sessionPage: SessionPage;
  testCharacter: TestCharacter;
}>({
  sessionPage: async ({ characterPage, testCharacter }, use) => {
    await characterPage.goto("/session-test");

    // Wait for window.__DR to be exposed
    await characterPage.waitForFunction(
      () =>
        typeof (window as Record<string, unknown>).__DR === "object" &&
        typeof ((window as Record<string, unknown>).__DR as Record<string, unknown>)
          ?.handleGameEvent === "function",
      null,
      { timeout: 15_000 },
    );

    const injectEvent = async (event: GameEvent) => {
      await characterPage.evaluate((e) => {
        const dr = (window as Record<string, unknown>).__DR as {
          handleGameEvent: (ev: Record<string, unknown>) => void;
        };
        dr.handleGameEvent(e);
      }, event);
    };

    const injectSessionInit = async (
      overrides?: Record<string, unknown>,
    ) => {
      const base: GameEvent = {
        type: "session_init",
        character: {
          player_id: testCharacter.playerId,
          name: testCharacter.name,
          race: testCharacter.race,
          class: testCharacter.className,
          level: testCharacter.level,
          xp: TEST_CHARACTER.xp,
          location_id: testCharacter.locationId,
          location_name: testCharacter.locationName,
          hp: TEST_CHARACTER.hp,
          attributes: {
            strength: 14,
            dexterity: 12,
            constitution: 14,
            intelligence: 10,
            wisdom: 13,
            charisma: 8,
          },
          ac: 16,
          gold: 35,
          proficiencies: ["Athletics", "Survival"],
          saving_throw_proficiencies: ["Strength", "Constitution"],
          equipment: {
            main_hand: { name: "Iron Longsword" },
            armor: { name: "Chain Mail" },
            shield: null,
          },
        },
        location: {
          id: testCharacter.locationId,
          name: testCharacter.locationName,
          atmosphere: "warm hearth, murmured conversations",
          region: "Greyvale",
          tags: ["tavern", "safe"],
          ambient_sounds: "tavern_ambience",
        },
        world_state: { time: "evening" },
        inventory: [
          {
            id: "item_health_potion",
            name: "Health Potion",
            type: "consumable",
            rarity: "common",
            description: "Restores 2d4+2 hit points.",
            weight: 0.5,
            effects: [],
            lore: "",
            value_base: 50,
            slot_info: { quantity: 2, equipped: false },
          },
          {
            id: "item_iron_longsword",
            name: "Iron Longsword",
            type: "weapon",
            rarity: "common",
            description: "A sturdy iron blade.",
            weight: 3,
            effects: [],
            lore: "",
            value_base: 15,
            slot_info: { quantity: 1, equipped: true },
          },
        ],
        quests: [
          {
            quest_id: "q_missing_merchant",
            quest_name: "The Missing Merchant",
            type: "main",
            current_stage: 0,
            stages: [
              {
                id: "stage_0",
                name: "Investigate",
                objective:
                  "Ask around the tavern about the missing merchant.",
              },
              {
                id: "stage_1",
                name: "Search",
                objective: "Follow the trail into the Ashen Weald.",
                target_location_id: "ashen_weald_entrance",
              },
            ],
            global_hints: {},
          },
        ],
        ...overrides,
      };
      await injectEvent(base);
    };

    const openPanel = async (tab: string) => {
      await characterPage.evaluate((t) => {
        const dr = (window as Record<string, unknown>).__DR as {
          openPanel: (tab: string) => void;
        };
        dr.openPanel(t);
      }, tab);
    };

    const closePanel = async () => {
      await characterPage.evaluate(() => {
        const dr = (window as Record<string, unknown>).__DR as {
          closePanel: () => void;
        };
        dr.closePanel();
      });
    };

    await use({ page: characterPage, injectEvent, injectSessionInit, openPanel, closePanel });
  },
});

export { expect } from "@playwright/test";
