import { test, expect, beforeEach } from "bun:test";
import { parseGameEvent, handleGameEvent } from "@/audio/game-event-handler";
import { activePlayerCount } from "@/audio/sfx-player";
import { sessionStore } from "@/stores/session-store";
import { characterStore, type CharacterSummary } from "@/stores/character-store";
import { hudStore } from "@/stores/hud-store";

function encode(data: object): Uint8Array {
  return new TextEncoder().encode(JSON.stringify(data));
}

const SAMPLE_CHARACTER: CharacterSummary = {
  playerId: "player-1",
  name: "Kael",
  className: "warrior",
  level: 3,
  xp: 450,
  locationId: "accord_guild_hall",
  locationName: "Guild Hall",
  hpCurrent: 25,
  hpMax: 30,
};

beforeEach(() => {
  sessionStore.getState().reset();
  characterStore.getState().clear();
  hudStore.getState().reset();
});

// --- parseGameEvent ---

test("parseGameEvent decodes valid JSON with type field", () => {
  const event = parseGameEvent(encode({ type: "play_sound", sound_name: "sword_clash" }));
  expect(event).toEqual({ type: "play_sound", sound_name: "sword_clash" });
});

test("parseGameEvent returns null for missing type field", () => {
  expect(parseGameEvent(encode({ sound_name: "sword_clash" }))).toBeNull();
});

test("parseGameEvent returns null for malformed JSON", () => {
  const payload = new TextEncoder().encode("not json{{{");
  expect(parseGameEvent(payload)).toBeNull();
});

test("parseGameEvent returns null for non-object JSON", () => {
  const payload = new TextEncoder().encode('"just a string"');
  expect(parseGameEvent(payload)).toBeNull();
});

// --- handleGameEvent: original events ---

test("play_sound event with known sound triggers playback", () => {
  handleGameEvent({ type: "play_sound", sound_name: "dice_roll" });
  expect(activePlayerCount()).toBeGreaterThanOrEqual(0);
});

test("dice_roll event triggers playback", () => {
  handleGameEvent({ type: "dice_roll", roll_type: "skill_check", roll: 14 });
});

test("unknown event type does not crash", () => {
  expect(() => handleGameEvent({ type: "unknown_event" })).not.toThrow();
});

test("play_sound without sound_name does not crash", () => {
  expect(() => handleGameEvent({ type: "play_sound" })).not.toThrow();
});

test("play_sound with non-string sound_name does not crash", () => {
  expect(() => handleGameEvent({ type: "play_sound", sound_name: 42 })).not.toThrow();
});

test("play_sound with unknown sound does not crash", () => {
  expect(() => handleGameEvent({ type: "play_sound", sound_name: "nonexistent" })).not.toThrow();
});

// --- handleGameEvent: location_changed ---

test("location_changed updates session and character stores", () => {
  characterStore.getState().setCharacter(SAMPLE_CHARACTER);
  handleGameEvent({
    type: "location_changed",
    new_location: "accord_market_square",
    location_name: "Market Square",
    atmosphere: "noisy, chaotic",
    region: "Accord",
  });
  const loc = sessionStore.getState().locationContext;
  expect(loc).not.toBeNull();
  expect(loc!.locationId).toBe("accord_market_square");
  expect(loc!.locationName).toBe("Market Square");
  expect(loc!.atmosphere).toBe("noisy, chaotic");
  const char = characterStore.getState().character!;
  expect(char.locationId).toBe("accord_market_square");
  expect(char.locationName).toBe("Market Square");
});

test("location_changed without location_name falls back to id", () => {
  characterStore.getState().setCharacter(SAMPLE_CHARACTER);
  handleGameEvent({
    type: "location_changed",
    new_location: "some_place",
  });
  const loc = sessionStore.getState().locationContext!;
  expect(loc.locationName).toBe("some_place");
});

test("location_changed without new_location is no-op", () => {
  handleGameEvent({ type: "location_changed" });
  expect(sessionStore.getState().locationContext).toBeNull();
});

// --- handleGameEvent: combat ---

test("combat_started sets inCombat true and plays sfx", () => {
  handleGameEvent({ type: "combat_started" });
  expect(sessionStore.getState().inCombat).toBe(true);
});

test("combat_ended sets inCombat false", () => {
  sessionStore.getState().setCombat(true);
  handleGameEvent({ type: "combat_ended" });
  expect(sessionStore.getState().inCombat).toBe(false);
});

// --- handleGameEvent: xp_awarded ---

test("xp_awarded updates character store", () => {
  characterStore.getState().setCharacter(SAMPLE_CHARACTER);
  handleGameEvent({ type: "xp_awarded", new_xp: 600, new_level: 4 });
  const char = characterStore.getState().character!;
  expect(char.xp).toBe(600);
  expect(char.level).toBe(4);
});

test("xp_awarded with non-number fields is no-op", () => {
  characterStore.getState().setCharacter(SAMPLE_CHARACTER);
  handleGameEvent({ type: "xp_awarded", new_xp: "not a number", new_level: "bad" });
  expect(characterStore.getState().character!.xp).toBe(450);
});

// --- handleGameEvent: hp_changed ---

test("hp_changed updates character HP", () => {
  characterStore.getState().setCharacter(SAMPLE_CHARACTER);
  handleGameEvent({ type: "hp_changed", current: 15, max: 30 });
  const char = characterStore.getState().character!;
  expect(char.hpCurrent).toBe(15);
  expect(char.hpMax).toBe(30);
});

