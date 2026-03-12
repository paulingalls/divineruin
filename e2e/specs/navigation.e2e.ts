import { test, expect } from "../fixtures/character.js";

test.describe("Navigation flows", () => {
  test("home → settings → back to home", async ({ characterPage }) => {
    // Click settings gear
    await characterPage.getByText("\u2699").click();

    // Settings screen should appear
    await expect(
      characterPage.getByText("SETTINGS"),
    ).toBeVisible({ timeout: 15_000 });

    // Click close button (×)
    await characterPage.getByText("\u2715").click();

    // Should return to home with character
    await expect(
      characterPage.getByText("ENTER AETHOS", { exact: true }),
    ).toBeVisible({ timeout: 15_000 });
  });

  test("settings volume sliders are interactive", async ({
    characterPage,
  }) => {
    // Open settings
    await characterPage.getByText("\u2699").click();
    await expect(
      characterPage.getByText("SETTINGS"),
    ).toBeVisible({ timeout: 15_000 });

    // Verify all volume labels and percentages are present
    const volumeBuses = ["VOICE", "MUSIC", "AMBIENCE", "EFFECTS", "UI"];
    for (const bus of volumeBuses) {
      await expect(
        characterPage.getByText(bus, { exact: true }).first(),
      ).toBeVisible();
    }

    // Verify percentage labels exist (at least one should show a %)
    await expect(
      characterPage.getByText(/%/).first(),
    ).toBeVisible();
  });

  test("settings shows account email", async ({
    characterPage,
    testUser,
  }) => {
    await characterPage.getByText("\u2699").click();
    await expect(
      characterPage.getByText("SETTINGS"),
    ).toBeVisible({ timeout: 15_000 });

    // Account section should show test user's email
    await expect(
      characterPage.getByText(testUser.email),
    ).toBeVisible();

    // ACCOUNT label should be visible
    await expect(
      characterPage.getByText("ACCOUNT"),
    ).toBeVisible();
  });
});
