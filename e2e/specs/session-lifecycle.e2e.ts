import { test, expect } from "../fixtures/session.js";

test.describe("Session lifecycle", () => {
  test("session_end populates summary screen", async ({ sessionPage }) => {
    await sessionPage.injectSessionInit();

    await sessionPage.injectEvent({
      type: "session_end",
      summary: "You explored the ruins and discovered a hidden passage.",
      xp_earned: 200,
      items_found: ["Moonstone Amulet"],
      quest_progress: ["The Missing Merchant"],
      duration: 1800,
      next_hooks: ["The passage leads deeper underground."],
      story_moments: [],
    });

    // Phase watcher in session-test.tsx auto-navigates to /session-summary
    const summaryScreen = sessionPage.page.getByTestId(
      "session-summary-screen",
    );
    await expect(summaryScreen).toBeVisible({ timeout: 15_000 });
    await expect(
      sessionPage.page.getByText("Session Complete"),
    ).toBeVisible();
    await expect(
      sessionPage.page.getByText(/explored the ruins/),
    ).toBeVisible();
    await expect(sessionPage.page.getByText("RETURN HOME")).toBeVisible();
  });

  test("summary shows XP, items, and quest counts", async ({
    sessionPage,
  }) => {
    await sessionPage.injectSessionInit();

    await sessionPage.injectEvent({
      type: "session_end",
      summary: "A productive adventure.",
      xp_earned: 350,
      items_found: ["Iron Shield", "Health Potion"],
      quest_progress: ["The Missing Merchant", "Hollow Threat"],
      duration: 2700,
      next_hooks: [],
      story_moments: [],
    });

    const summaryScreen = sessionPage.page.getByTestId(
      "session-summary-screen",
    );
    await expect(summaryScreen).toBeVisible({ timeout: 15_000 });

    // Stats row shows correct values
    await expect(sessionPage.page.getByText("350")).toBeVisible();
    await expect(sessionPage.page.getByText("XP")).toBeVisible();
    await expect(sessionPage.page.getByText("Items")).toBeVisible();
    await expect(sessionPage.page.getByText("Quests")).toBeVisible();
  });
});
