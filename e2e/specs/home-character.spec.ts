import { test, expect } from "../fixtures/character.js";

test.describe("Home screen with character", () => {
  test("shows character summary and enter button", async ({
    characterPage,
    testCharacter,
  }) => {
    // Character name visible
    await expect(
      characterPage.getByText(testCharacter.name),
    ).toBeVisible({ timeout: 15_000 });

    // Class and level
    await expect(
      characterPage.getByText(new RegExp(`Lv\\.\\s*${testCharacter.level}`)),
    ).toBeVisible();

    // ENTER AETHOS button (not AWAKEN — character exists)
    await expect(
      characterPage.getByText("ENTER AETHOS", { exact: true }),
    ).toBeVisible();

    // Settings gear visible
    await expect(characterPage.getByText("\u2699")).toBeVisible();
  });

  test("shows companion idle chatter when no activities", async ({
    characterPage,
  }) => {
    // The catch-up feed should show companion idle chatter
    // since there are no resolved/pending activities
    await expect(
      characterPage.getByText("Companion"),
    ).toBeVisible({ timeout: 15_000 });
  });
});
