import { test, expect, beforeEach } from "bun:test";
import { handleGameEventMessage } from "@/audio/game-event-handler";
import { authStore } from "@/stores/auth-store";
import { handleGameEvent } from "@/audio/game-event-handler";
import { panelStore } from "@/stores/panel-store";
import { sessionStore } from "@/stores/session-store";
import { characterStore } from "@/stores/character-store";
import { hudStore } from "@/stores/hud-store";
import favorEvents from "./fixtures/favor-neglect-event.json";
import { SAMPLE_CHARACTER, resetStores } from "./use-game-events.helpers";

beforeEach(resetStores);

test("neglect event updates the local favor bar and overlay, but not a teammate's", () => {
  characterStore.getState().setCharacter({
    ...SAMPLE_CHARACTER,
    playerId: favorEvents.primary.player_id,
  });
  characterStore.getState().updateDivineFavor(12, 100);
  handleGameEvent(favorEvents.primary);
  expect(characterStore.getState().divineFavorLevel).toBe(7);
  expect(characterStore.getState().divineFavorMax).toBe(100);
  expect(hudStore.getState().overlays).toHaveLength(1);
  expect(hudStore.getState().overlays[0].type).toBe("divine_favor");
  expect(hudStore.getState().overlays[0].payload.amount).toBe(-5);
  expect(hudStore.getState().overlays[0].payload.patronId).toBe("kaelen");

  hudStore.getState().dismissAllOverlays();
  handleGameEvent(favorEvents.joiner);
  expect(characterStore.getState().divineFavorLevel).toBe(7);
  expect(hudStore.getState().overlays).toHaveLength(0);
});

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

test("combat_started sets inCombat true and plays sfx", () => {
  handleGameEvent({ type: "combat_started" });
  expect(sessionStore.getState().inCombat).toBe(true);
});

test("combat_ended sets inCombat false", () => {
  sessionStore.getState().setCombat(true);
  handleGameEvent({ type: "combat_ended" });
  expect(sessionStore.getState().inCombat).toBe(false);
});

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

test("hollow_corruption_changed updates session store corruptionLevel", () => {
  handleGameEvent({ type: "hollow_corruption_changed", level: 2 });
  expect(sessionStore.getState().corruptionLevel).toBe(2);
});

