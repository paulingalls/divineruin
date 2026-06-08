import { test, expect, beforeEach } from "bun:test";
import { handleGameEvent } from "@/audio/game-event-handler";
import { sessionStore } from "@/stores/session-store";
import { characterStore } from "@/stores/character-store";
import { resetStores } from "./use-game-events.helpers";

beforeEach(resetStores);

// --- handleGameEvent: session_init ---

test("session_init populates character and session stores", () => {
  handleGameEvent({
    type: "session_init",
    character: {
      player_id: "player-1",
      name: "Kael",
      level: 3,
      xp: 450,
      location_id: "accord_guild_hall",
      location_name: "Guild Hall",
      hp: { current: 25, max: 30 },
    },
    location: {
      id: "accord_guild_hall",
      name: "Guild Hall",
      atmosphere: "busy, purposeful",
      region: "Accord",
      tags: ["guild"],
      ambient_sounds: "guild_hall_bustle",
    },
    quests: [],
    inventory: [],
  });

  const char = characterStore.getState().character;
  expect(char).not.toBeNull();
  expect(char!.playerId).toBe("player-1");
  expect(char!.name).toBe("Kael");
  expect(char!.level).toBe(3);
  expect(char!.hpCurrent).toBe(25);
  expect(char!.hpMax).toBe(30);

  const loc = sessionStore.getState().locationContext;
  expect(loc).not.toBeNull();
  expect(loc!.locationId).toBe("accord_guild_hall");
  expect(loc!.locationName).toBe("Guild Hall");
  expect(loc!.atmosphere).toBe("busy, purposeful");
  expect(loc!.ambientSounds).toBe("guild_hall_bustle");
});

test("session_init with partial payload handles missing fields gracefully", () => {
  handleGameEvent({
    type: "session_init",
    character: { player_id: "p1", name: "Test" },
    location: null,
    quests: [],
    inventory: [],
  });

  const char = characterStore.getState().character;
  expect(char).not.toBeNull();
  expect(char!.name).toBe("Test");
  expect(char!.level).toBe(1);
  expect(char!.hpCurrent).toBe(0);

  expect(sessionStore.getState().locationContext).toBeNull();
});

test("session_init with null character does not crash", () => {
  expect(() =>
    handleGameEvent({
      type: "session_init",
      character: null,
      location: null,
      quests: [],
      inventory: [],
    }),
  ).not.toThrow();
  expect(characterStore.getState().character).toBeNull();
});

// --- handleGameEvent: session_end ---

test("session_end with summary populates sessionSummary and sets phase to summary", () => {
  sessionStore.getState().setPhase("active");
  handleGameEvent({
    type: "session_end",
    summary: "You explored the guild hall.",
    xp_earned: 50,
    items_found: ["rusty_sword"],
    quest_progress: ["guild_initiation"],
    duration: 300,
    next_hooks: ["Return to Torin."],
  });

  expect(sessionStore.getState().phase).toBe("summary");
  const s = sessionStore.getState().sessionSummary;
  expect(s).not.toBeNull();
  expect(s!.summary).toBe("You explored the guild hall.");
  expect(s!.xpEarned).toBe(50);
  expect(s!.itemsFound).toEqual(["rusty_sword"]);
  expect(s!.duration).toBe(300);
  expect(s!.nextHooks).toEqual(["Return to Torin."]);
});

test("session_end without summary sets phase to ended", () => {
  sessionStore.getState().setPhase("active");
  handleGameEvent({ type: "session_end" });
  expect(sessionStore.getState().phase).toBe("ended");
  expect(sessionStore.getState().sessionSummary).toBeNull();
});

// --- Milestone 10.4b: Story moments in session_end ---

test("session_end with story_moments populates storyMoments in summary", () => {
  sessionStore.getState().setPhase("active");
  handleGameEvent({
    type: "session_end",
    summary: "You fought bravely.",
    xp_earned: 100,
    items_found: [],
    quest_progress: [],
    duration: 600,
    next_hooks: [],
    story_moments: [
      {
        moment_key: "combat",
        description: "You struck down the hollow spider.",
        image_url: "/api/assets/images/img_combat",
      },
      {
        moment_key: "god_contact",
        description: "Veythar whispered.",
        image_url: "/api/assets/images/img_god",
      },
    ],
  });

  const s = sessionStore.getState().sessionSummary;
  expect(s).not.toBeNull();
  expect(s!.storyMoments).toHaveLength(2);
  expect(s!.storyMoments[0].momentKey).toBe("combat");
  expect(s!.storyMoments[0].imageUrl).toBe("/api/assets/images/img_combat");
  expect(s!.storyMoments[1].momentKey).toBe("god_contact");
});

test("session_end without story_moments has empty storyMoments array", () => {
  sessionStore.getState().setPhase("active");
  handleGameEvent({
    type: "session_end",
    summary: "A quiet session.",
    xp_earned: 0,
    items_found: [],
    quest_progress: [],
    duration: 300,
    next_hooks: [],
  });

  const s = sessionStore.getState().sessionSummary;
  expect(s).not.toBeNull();
  expect(s!.storyMoments).toEqual([]);
});
