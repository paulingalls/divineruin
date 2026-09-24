import { API_ORIGIN } from "../ports.js";
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
    new RegExp(`^${API_ORIGIN}/api/assets/images/`),
  );
});

test("tagged companion transcript shows the assigned companion portrait", async ({
  sessionPage,
}) => {
  await sessionPage.injectSessionInit({
    companion: { name: "Lira", voice_id: "COMPANION_LIRA" },
    portraits: {
      companion: {
        primary: "/api/assets/images/companion_lira_primary",
        alert: "/api/assets/images/companion_lira_alert",
      },
      npcs: {},
    },
  });
  await sessionPage.injectEvent({
    type: "transcript_entry",
    speaker: "npc",
    character: "COMPANION_LIRA",
    text: "The road bends ahead.",
  });

  const overlay = sessionPage.page.getByTestId("companion-portrait-overlay");
  await expect(overlay).toBeVisible();
  await expect(overlay).toContainText("Lira");
  await expect(overlay.locator("img")).toHaveAttribute(
    "src",
    new RegExp(`^${API_ORIGIN}/api/assets/images/`),
  );
});

test("Sable companion cue shows her portrait without a transcript tag", async ({ sessionPage }) => {
  await sessionPage.injectSessionInit({
    companion: { name: "Sable", voice_id: "COMPANION_SABLE" },
    portraits: {
      companion: {
        primary: "/api/assets/images/companion_sable_primary",
        alert: "/api/assets/images/companion_sable_alert",
      },
      npcs: {},
    },
  });
  await sessionPage.injectEvent({
    type: "companion_cue",
    voice_id: "COMPANION_SABLE",
  });

  const overlay = sessionPage.page.getByTestId("companion-portrait-overlay");
  await expect(overlay).toBeVisible();
  await expect(overlay).toContainText("Sable");
  await expect(overlay.locator("img")).toHaveAttribute(
    "src",
    new RegExp(`^${API_ORIGIN}/api/assets/images/`),
  );
});
