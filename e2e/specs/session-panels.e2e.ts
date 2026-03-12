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
});
