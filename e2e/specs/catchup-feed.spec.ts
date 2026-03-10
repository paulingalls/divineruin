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
    const startTime = new Date(now.getTime() - 1_800_000); // 30 min ago
    const resolveAt = new Date(now.getTime() + 1_800_000); // 30 min from now
    const data = {
      status: "in_progress",
      activity_type: "training",
      start_time: startTime.toISOString(),
      resolve_at: resolveAt.toISOString(),
      narration_text: null,
      narration_audio_url: null,
      decision_options: null,
      parameters: {
        program_id: "combat_basics",
        stat: "strength",
        dc: 13,
      },
      progress_stages: [
        "Warming up with basic drills...",
        "Sparring with a training dummy...",
        "Working on advanced techniques...",
      ],
    };

    await queryDb(
      `INSERT INTO async_activities (id, player_id, data)
       VALUES ($1, $2, $3::jsonb)
       ON CONFLICT (id) DO UPDATE SET data = $3::jsonb`,
      [activityId, testCharacter.playerId, JSON.stringify(data)],
    );

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
