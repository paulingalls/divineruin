import { test, expect, beforeEach } from "bun:test";
import { characterStore, type CharacterSummary } from "@/stores/character-store";

const SAMPLE: CharacterSummary = {
  playerId: "player-1",
  name: "Kael",
  race: "human",
  className: "warrior",
  level: 3,
  xp: 450,
  locationId: "accord_guild_hall",
  locationName: "Guild Hall",
  hpCurrent: 25,
  hpMax: 30,
  deity: "",
};

beforeEach(() => {
  characterStore.getState().clear();
});

test("initial state is null", () => {
  expect(characterStore.getState().character).toBeNull();
});

test("setCharacter populates character", () => {
  characterStore.getState().setCharacter(SAMPLE);
  expect(characterStore.getState().character).toEqual(SAMPLE);
});

test("updateLocation updates locationId and locationName", () => {
  characterStore.getState().setCharacter(SAMPLE);
  characterStore.getState().updateLocation("accord_market_square", "Market Square");
  const c = characterStore.getState().character!;
  expect(c.locationId).toBe("accord_market_square");
  expect(c.locationName).toBe("Market Square");
});

test("updateLocation is no-op when character is null", () => {
  characterStore.getState().updateLocation("somewhere", "Somewhere");
  expect(characterStore.getState().character).toBeNull();
});

test("updateHp updates current HP", () => {
  characterStore.getState().setCharacter(SAMPLE);
  characterStore.getState().updateHp(10);
  expect(characterStore.getState().character!.hpCurrent).toBe(10);
  expect(characterStore.getState().character!.hpMax).toBe(30);
});

test("updateHp updates both current and max", () => {
  characterStore.getState().setCharacter(SAMPLE);
  characterStore.getState().updateHp(20, 35);
  const c = characterStore.getState().character!;
  expect(c.hpCurrent).toBe(20);
  expect(c.hpMax).toBe(35);
});

test("updateHp is no-op when character is null", () => {
  characterStore.getState().updateHp(10);
  expect(characterStore.getState().character).toBeNull();
});

test("updateXp updates xp and level", () => {
  characterStore.getState().setCharacter(SAMPLE);
  characterStore.getState().updateXp(600, 4);
  const c = characterStore.getState().character!;
  expect(c.xp).toBe(600);
  expect(c.level).toBe(4);
});

test("updateXp is no-op when character is null", () => {
  characterStore.getState().updateXp(100, 2);
  expect(characterStore.getState().character).toBeNull();
});

test("clear resets character to null", () => {
  characterStore.getState().setCharacter(SAMPLE);
  characterStore.getState().clear();
  expect(characterStore.getState().character).toBeNull();
});
