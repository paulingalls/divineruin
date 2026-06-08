import { test, expect, beforeEach } from "bun:test";
import { handleGameEvent } from "@/audio/game-event-handler";
import { characterStore } from "@/stores/character-store";
import { portraitStore } from "@/stores/portrait-store";
import { SAMPLE_CHARACTER, resetStores } from "./use-game-events.helpers";

beforeEach(resetStores);

// --- Portrait store integration ---

test("session_init populates portrait store from portraits field", () => {
  handleGameEvent({
    type: "session_init",
    character: {
      player_id: "p1",
      name: "Test",
      class: "warrior",
      level: 1,
      xp: 0,
      location_id: "loc1",
      hp: { current: 10, max: 10 },
      portrait_url: "/api/assets/images/img_player",
    },
    location: { id: "loc1", name: "Town" },
    portraits: {
      companion: { primary: "/api/assets/images/img_comp1", alert: "/api/assets/images/img_comp2" },
      npcs: { "Guildmaster Torin": "/api/assets/images/img_torin" },
    },
  });

  const ps = portraitStore.getState();
  expect(ps.companionPrimaryUrl).toBe("/api/assets/images/img_comp1");
  expect(ps.companionAlertUrl).toBe("/api/assets/images/img_comp2");
  expect(ps.npcPortraitMap["Guildmaster Torin"]).toBe("/api/assets/images/img_torin");

  // Player portrait should also be set
  const cs = characterStore.getState();
  expect(cs.character?.portraitUrl).toBe("/api/assets/images/img_player");
});

// --- Transcript entry triggers NPC portrait ---

test("transcript_entry with npc speaker shows portrait", () => {
  portraitStore
    .getState()
    .setNpcPortraitMap({ "Guildmaster Torin": "/api/assets/images/img_torin" });

  handleGameEvent({
    type: "transcript_entry",
    speaker: "npc",
    character: "Guildmaster Torin",
    text: "Welcome, traveler.",
  });

  expect(portraitStore.getState().activeNpc).toEqual({
    name: "Guildmaster Torin",
    url: "/api/assets/images/img_torin",
  });
});

test("transcript_entry with dm speaker clears NPC portrait", () => {
  portraitStore.getState().setActiveNpc("Torin", "/api/assets/images/img_torin");

  handleGameEvent({
    type: "transcript_entry",
    speaker: "dm",
    text: "The guildmaster nods.",
  });

  expect(portraitStore.getState().activeNpc).toBeNull();
});

// --- Player portrait ready event ---

test("player_portrait_ready updates character store", () => {
  characterStore.getState().setCharacter({ ...SAMPLE_CHARACTER });

  handleGameEvent({
    type: "player_portrait_ready",
    url: "/api/assets/images/img_abc123",
  });

  expect(characterStore.getState().character?.portraitUrl).toBe("/api/assets/images/img_abc123");
  expect(portraitStore.getState().playerPortraitUrl).toBe("/api/assets/images/img_abc123");
});

test("player_portrait_ready rejects URLs without /api/assets/ prefix", () => {
  characterStore.getState().setCharacter({ ...SAMPLE_CHARACTER });

  handleGameEvent({
    type: "player_portrait_ready",
    url: "https://evil.com/image.png",
  });

  expect(characterStore.getState().character?.portraitUrl).toBeNull();
});

test("player_portrait_ready rejects URLs with path traversal", () => {
  characterStore.getState().setCharacter({ ...SAMPLE_CHARACTER });

  handleGameEvent({
    type: "player_portrait_ready",
    url: "/api/assets/../../../etc/passwd",
  });

  expect(characterStore.getState().character?.portraitUrl).toBeNull();
});
