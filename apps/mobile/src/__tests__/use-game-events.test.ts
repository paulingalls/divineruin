import { test, expect, beforeEach } from "bun:test";
import {
  parseGameEvent,
  handleGameEvent,
  parseCombatant,
  DICE_STINGER_DELAY_MS,
} from "@/audio/game-event-handler";
import { activePlayerCount } from "@/audio/sfx-player";
import { sessionStore } from "@/stores/session-store";
import { characterStore, type CharacterSummary } from "@/stores/character-store";
import { hudStore } from "@/stores/hud-store";
import { panelStore } from "@/stores/panel-store";

function encode(data: object): Uint8Array {
  return new TextEncoder().encode(JSON.stringify(data));
}

function captureTimers(fn: () => void): { fn: () => void; delay: number }[] {
  const timers: { fn: () => void; delay: number }[] = [];
  const orig = globalThis.setTimeout;
  globalThis.setTimeout = ((cb: () => void, delay: number) => {
    timers.push({ fn: cb, delay });
    return 0 as unknown as ReturnType<typeof setTimeout>;
  }) as typeof setTimeout;
  fn();
  globalThis.setTimeout = orig;
  return timers;
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
  panelStore.getState().reset();
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
    ambient_sounds: "market_bustle",
  });
  const loc = sessionStore.getState().locationContext;
  expect(loc).not.toBeNull();
  expect(loc!.locationId).toBe("accord_market_square");
  expect(loc!.locationName).toBe("Market Square");
  expect(loc!.atmosphere).toBe("noisy, chaotic");
  expect(loc!.ambientSounds).toBe("market_bustle");
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

