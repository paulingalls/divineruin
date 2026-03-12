import { test, expect } from "../fixtures/auth.js";

test.describe("Settings screen", () => {
  test("shows settings and can sign out", async ({ authenticatedPage }) => {
    // Navigate to settings
    await authenticatedPage.goto("/settings");
    await authenticatedPage.waitForLoadState("domcontentloaded");

    // Assert settings title
    await expect(authenticatedPage.getByText("SETTINGS")).toBeVisible({
      timeout: 15_000,
    });

    // Assert volume labels
    for (const label of ["VOICE", "MUSIC", "AMBIENCE", "EFFECTS", "UI"]) {
      await expect(
        authenticatedPage.getByText(label, { exact: true }).first(),
      ).toBeVisible();
    }

    // Assert sign out button
    const signOutButton = authenticatedPage.getByText("SIGN OUT", {
      exact: true,
    });
    await expect(signOutButton).toBeVisible();

    // Click sign out — should redirect to auth screen
    await signOutButton.click();

    await expect(
      authenticatedPage.getByText("Listen to the dark"),
    ).toBeVisible({ timeout: 15_000 });
  });
});
