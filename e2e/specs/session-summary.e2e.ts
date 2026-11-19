import { test, expect } from "../fixtures/session.js";

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
      authenticatedPage.getByText(/ENTER AETHOS|Your story is about to begin/i).first(),
    ).toBeVisible();
  });
});

async function requestLeave(sessionPage: import("../fixtures/session.js").SessionPage) {
  const { page } = sessionPage;
  await sessionPage.enterFromHome();
  await sessionPage.injectSessionInit();
  await page.clock.install();
  // The browser's clock, not the runner's, may be ahead: pause just past the page's own now.
  await page.clock.pauseAt((await page.evaluate(() => Date.now())) + 1000);
  await page.getByRole("button", { name: "Leave", exact: true }).click();
  await expect(page.getByText("Wrapping up…", { exact: true })).toBeVisible();
  const observations = await page.evaluate(() => window.__DR!.transport);
  expect(observations.packets).toEqual([
    {
      payload: Array.from(new TextEncoder().encode(JSON.stringify({ type: "leave_requested" }))),
      reliable: true,
      topic: "player_hints",
    },
  ]);
  expect(observations.microphone).toEqual([false]);
  expect(observations.disposed).toBe(false);
  await expect(page.getByRole("button", { name: "Muted", exact: true })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Wrapping up…", exact: true })).toBeDisabled();
  return page.evaluateHandle(() => window.__DR!.transport);
}

test("Leave mutes, requests one recap and shows the received summary", async ({ sessionPage }) => {
  const transport = await requestLeave(sessionPage);
  const { page } = sessionPage;
  await page.getByText("Wrapping up…", { exact: true }).click({ force: true });
  expect(await page.evaluate(() => window.__DR!.transport.packets.length)).toBe(1);
  await page.evaluate(() =>
    window.__DR!.injectPacket(
      Array.from(
        new TextEncoder().encode(
          JSON.stringify({
            type: "session_end",
            summary: "The bells rang at farewell.",
            xp_earned: 12,
          }),
        ),
      ),
    ),
  );
  await expect(page.getByTestId("session-summary-screen")).toBeVisible();
  await expect(page.getByText("The bells rang at farewell.")).toBeVisible();
  await page.clock.runFor(16000);
  await expect(page.getByTestId("session-summary-screen")).toBeVisible();
  await transport.dispose();
});

test("Leave returns home at fifteen seconds without a recap", async ({ sessionPage }) => {
  const transport = await requestLeave(sessionPage);
  const { page } = sessionPage;
  await page.clock.runFor(14999);
  await expect(page.getByText("Wrapping up…", { exact: true })).toBeVisible();
  await page.clock.runFor(1);
  await expect(page.getByText(/ENTER AETHOS|Your story is about to begin/i).first()).toBeVisible();
  await expect(page.getByTestId("session-summary-screen")).toBeHidden();
  expect(await transport.evaluate((t) => t.disposed)).toBe(true);
  await transport.dispose();
});
