import { test, expect } from "../fixtures/session.js";

test.describe("Session panel interactions", () => {
  test("inventory panel shows items after session_init", async ({
    sessionPage,
  }) => {
    await sessionPage.injectSessionInit();

    const bar = sessionPage.page.getByTestId("persistent-bar");
    await expect(bar).toBeVisible({ timeout: 10_000 });

    await sessionPage.openPanel("inventory");

    // Verify items are visible
    await expect(
      sessionPage.page.getByText("Health Potion"),
    ).toBeVisible({ timeout: 10_000 });
    await expect(
      sessionPage.page.getByText("Iron Longsword"),
    ).toBeVisible();
  });

  test("quest log panel shows quests after session_init", async ({
    sessionPage,
  }) => {
    await sessionPage.injectSessionInit();

    const bar = sessionPage.page.getByTestId("persistent-bar");
    await expect(bar).toBeVisible({ timeout: 10_000 });

    await sessionPage.openPanel("quests");

    const questName = sessionPage.page.getByText("The Missing Merchant");
    await expect(questName).toBeVisible({ timeout: 10_000 });

    // Quest rows start collapsed — click to expand and reveal the objective
    await questName.click();
    await expect(
      sessionPage.page.getByText(/Ask around the tavern/),
    ).toBeVisible({ timeout: 10_000 });
  });

  test("panel can be dismissed", async ({
    sessionPage,
  }) => {
    await sessionPage.injectSessionInit();

    const bar = sessionPage.page.getByTestId("persistent-bar");
    await expect(bar).toBeVisible({ timeout: 10_000 });

    await sessionPage.openPanel("character");

    // Verify panel is open — the tab bar shows CHARACTER
    await expect(
      sessionPage.page.getByText("CHARACTER", { exact: true }),
    ).toBeVisible({ timeout: 10_000 });

    // Close via store (GestureDetector intercepts the ✕ click on web)
    await sessionPage.closePanel();

    // Panel should disappear
    await expect(
      sessionPage.page.getByText("INVENTORY", { exact: true }),
    ).not.toBeVisible({ timeout: 10_000 });
  });

  test("inventory_updated replaces inventory items", async ({
    sessionPage,
  }) => {
    await sessionPage.injectSessionInit();

    // Initial inventory from session_init has Health Potion and Iron Longsword
    await sessionPage.openPanel("inventory");
    await expect(
      sessionPage.page.getByText("Health Potion"),
    ).toBeVisible({ timeout: 10_000 });

    await sessionPage.closePanel();

    // Inject inventory_updated with different items
    await sessionPage.injectEvent({
      type: "inventory_updated",
      inventory: [
        {
          id: "item_silver_dagger",
          name: "Silver Dagger",
          type: "weapon",
          rarity: "uncommon",
          description: "A finely crafted silver blade.",
          weight: 1,
          effects: [],
          lore: "",
          value_base: 75,
          slot_info: { quantity: 1, equipped: false },
        },
        {
          id: "item_mana_potion",
          name: "Mana Potion",
          type: "consumable",
          rarity: "common",
          description: "Restores magical energy.",
          weight: 0.5,
          effects: [],
          lore: "",
          value_base: 30,
          slot_info: { quantity: 3, equipped: false },
        },
      ],
    });

    await sessionPage.openPanel("inventory");
    // New items should be visible
    await expect(
      sessionPage.page.getByText("Silver Dagger"),
    ).toBeVisible({ timeout: 10_000 });
    await expect(
      sessionPage.page.getByText("Mana Potion"),
    ).toBeVisible();
    // Old items should be gone (inventory is replaced, not merged)
    await expect(
      sessionPage.page.getByText("Health Potion"),
    ).not.toBeVisible();
  });
});
