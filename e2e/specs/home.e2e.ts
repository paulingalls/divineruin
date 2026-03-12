import { test, expect } from "../fixtures/auth.js";

test.describe("Home screen", () => {
  test("shows home screen for authenticated new user", async ({
    authenticatedPage,
  }) => {
    // New user should see the welcome state
    await expect(
      authenticatedPage.getByText("Your story is about to begin."),
    ).toBeVisible({ timeout: 15_000 });

    // AWAKEN button should be present
    await expect(
      authenticatedPage.getByText("AWAKEN", { exact: true }),
    ).toBeVisible();
  });
});
