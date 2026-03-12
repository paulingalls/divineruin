import { test, expect, seedActivity, queryDb } from "../fixtures/character.js";

test.describe("Catch-up feed", () => {
  test("shows resolved activity with pending decision", async ({
    characterPage,
    testCharacter,
  }) => {
    const activityId = `activity_e2e_${Date.now()}`;

    // Seed a resolved activity with decision options
    await seedActivity(testCharacter.playerId, {
      id: activityId,
      type: "crafting",
      status: "resolved",
      narrationText:
        "The smith examines your work and nods slowly. The iron blade holds true.",
      decisionOptions: [
        { id: "keep", label: "Keep the blade" },
        { id: "sell", label: "Sell at market" },
      ],
      parameters: {
        result_item_name: "Iron Sword",
        recipe_id: "iron_sword",
      },
    });

    // Reload to pick up the new feed data
    await characterPage.reload();
    await characterPage.waitForLoadState("domcontentloaded");

    // Activity title should appear
    await expect(
      characterPage.getByText("Iron Sword"),
    ).toBeVisible({ timeout: 15_000 });

    // Narration summary text should appear
    await expect(
      characterPage.getByText(/iron blade holds true/i),
    ).toBeVisible();

    // Decision options should be visible
    await expect(
      characterPage.getByText("Keep the blade"),
    ).toBeVisible();
    await expect(
      characterPage.getByText("Sell at market"),
    ).toBeVisible();

    // Cleanup
    await queryDb(`DELETE FROM async_activities WHERE id = $1`, [activityId]);
  });

  test("shows in-progress activity with progress", async ({
    characterPage,
    testCharacter,
  }) => {
    const activityId = `activity_e2e_prog_${Date.now()}`;
    const now = new Date();

    await seedActivity(testCharacter.playerId, {
      id: activityId,
      type: "training",
      status: "in_progress",
      startTime: new Date(now.getTime() - 1_800_000), // 30 min ago
      resolveAt: new Date(now.getTime() + 1_800_000), // 30 min from now
      parameters: {
        program_id: "combat_basics",
        stat: "strength",
        dc: 13,
      },
      progressStages: [
        "Warming up with basic drills...",
        "Sparring with a training dummy...",
        "Working on advanced techniques...",
      ],
    });

    await characterPage.reload();
    await characterPage.waitForLoadState("domcontentloaded");

    // Training title should appear
    await expect(
      characterPage.getByText("Strength Training").first(),
    ).toBeVisible({ timeout: 15_000 });

    // Cleanup
    await queryDb(`DELETE FROM async_activities WHERE id = $1`, [activityId]);
  });
});
