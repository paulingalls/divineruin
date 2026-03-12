import { test, expect } from "../fixtures/character.js";

test.describe("Session summary", () => {
  test("redirects to home when no summary data exists", async ({
    authenticatedPage,
    seededCharacter: _,
  }) => {
    // Navigate directly to session-summary with no summary in store.
    // The screen should redirect to home since sessionSummary is null.
    await authenticatedPage.goto("/session-summary");
    await authenticatedPage.waitForLoadState("domcontentloaded");

    // Should land on home screen (redirect from session-summary)
    await expect(
      authenticatedPage
        .getByText(/ENTER AETHOS|Your story is about to begin/i)
        .first(),
    ).toBeVisible({ timeout: 15_000 });
  });
});