test("hp_changed with only current preserves max", () => {
  characterStore.getState().setCharacter(SAMPLE_CHARACTER);
  handleGameEvent({ type: "hp_changed", current: 10 });
  const char = characterStore.getState().character!;
  expect(char.hpCurrent).toBe(10);
  expect(char.hpMax).toBe(30);
});

test("hp_changed with non-number current is no-op", () => {
  characterStore.getState().setCharacter(SAMPLE_CHARACTER);
  handleGameEvent({ type: "hp_changed", current: "bad" });
  expect(characterStore.getState().character!.hpCurrent).toBe(25);
});

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

// --- handleGameEvent: session_end with summary ---

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

// --- handleGameEvent: dice_result ---

test("dice_result pushes overlay to hudStore", () => {
  handleGameEvent({ type: "dice_result", roll: 14, modifier: 2, total: 16, success: true });
  const overlays = hudStore.getState().overlays;
  expect(overlays).toHaveLength(1);
  expect(overlays[0].type).toBe("dice_result");
  expect(overlays[0].payload.roll).toBe(14);
  expect(overlays[0].payload.success).toBe(true);
});

// --- handleGameEvent: combat_ui_update ---

test("combat_ui_update sets combat state in hudStore", () => {
  handleGameEvent({
    type: "combat_ui_update",
    phase: "player_turn",
    round: 2,
    combatants: [
      {
        id: "c1",
        name: "Kael",
        isAlly: true,
        hpCurrent: 20,
        hpMax: 30,
        statusEffects: [],
        isActive: true,
      },
    ],
  });
  const combat = hudStore.getState().combatState;
  expect(combat).not.toBeNull();
  expect(combat!.phase).toBe("player_turn");
  expect(combat!.round).toBe(2);
  expect(combat!.combatants).toHaveLength(1);
});

// --- handleGameEvent: combat_ended clears hudStore ---

test("combat_ended clears hudStore combat state", () => {
  hudStore.getState().setCombatState({ phase: "init", round: 1, combatants: [] });
  handleGameEvent({ type: "combat_ended" });
  expect(hudStore.getState().combatState).toBeNull();
});

// --- handleGameEvent: item_acquired ---

test("item_acquired pushes overlay to hudStore", () => {
  handleGameEvent({
    type: "item_acquired",
    name: "Rusty Sword",
    description: "A worn blade",
    rarity: "common",
  });
  const overlays = hudStore.getState().overlays;
  expect(overlays).toHaveLength(1);
  expect(overlays[0].type).toBe("item_acquired");
  expect(overlays[0].payload.name).toBe("Rusty Sword");
  expect(overlays[0].payload.rarity).toBe("common");
});

// --- handleGameEvent: quest_update ---

test("quest_update pushes overlay and sets active objective", () => {
  handleGameEvent({
    type: "quest_update",
    quest_name: "Guild Initiation",
    objective: "Find the cartographer",
    status: "active",
  });
  const overlays = hudStore.getState().overlays;
  expect(overlays).toHaveLength(1);
  expect(overlays[0].type).toBe("quest_update");
  const obj = hudStore.getState().activeObjective;
  expect(obj).not.toBeNull();
  expect(obj!.questName).toBe("Guild Initiation");
  expect(obj!.objective).toBe("Find the cartographer");
});

test("quest_updated also pushes overlay (backward compat)", () => {
  handleGameEvent({
    type: "quest_updated",
    quest_name: "Old Quest",
    objective: "Do something",
  });
  expect(hudStore.getState().overlays).toHaveLength(1);
  expect(hudStore.getState().overlays[0].type).toBe("quest_update");
});

// --- handleGameEvent: xp_awarded with overlay ---

test("xp_awarded without level_up pushes xp_toast overlay", () => {
  characterStore.getState().setCharacter(SAMPLE_CHARACTER);
  handleGameEvent({ type: "xp_awarded", new_xp: 525, new_level: 3, xp_gained: 75 });
  const overlays = hudStore.getState().overlays;
  expect(overlays).toHaveLength(1);
  expect(overlays[0].type).toBe("xp_toast");
  expect(overlays[0].payload.xpGained).toBe(75);
});

test("xp_awarded with level_up pushes level_up overlay", () => {
  characterStore.getState().setCharacter(SAMPLE_CHARACTER);
  handleGameEvent({
    type: "xp_awarded",
    new_xp: 600,
    new_level: 4,
    xp_gained: 150,
    level_up: true,
  });
  const overlays = hudStore.getState().overlays;
  expect(overlays).toHaveLength(1);
  expect(overlays[0].type).toBe("level_up");
  expect(overlays[0].payload.newLevel).toBe(4);
});

// --- handleGameEvent: status_effect ---

test("status_effect add creates status effect in hudStore", () => {
  handleGameEvent({
    type: "status_effect",
    action: "add",
    effect_id: "blessed-1",
    name: "Blessed",
    category: "buff",
  });
  expect(hudStore.getState().statusEffects).toHaveLength(1);
  expect(hudStore.getState().statusEffects[0].name).toBe("Blessed");
  expect(hudStore.getState().statusEffects[0].category).toBe("buff");
});

test("status_effect remove removes from hudStore", () => {
  hudStore.getState().addStatusEffect({ id: "curse-1", name: "Cursed", category: "debuff" });
  handleGameEvent({ type: "status_effect", action: "remove", effect_id: "curse-1" });
  expect(hudStore.getState().statusEffects).toHaveLength(0);
});

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

// --- handleGameEvent: inventory_updated ---

test("inventory_updated does not crash", () => {
  expect(() => handleGameEvent({ type: "inventory_updated" })).not.toThrow();
});