test("hollow_corruption_changed only updates the local player's HUD", () => {
  characterStore.getState().setCharacter(SAMPLE_CHARACTER);
  sessionStore.getState().setCorruptionLevel(1);
  handleGameEvent({ type: "hollow_corruption_changed", player_id: "foreign-player", level: 3 });
  expect(sessionStore.getState().corruptionLevel).toBe(1);
  handleGameEvent({
    type: "hollow_corruption_changed",
    player_id: SAMPLE_CHARACTER.playerId,
    level: 2,
  });
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

test.each(["moderate", "hard"] as const)(
  "combat_started with %s sets combatDifficulty in store",
  (difficulty) => {
    sessionStore.setState({ combatDifficulty: difficulty === "moderate" ? "hard" : "moderate" });
    handleGameEvent({ type: "combat_started", difficulty });
    expect(sessionStore.getState().combatDifficulty).toBe(difficulty);
    expect(sessionStore.getState().inCombat).toBe(true);
  },
);

test("combat_started without difficulty keeps default", () => {
  handleGameEvent({ type: "combat_started" });
  expect(sessionStore.getState().combatDifficulty).toBe("moderate");
  expect(sessionStore.getState().inCombat).toBe(true);
});

test("divine_favor_changed updates character store", () => {
  handleGameEvent({
    type: "divine_favor_changed",
    new_level: 30,
    max: 100,
    amount: 5,
  });
  expect(characterStore.getState().divineFavorLevel).toBe(30);
  expect(characterStore.getState().divineFavorMax).toBe(100);
});

test("patron snapshots initialize and replace sheet favor and server ability states", () => {
  characterStore.getState().setCharacter(SAMPLE_CHARACTER);
  const abilities: import("@/audio/patron-abilities").PatronAbility[] = [
    {
      id: "gift",
      name: "Gift",
      tier: "Devoted",
      recharge: "long_rest",
      status: "active",
      eligible: true,
      available: true,
      spent: false,
      reason: null,
      state: "ready",
    },
  ];
  handleGameEvent({
    type: "session_init",
    patron_revision: 0,
    character: {
      player_id: SAMPLE_CHARACTER.playerId,
      divine_favor: { patron: "veythar", level: 40, max: 61 },
    },
    abilities,
  });
  expect(panelStore.getState().characterDetail?.abilities).toEqual(abilities);
  expect(panelStore.getState().characterDetail?.divineFavor?.max).toBe(61);
  const spent: import("@/audio/patron-abilities").PatronAbility[] = [
    { ...abilities[0], available: false, spent: true, reason: "Spent", state: "spent" },
  ];
  handleGameEvent({
    type: "patron_abilities_updated",
    patron_revision: 1,
    player_id: SAMPLE_CHARACTER.playerId,
    divine_favor: { patron: "veythar", level: 39, max: 61 },
    abilities: spent,
  });
  expect(panelStore.getState().characterDetail?.abilities).toEqual(spent);
  expect(panelStore.getState().characterDetail?.divineFavor?.level).toBe(39);
  const before = panelStore.getState().characterDetail;
  handleGameEvent({
    type: "patron_abilities_updated",
    patron_revision: 1,
    player_id: "someone_else",
    divine_favor: { patron: "veythar", level: 1, max: 61 },
    abilities: [],
  });
  expect(panelStore.getState().characterDetail).toBe(before);
});

test("encoded patron updates preserve server states and reject unknown recipients", () => {
  const pid = SAMPLE_CHARACTER.playerId;
  authStore.setState({ playerId: pid });
  const send = (event: unknown) =>
    handleGameEventMessage({
      payload: new TextEncoder().encode(JSON.stringify(event)),
      from: { isAgent: true },
    } as Parameters<typeof handleGameEventMessage>[0]);
  const favor = { patron: "veythar", level: 40, max: 61 };
  const row = {
    id: "gift",
    name: "Gift",
    tier: "Devoted",
    recharge: "long_rest",
    status: "active",
    eligible: true,
    available: true,
    spent: false,
    reason: null,
    state: "ready",
  };
  send({
    type: "session_init",
    patron_revision: 0,
    character: { player_id: pid, divine_favor: favor },
    abilities: [row],
  });
  let revision = 0;
  for (const state of ["spent", "ready", "locked", "ready"]) {
    const next = {
      ...row,
      state,
      spent: state === "spent" || state === "locked",
      available: state === "ready",
      reason: state === "ready" ? null : "Blocked",
    };
    send({
      type: "patron_abilities_updated",
      patron_revision: ++revision,
      player_id: pid,
      divine_favor: { ...favor, level: state === "locked" ? 20 : 40 },
      abilities: [next],
    });
    expect(panelStore.getState().characterDetail?.abilities as unknown).toEqual([next]);
    expect(panelStore.getState().characterDetail?.divineFavor?.level).toBe(
      state === "locked" ? 20 : 40,
    );
  }
  const before = panelStore.getState().characterDetail;
  send({
    type: "session_init",
    patron_revision: 0,
    character: { player_id: "foreign", divine_favor: favor },
    abilities: [],
  });
  expect(panelStore.getState().characterDetail).toBe(before);
  characterStore.setState({ character: null });
  authStore.setState({ playerId: null });
  send({ type: "patron_abilities_updated", player_id: pid, divine_favor: favor, abilities: [] });
  expect(panelStore.getState().characterDetail).toBe(before);
  authStore.setState({ playerId: pid });
  send({
    type: "session_init",
    patron_revision: 10,
    character: { player_id: pid, divine_favor: { patron: "none", level: 0, max: 61 } },
    abilities: [],
  });
  expect(panelStore.getState().characterDetail?.abilities).toEqual([]);
});