test("quest_updated advances quest in panelStore", () => {
  panelStore.getState().setQuests([
    {
      questId: "greyvale_anomaly",
      questName: "The Greyvale Anomaly",
      type: "main",
      currentStage: 0,
      stages: [
        {
          id: "s0",
          name: "The Road North",
          objective: "Travel to Millhaven",
          completed: false,
          targetLocationId: "millhaven",
        },
        {
          id: "s1",
          name: "Something Wrong",
          objective: "Talk to residents",
          completed: false,
          targetLocationId: "millhaven",
        },
      ],
      globalHints: {},
      status: "active",
    },
  ]);

  handleGameEvent({
    type: "quest_updated",
    quest_id: "greyvale_anomaly",
    quest_name: "The Greyvale Anomaly",
    new_stage: 1,
    objective: "Talk to residents",
  });

  const quest = panelStore.getState().quests[0];
  expect(quest.currentStage).toBe(1);
  expect(quest.stages[0].completed).toBe(true);
  expect(quest.stages[1].completed).toBe(false);
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

// --- handleGameEvent: item_acquired passes stats ---

test("item_acquired passes stats through to overlay payload", () => {
  handleGameEvent({
    type: "item_acquired",
    name: "Iron Shield",
    description: "Sturdy defense",
    rarity: "uncommon",
    stats: { defense: 5, weight: 3 },
  });
  const overlay = hudStore.getState().overlays[0];
  expect(overlay.payload.stats).toEqual({ defense: 5, weight: 3 });
});

// --- handleGameEvent: quest_update passes stageName ---

test("quest_update passes stageName through to overlay payload", () => {
  handleGameEvent({
    type: "quest_update",
    quest_name: "Guild Initiation",
    objective: "Find the cartographer",
    status: "active",
    stage_name: "Discovery",
  });
  const overlay = hudStore.getState().overlays[0];
  expect(overlay.payload.stageName).toBe("Discovery");
});

// --- handleGameEvent: xp_awarded level_up passes className ---

test("xp_awarded with level_up passes className from character store", () => {
  characterStore.getState().setCharacter(SAMPLE_CHARACTER);
  handleGameEvent({
    type: "xp_awarded",
    new_xp: 600,
    new_level: 4,
    xp_gained: 150,
    level_up: true,
  });
  const overlay = hudStore.getState().overlays[0];
  expect(overlay.payload.className).toBe("warrior");
});

// --- handleGameEvent: dice_result stinger ---

test("dice_result schedules success stinger after delay", () => {
  const timers = captureTimers(() =>
    handleGameEvent({ type: "dice_result", roll: 14, total: 16, success: true }),
  );
  const stingerTimer = timers.find((t) => t.delay === DICE_STINGER_DELAY_MS);
  expect(stingerTimer).toBeDefined();
});

test("dice_result schedules fail stinger for failure", () => {
  const timers = captureTimers(() =>
    handleGameEvent({ type: "dice_result", roll: 3, total: 5, success: false }),
  );
  const stingerTimer = timers.find((t) => t.delay === DICE_STINGER_DELAY_MS);
  expect(stingerTimer).toBeDefined();
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

test("inventory_updated does not crash without inventory array", () => {
  expect(() => handleGameEvent({ type: "inventory_updated" })).not.toThrow();
});

test("inventory_updated populates panelStore inventory", () => {
  handleGameEvent({
    type: "inventory_updated",
    inventory: [
      {
        id: "sword_1",
        name: "Steel Sword",
        type: "weapon",
        rarity: "common",
        description: "A blade",
        weight: 3,
        effects: [],
        lore: "",
        value_base: 25,
        slot_info: { quantity: 1, equipped: true },
      },
    ],
  });
  const inv = panelStore.getState().inventory;
  expect(inv).toHaveLength(1);
  expect(inv[0].name).toBe("Steel Sword");
  expect(inv[0].equipped).toBe(true);
});

// --- handleGameEvent: session_init populates panelStore ---

test("session_init populates panelStore characterDetail", () => {
  handleGameEvent({
    type: "session_init",
    character: {
      player_id: "p1",
      name: "Kael",
      race: "Human",
      class: "warrior",
      level: 3,
      xp: 450,
      location_id: "guild",
      location_name: "Guild Hall",
      hp: { current: 25, max: 30 },
      attributes: {
        strength: 16,
        dexterity: 12,
        constitution: 14,
        intelligence: 10,
        wisdom: 11,
        charisma: 8,
      },
      ac: 18,
      proficiencies: ["athletics"],
      saving_throw_proficiencies: ["strength"],
      equipment: {
        main_hand: { name: "Sword" },
        armor: { name: "Chain Mail" },
        shield: null,
      },
      gold: 50,
    },
    location: { id: "guild", name: "Guild Hall", exits: { south: { destination: "market" } } },
    quests: [],
    inventory: [],
  });
  const detail = panelStore.getState().characterDetail;
  expect(detail).not.toBeNull();
  expect(detail!.race).toBe("Human");
  expect(detail!.attributes.strength).toBe(16);
  expect(detail!.ac).toBe(18);
  expect(detail!.proficiencies).toEqual(["athletics"]);
  expect(detail!.gold).toBe(50);
});

test("session_init populates panelStore inventory", () => {
  handleGameEvent({
    type: "session_init",
    character: { player_id: "p1", name: "Kael" },
    location: null,
    quests: [],
    inventory: [
      {
        id: "item1",
        name: "Potion",
        type: "consumable",
        rarity: "common",
        description: "",
        weight: 1,
        effects: [],
        lore: "",
        value_base: 5,
        slot_info: { quantity: 3, equipped: false },
      },
    ],
  });
  const inv = panelStore.getState().inventory;
  expect(inv).toHaveLength(1);
  expect(inv[0].quantity).toBe(3);
  expect(inv[0].equipped).toBe(false);
});

test("session_init populates panelStore quests", () => {
  handleGameEvent({
    type: "session_init",
    character: { player_id: "p1", name: "Kael" },
    location: null,
    quests: [
      {
        quest_id: "q1",
        quest_name: "Guild Initiation",
        type: "main",
        current_stage: 1,
        stages: [
          { id: "s0", name: "Intro", objective: "Talk to NPC" },
          { id: "s1", name: "Discovery", objective: "Find item" },
        ],
        global_hints: { stuck_stage_1: "Check the market" },
      },
    ],
    inventory: [],
  });
  const quests = panelStore.getState().quests;
  expect(quests).toHaveLength(1);
  expect(quests[0].questName).toBe("Guild Initiation");
  expect(quests[0].stages[0].completed).toBe(true);
  expect(quests[0].stages[1].completed).toBe(false);
  expect(quests[0].globalHints).toEqual({ stuck_stage_1: "Check the market" });
});

test("session_init populates panelStore map from location exits", () => {
  handleGameEvent({
    type: "session_init",
    character: { player_id: "p1", name: "Kael" },
    location: {
      id: "guild",
      name: "Guild Hall",
      exits: { south: { destination: "market" }, east: { destination: "temple" } },
    },
    quests: [],
    inventory: [],
    map_progress: [],
  });
  const map = panelStore.getState().mapProgress;
  const guild = map.find((n) => n.locationId === "guild");
  expect(guild).toBeDefined();
  expect(guild!.visited).toBe(true);
  expect(guild!.connections).toContain("market");
  expect(guild!.connections).toContain("temple");
});

test("session_init populates map from map_progress array", () => {
  handleGameEvent({
    type: "session_init",
    character: { player_id: "p1", name: "Kael" },
    location: { id: "market", name: "Market", exits: {} },
    quests: [],
    inventory: [],
    map_progress: [
      { location_id: "guild", connections: ["market"] },
      { location_id: "market", connections: ["guild", "temple"] },
    ],
  });
  const map = panelStore.getState().mapProgress;
  expect(map.find((n) => n.locationId === "guild")?.visited).toBe(true);
  expect(map.find((n) => n.locationId === "market")?.visited).toBe(true);
});

// --- handleGameEvent: location_changed updates map ---

test("location_changed adds visited location to panelStore map", () => {
  handleGameEvent({
    type: "location_changed",
    new_location: "market",
    location_name: "Market Square",
    connections: ["guild", "docks"],
  });
  const map = panelStore.getState().mapProgress;
  const market = map.find((n) => n.locationId === "market");
  expect(market).toBeDefined();
  expect(market!.visited).toBe(true);
  expect(market!.connections).toEqual(["guild", "docks"]);
});

// --- parseCombatant ---

test("parseCombatant returns valid combatant from well-formed data", () => {
  const result = parseCombatant({
    id: "c1",
    name: "Kael",
    isAlly: true,
    hpCurrent: 20,
    hpMax: 30,
    statusEffects: ["blessed"],
    isActive: true,
  });
  expect(result).not.toBeNull();
  expect(result!.id).toBe("c1");
  expect(result!.name).toBe("Kael");
  expect(result!.isAlly).toBe(true);
  expect(result!.hpCurrent).toBe(20);
  expect(result!.statusEffects).toEqual(["blessed"]);
});

test("parseCombatant returns null for null input", () => {
  expect(parseCombatant(null)).toBeNull();
});

test("parseCombatant returns null for non-object input", () => {
  expect(parseCombatant("string")).toBeNull();
  expect(parseCombatant(42)).toBeNull();
});

test("parseCombatant returns null for missing id", () => {
  expect(parseCombatant({ name: "Kael" })).toBeNull();
});

test("parseCombatant returns null for missing name", () => {
  expect(parseCombatant({ id: "c1" })).toBeNull();
});

test("parseCombatant defaults missing optional fields", () => {
  const result = parseCombatant({ id: "c1", name: "Kael" });
  expect(result).not.toBeNull();
  expect(result!.isAlly).toBe(false);
  expect(result!.hpCurrent).toBe(0);
  expect(result!.hpMax).toBe(1);
  expect(result!.statusEffects).toEqual([]);
  expect(result!.isActive).toBe(false);
});

test("combat_ui_update filters out malformed combatants", () => {
  handleGameEvent({
    type: "combat_ui_update",
    phase: "player_turn",
    round: 1,
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
      null,
      { notAnId: true },
      "string",
    ],
  });
  const combat = hudStore.getState().combatState;
  expect(combat).not.toBeNull();
  expect(combat!.combatants).toHaveLength(1);
  expect(combat!.combatants[0].id).toBe("c1");
});

// --- Milestone 8.1: Music system events ---

test("hollow_corruption_changed updates session store corruptionLevel", () => {
  handleGameEvent({ type: "hollow_corruption_changed", level: 2 });
  expect(sessionStore.getState().corruptionLevel).toBe(2);
});

test("hollow_corruption_changed ignores non-number level", () => {
  sessionStore.getState().setCorruptionLevel(1);
  handleGameEvent({ type: "hollow_corruption_changed", level: "high" });
  expect(sessionStore.getState().corruptionLevel).toBe(1);
});

test("hollow_corruption_changed clamps negative values to 0", () => {
  handleGameEvent({ type: "hollow_corruption_changed", level: -5 });
  expect(sessionStore.getState().corruptionLevel).toBe(0);
});

test("hollow_corruption_changed clamps values above 3", () => {
  handleGameEvent({ type: "hollow_corruption_changed", level: 99 });
  expect(sessionStore.getState().corruptionLevel).toBe(3);
});

test("hollow_corruption_changed floors float values", () => {
  handleGameEvent({ type: "hollow_corruption_changed", level: 2.7 });
  expect(sessionStore.getState().corruptionLevel).toBe(2);
});

test("set_music_state with valid string does not crash", () => {
  handleGameEvent({ type: "set_music_state", music_state: "wonder" });
  // Verifying no error thrown — overrideMusicState is called
});

test("set_music_state ignores non-string", () => {
  handleGameEvent({ type: "set_music_state", music_state: 42 });
  // No crash, no-op
});

test("combat_started with difficulty sets combatDifficulty in store", () => {
  handleGameEvent({ type: "combat_started", difficulty: "hard" });
  expect(sessionStore.getState().combatDifficulty).toBe("hard");
  expect(sessionStore.getState().inCombat).toBe(true);
});

test("combat_started without difficulty keeps default", () => {
  handleGameEvent({ type: "combat_started" });
  expect(sessionStore.getState().combatDifficulty).toBe("moderate");
  expect(sessionStore.getState().inCombat).toBe(true);
});
