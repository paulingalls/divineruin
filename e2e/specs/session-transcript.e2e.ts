import { test, expect } from "../fixtures/session.js";

test.describe("Transcript entries", () => {
  test("DM narration appears in transcript", async ({ sessionPage }) => {
    await sessionPage.injectEvent({
      type: "transcript_entry",
      speaker: "dm",
      text: "The ancient door creaks open before you.",
    });

    const view = sessionPage.page.getByTestId("transcript-view");
    await expect(view).toBeVisible({ timeout: 10_000 });
    await expect(
      sessionPage.page.getByText("The ancient door creaks open before you."),
    ).toBeVisible();
  });

  test("player transcript shows You label", async ({ sessionPage }) => {
    await sessionPage.injectEvent({
      type: "transcript_entry",
      speaker: "player",
      text: "I push open the door.",
    });

    await expect(
      sessionPage.page.getByText("You"),
    ).toBeVisible({ timeout: 10_000 });
    await expect(
      sessionPage.page.getByText("I push open the door."),
    ).toBeVisible();
  });

  test("NPC transcript shows character name", async ({ sessionPage }) => {
    await sessionPage.injectEvent({
      type: "transcript_entry",
      speaker: "npc",
      character: "Elder_Mirael",
      text: "Welcome, traveler.",
    });

    // Component replaces underscores with spaces
    await expect(
      sessionPage.page.getByText("Elder Mirael"),
    ).toBeVisible({ timeout: 10_000 });
    await expect(
      sessionPage.page.getByText("Welcome, traveler."),
    ).toBeVisible();
  });

  test("multiple transcript entries accumulate", async ({ sessionPage }) => {
    await sessionPage.injectEvent({
      type: "transcript_entry",
      speaker: "dm",
      text: "The cave is dark and cold.",
    });
    await sessionPage.injectEvent({
      type: "transcript_entry",
      speaker: "player",
      text: "I light a torch.",
    });
    await sessionPage.injectEvent({
      type: "transcript_entry",
      speaker: "dm",
      text: "Warm light fills the passage.",
    });

    await expect(
      sessionPage.page.getByText("The cave is dark and cold."),
    ).toBeVisible({ timeout: 10_000 });
    await expect(
      sessionPage.page.getByText("I light a torch."),
    ).toBeVisible();
    await expect(
      sessionPage.page.getByText("Warm light fills the passage."),
    ).toBeVisible();
  });

  test("tool transcript shows system text", async ({ sessionPage }) => {
    await sessionPage.injectEvent({
      type: "transcript_entry",
      speaker: "tool",
      text: "Skill check: Athletics DC 14",
    });

    await expect(
      sessionPage.page.getByText("Skill check: Athletics DC 14"),
    ).toBeVisible({ timeout: 10_000 });
  });
});
