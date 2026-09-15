import { test, expect } from "../fixtures/session.js";

test("tagged NPC transcript shows the authored portrait with an absolute image URL", async ({
  sessionPage,
}) => {
  await sessionPage.injectSessionInit({
    portraits: {
      companion: null,
      npcs: {
        GUILDMASTER_TORIN: {
          name: "Guildmaster Torin",
          url: "/api/assets/images/npc_torin",
        },
      },
    },
  });
  await sessionPage.injectEvent({
    type: "transcript_entry",
    speaker: "npc",
    character: "GUILDMASTER_TORIN",
    text: "Welcome, traveler.",
  });

  const overlay = sessionPage.page.getByTestId("npc-portrait-overlay");
  await expect(overlay).toBeVisible();
  await expect(overlay).toContainText("Guildmaster Torin");
  await expect(overlay.locator("img")).toHaveAttribute(
    "src",
    /^http:\/\/localhost:3001\/api\/assets\/images\//,
  );
});
