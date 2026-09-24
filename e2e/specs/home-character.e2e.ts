import { chatterPool } from "../../apps/server/src/companion_chatter.js";
import { test, expect } from "../fixtures/character.js";

// The fixture's class is an archetype companion_sable complements. A failed companion resolution
// drops the idle line without an error the page can show, so only a line from Sable's own pool
// proves the feed resolved the player's companion.
const escapeRegExp = (line: string) => line.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const SABLE_IDLE_LINE = new RegExp(chatterPool("companion_sable").map(escapeRegExp).join("|"));

test.describe("Home screen with character", () => {
  test("shows character summary and enter button", async ({ characterPage, testCharacter }) => {
    // Character name visible
    await expect(characterPage.getByText(testCharacter.name)).toBeVisible();

    // ENTER AETHOS button (not AWAKEN — character exists)
    await expect(characterPage.getByText("ENTER AETHOS", { exact: true })).toBeVisible();

    // Settings gear visible
    await expect(characterPage.getByText("\u2699")).toBeVisible();
  });

  test("shows the player's own companion idle chatter when no activities", async ({
    characterPage,
  }) => {
    await expect(characterPage.getByText(SABLE_IDLE_LINE)).toBeVisible();
  });
});
