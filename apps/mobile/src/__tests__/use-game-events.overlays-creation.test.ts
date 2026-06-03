import { test, expect, beforeEach } from "bun:test";
import { handleGameEvent } from "@/audio/game-event-handler";
import { hudStore } from "@/stores/hud-store";
import { resetStores } from "./use-game-events.helpers";

beforeEach(resetStores);

// --- handleGameEvent: creation_cards ---

test("creation_cards sets cards in hudStore", () => {
  handleGameEvent({
    type: "creation_cards",
    cards: [
      { id: "c1", title: "Warrior", description: "Strong fighter", category: "class" },
      { id: "c2", title: "Mage", description: "Arcane power", category: "class" },
    ],
  });
  expect(hudStore.getState().creationCards).toHaveLength(2);
  expect(hudStore.getState().creationCards[0].title).toBe("Warrior");
});

// --- handleGameEvent: creation_card_selected ---

test("creation_card_selected sets selection in hudStore", () => {
  hudStore
    .getState()
    .setCreationCards([{ id: "c1", title: "Warrior", description: "Strong", category: "class" }]);
  handleGameEvent({ type: "creation_card_selected", card_id: "c1" });
  expect(hudStore.getState().selectedCreationCard).toBe("c1");
});

// --- Creation cards with image_url ---

test("creation_cards maps image_url to imageUrl", () => {
  handleGameEvent({
    type: "creation_cards",
    cards: [
      {
        id: "human",
        title: "Human",
        description: "Adaptable",
        category: "race",
        image_url: "/api/assets/images/img_abc123",
      },
      { id: "elari", title: "Elari", description: "Tall", category: "race" },
    ],
  });
  const cards = hudStore.getState().creationCards;
  expect(cards).toHaveLength(2);
  expect(cards[0]?.imageUrl).toMatch(/^https?:\/\/.+\/api\/assets\/images\/img_abc123$/);
  expect(cards[1]?.imageUrl).toBeUndefined();
});
