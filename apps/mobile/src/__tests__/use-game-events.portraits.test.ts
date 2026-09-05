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

// --- Companion portrait keys on the voice tag the parser actually emits ---
//
// transcript_entry.character always carries the UPPERCASE voice tag: the value comes from
// dialogue_parser.TAG_PATTERN (`\[([A-Z_]+),\s*([a-z]+)\]:\s*"`) via base_agent's
// buffered_character and transcript._publish. Matching it against a display name ("Kael") was
// false for every player including Kael's — the companion portrait was dead code, not
// Kael-specific code. So the pin's input must be built in the emitted format or it goes green
// while production stays broken.

test("companion speech shows the portrait, keyed on the emitted voice tag", () => {
  portraitStore
    .getState()
    .setCompanionPortraits("/api/assets/images/p.png", "/api/assets/images/a.png");
  portraitStore.getState().setCompanionIdentity("Lira", "COMPANION_LIRA");

  handleGameEvent({
    type: "transcript_entry",
    speaker: "npc",
    character: "COMPANION_LIRA",
    text: "The road bends ahead.",
  });

  expect(portraitStore.getState().companionVisible).toBe(true);
});

test("a different companion's tag does not show this player's companion", () => {
  portraitStore
    .getState()
    .setCompanionPortraits("/api/assets/images/p.png", "/api/assets/images/a.png");
  portraitStore.getState().setCompanionIdentity("Lira", "COMPANION_LIRA");

  handleGameEvent({
    type: "transcript_entry",
    speaker: "npc",
    character: "COMPANION_KAEL",
    text: "Not your companion.",
  });

  expect(portraitStore.getState().companionVisible).toBe(false);
});

test("a display name does not show the companion — that was the dead gate", () => {
  portraitStore
    .getState()
    .setCompanionPortraits("/api/assets/images/p.png", "/api/assets/images/a.png");
  portraitStore.getState().setCompanionIdentity("Kael", "COMPANION_KAEL");

  handleGameEvent({
    type: "transcript_entry",
    speaker: "npc",
    character: "Kael",
    text: "A name the parser never emits.",
  });

  expect(portraitStore.getState().companionVisible).toBe(false);
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
