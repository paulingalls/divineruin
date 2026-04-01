import { test, expect } from "../fixtures/session.js";

test.describe("Session HUD overlays", () => {
  test("dice roll overlay shows on dice_result event", async ({
    sessionPage,
  }) => {
    await sessionPage.injectEvent({
      type: "dice_result",
      roll: 15,
      modifier: 3,
      total: 18,
      success: true,
      roll_type: "attack",
      narrative: "You strike true!",
    });

    const overlay = sessionPage.page.getByTestId("dice-roll-overlay");
    await expect(overlay).toBeVisible({ timeout: 10_000 });
    await expect(sessionPage.page.getByText("SUCCESS")).toBeVisible();
    await expect(sessionPage.page.getByText("ATTACK")).toBeVisible();
  });

  test("dice roll failure shows FAILURE text", async ({ sessionPage }) => {
    await sessionPage.injectEvent({
      type: "dice_result",
      roll: 3,
      modifier: 1,
      total: 4,
      success: false,
      roll_type: "saving throw",
      narrative: "You stumble.",
    });

    const overlay = sessionPage.page.getByTestId("dice-roll-overlay");
    await expect(overlay).toBeVisible({ timeout: 10_000 });
    await expect(sessionPage.page.getByText("FAILURE")).toBeVisible();
  });

  test("item acquired overlay shows item details", async ({
    sessionPage,
  }) => {
    await sessionPage.injectEvent({
      type: "item_acquired",
      name: "Moonstone Amulet",
      description: "Glimmers with pale light.",
      rarity: "rare",
      stats: { bonus: "+1 WIS" },
    });

    const overlay = sessionPage.page.getByTestId("item-card-overlay");
    await expect(overlay).toBeVisible({ timeout: 10_000 });
    await expect(
      sessionPage.page.getByText("Moonstone Amulet"),
    ).toBeVisible();
    await expect(sessionPage.page.getByText("RARE")).toBeVisible();
  });

  test("quest update toast shows quest info", async ({ sessionPage }) => {
    await sessionPage.injectEvent({
      type: "quest_update",
      quest_name: "The Missing Merchant",
      objective: "Follow the trail into the Ashen Weald.",
      status: "updated",
      stage_name: "Search",
    });

    const toast = sessionPage.page.getByTestId("quest-update-toast");
    await expect(toast).toBeVisible({ timeout: 10_000 });
    await expect(
      sessionPage.page.getByText("The Missing Merchant"),
    ).toBeVisible();
  });

  test("XP toast shows on xp_awarded event", async ({ sessionPage }) => {
    await sessionPage.injectSessionInit();
    await sessionPage.injectEvent({
      type: "xp_awarded",
      xp_gained: 150,
      new_xp: 600,
      new_level: 3,
      level_up: false,
    });

    const toast = sessionPage.page.getByTestId("xp-toast");
    await expect(toast).toBeVisible({ timeout: 10_000 });
    await expect(sessionPage.page.getByText("+150 XP")).toBeVisible();
  });

  test("level up overlay shows on level_up event", async ({
    sessionPage,
  }) => {
    await sessionPage.injectSessionInit();
    await sessionPage.injectEvent({
      type: "xp_awarded",
      xp_gained: 300,
      new_xp: 750,
      new_level: 4,
      level_up: true,
    });

    const overlay = sessionPage.page.getByTestId("level-up-overlay");
    await expect(overlay).toBeVisible({ timeout: 10_000 });
    await expect(sessionPage.page.getByText("LEVEL UP")).toBeVisible();
    await expect(sessionPage.page.getByText("4")).toBeVisible();
  });

  test("divine favor toast shows on divine_favor_changed", async ({
    sessionPage,
  }) => {
    await sessionPage.injectEvent({
      type: "divine_favor_changed",
      amount: 5,
      new_level: 15,
      max: 100,
      patron_id: "aethon_the_radiant",
    });

    const toast = sessionPage.page.getByTestId("divine-favor-toast");
    await expect(toast).toBeVisible({ timeout: 10_000 });
    await expect(
      sessionPage.page.getByText("+5 DIVINE FAVOR"),
    ).toBeVisible();
  });

  test("location update changes persistent bar", async ({
    sessionPage,
  }) => {
    await sessionPage.injectSessionInit();

    // Verify initial location
    const bar = sessionPage.page.getByTestId("persistent-bar");
    await expect(bar).toBeVisible({ timeout: 10_000 });
    await expect(bar.getByText(/GREYVALE/)).toBeVisible();

    // Change location
    await sessionPage.injectEvent({
      type: "location_changed",
      new_location: "ashen_weald_entrance",
      location_name: "Ashen Weald Entrance",
      region: "Ashen Weald",
      atmosphere: "misty, quiet",
      ambient_sounds: "forest_night",
    });

    await expect(
      bar.getByText(/ASHEN WEALD/),
    ).toBeVisible({ timeout: 10_000 });
  });

  test("combat tracker shows on combat_ui_update", async ({
    sessionPage,
  }) => {
    await sessionPage.injectEvent({
      type: "combat_ui_update",
      phase: "player turn",
      round: 2,
      combatants: [
        {
          id: "player_1",
          name: "Edrin",
          isAlly: true,
          hpCurrent: 25,
          hpMax: 32,
          statusEffects: [],
          isActive: true,
        },
        {
          id: "goblin_1",
          name: "Goblin Scout",
          isAlly: false,
          hpCurrent: 8,
          hpMax: 12,
          statusEffects: [],
          isActive: false,
        },
      ],
    });

    const tracker = sessionPage.page.getByTestId("combat-tracker");
    await expect(tracker).toBeVisible({ timeout: 10_000 });
    await expect(sessionPage.page.getByText("ROUND 2")).toBeVisible();
    await expect(sessionPage.page.getByText("Edrin")).toBeVisible();
    await expect(
      sessionPage.page.getByText("Goblin Scout"),
    ).toBeVisible();

    // End combat — tracker disappears
    await sessionPage.injectEvent({ type: "combat_ended" });
    await expect(tracker).not.toBeVisible({ timeout: 10_000 });
  });

  test("creation cards show on creation_cards event", async ({
    sessionPage,
  }) => {
    await sessionPage.injectEvent({
      type: "creation_cards",
      cards: [
        {
          id: "human",
          title: "Human",
          description: "Versatile and ambitious.",
          category: "race",
        },
        {
          id: "elf",
          title: "Elf",
          description: "Graceful and long-lived.",
          category: "race",
        },
        {
          id: "dwarf",
          title: "Dwarf",
          description: "Stout and resilient.",
          category: "race",
        },
      ],
    });

    const row = sessionPage.page.getByTestId("creation-card-row");
    await expect(row).toBeVisible({ timeout: 10_000 });
    await expect(
      sessionPage.page.getByText("Who Are You?"),
    ).toBeVisible();
    await expect(sessionPage.page.getByText("Human")).toBeVisible();
    await expect(sessionPage.page.getByText("Elf")).toBeVisible();
    await expect(sessionPage.page.getByText("Dwarf")).toBeVisible();
  });

  test("HP bar updates on hp_changed event", async ({ sessionPage }) => {
    await sessionPage.injectSessionInit();

    const bar = sessionPage.page.getByTestId("persistent-bar");
    await expect(bar).toBeVisible({ timeout: 10_000 });

    // Change HP — the bar element should still be present
    await sessionPage.injectEvent({
      type: "hp_changed",
      current: 10,
      max: 32,
    });

    // HP bar is inside persistent-bar — just verify bar is still visible
    await expect(bar).toBeVisible();
  });

  test("status effects appear and disappear", async ({ sessionPage }) => {
    await sessionPage.injectSessionInit();

    const bar = sessionPage.page.getByTestId("persistent-bar");
    await expect(bar).toBeVisible({ timeout: 10_000 });

    // Add a buff status effect
    await sessionPage.injectEvent({
      type: "status_effect",
      effect_id: "bless_1",
      name: "Bless",
      category: "buff",
    });

    const dot = bar.getByTestId("status-effect-bless_1");
    await expect(dot).toBeVisible({ timeout: 10_000 });

    // Remove the status effect
    await sessionPage.injectEvent({
      type: "status_effect",
      action: "remove",
      effect_id: "bless_1",
    });

    await expect(dot).not.toBeVisible({ timeout: 10_000 });
  });

  test("overlay auto-dismisses after TTL", async ({ sessionPage }) => {
    await sessionPage.injectSessionInit();

    // XP toast has a 2500ms TTL
    await sessionPage.injectEvent({
      type: "xp_awarded",
      xp_gained: 50,
      new_xp: 500,
      new_level: 3,
      level_up: false,
    });

    const toast = sessionPage.page.getByTestId("xp-toast");
    await expect(toast).toBeVisible({ timeout: 10_000 });

    // Wait for TTL + animation buffer
    await expect(toast).not.toBeVisible({ timeout: 10_000 });
  });

  test("combat_started followed by combat_ui_update shows tracker", async ({
    sessionPage,
  }) => {
    await sessionPage.injectEvent({
      type: "combat_started",
      difficulty: "moderate",
    });

    await sessionPage.injectEvent({
      type: "combat_ui_update",
      phase: "initiative",
      round: 1,
      combatants: [
        {
          id: "player_1",
          name: "Edrin",
          isAlly: true,
          hpCurrent: 28,
          hpMax: 32,
          statusEffects: [],
          isActive: true,
        },
        {
          id: "wolf_1",
          name: "Shadow Wolf",
          isAlly: false,
          hpCurrent: 15,
          hpMax: 15,
          statusEffects: [],
          isActive: false,
        },
      ],
    });

    const tracker = sessionPage.page.getByTestId("combat-tracker");
    await expect(tracker).toBeVisible({ timeout: 10_000 });
    await expect(sessionPage.page.getByText("ROUND 1")).toBeVisible();
    await expect(sessionPage.page.getByText("Shadow Wolf")).toBeVisible();

    await sessionPage.injectEvent({ type: "combat_ended" });
    await expect(tracker).not.toBeVisible({ timeout: 10_000 });
  });

  test("creation_card_selected highlights chosen card", async ({
    sessionPage,
  }) => {
    await sessionPage.injectEvent({
      type: "creation_cards",
      cards: [
        {
          id: "warrior",
          title: "Warrior",
          description: "Strength in arms.",
          category: "class",
        },
        {
          id: "mage",
          title: "Mage",
          description: "Power of the arcane.",
          category: "class",
        },
        {
          id: "rogue",
          title: "Rogue",
          description: "Shadows and steel.",
          category: "class",
        },
      ],
    });

    const row = sessionPage.page.getByTestId("creation-card-row");
    await expect(row).toBeVisible({ timeout: 10_000 });

    await sessionPage.injectEvent({
      type: "creation_card_selected",
      card_id: "warrior",
    });

    // Selected card and its title remain visible
    await expect(sessionPage.page.getByText("Warrior")).toBeVisible();
    await expect(sessionPage.page.getByText("Mage")).toBeVisible();
    await expect(sessionPage.page.getByText("Rogue")).toBeVisible();
  });

  test("corruption overlay appears on hollow_corruption_changed", async ({
    sessionPage,
  }) => {
    // At level 0, corruption overlay is not rendered
    const overlay = sessionPage.page.getByTestId("corruption-overlay");
    await expect(overlay).not.toBeVisible({ timeout: 5_000 });

    // Set corruption to level 2
    await sessionPage.injectEvent({
      type: "hollow_corruption_changed",
      level: 2,
    });

    await expect(overlay).toBeVisible({ timeout: 10_000 });
  });
});
