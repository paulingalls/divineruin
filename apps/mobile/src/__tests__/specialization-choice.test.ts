import { test, expect, beforeEach } from "bun:test";

import { handleGameEvent } from "@/audio/game-event-handler";
import { sendSpecializationChoice } from "@/audio/specialization-hint";
import { characterStore, type CharacterSummary } from "@/stores/character-store";
import { hudStore } from "@/stores/hud-store";

// M2.3 story-005: the mobile glanceable supplement for the L5 specialization fork.
// The handler dispatches the agent's SPECIALIZATION_CHOICE event into hudStore's
// dedicated specializationChoice field (rendered as an interactive OverlayManager
// branch, like the creation-card row — NOT a tap-to-dismiss pushOverlay). Tapping a
// path publishes a player_hints data-channel hint via sendSpecializationChoice.

const SAMPLE_CHARACTER: CharacterSummary = {
  playerId: "player-1",
  name: "Kael",
  race: "human",
  className: "warrior",
  level: 5,
  xp: 1000,
  locationId: "accord_guild_hall",
  locationName: "Guild Hall",
  hpCurrent: 25,
  hpMax: 30,
  deity: "",
  portraitUrl: null,
};

const OPTIONS = [
  { id: "warrior_battle_master", name: "Battle Master", description: "Tactical maneuvers." },
  { id: "warrior_berserker", name: "Berserker", description: "Rage state." },
];

beforeEach(() => {
  characterStore.getState().clear();
  hudStore.getState().reset();
});

// --- handler dispatch (AC1) ---

test("specialization_choice event sets the choice state with both options", () => {
  handleGameEvent({
    type: "specialization_choice",
    milestone_id: "warrior_identity",
    options: OPTIONS,
  });
  const choice = hudStore.getState().specializationChoice;
  expect(choice).not.toBeNull();
  expect(choice!.milestoneId).toBe("warrior_identity");
  expect(choice!.options).toHaveLength(2);
  expect(choice!.options[0].id).toBe("warrior_battle_master");
  expect(choice!.options[1].name).toBe("Berserker");
});

test("specialization_choice with missing options is a no-op", () => {
  handleGameEvent({ type: "specialization_choice", milestone_id: "warrior_identity" });
  expect(hudStore.getState().specializationChoice).toBeNull();
});

test("specialization_choice with empty options is a no-op", () => {
  handleGameEvent({ type: "specialization_choice", milestone_id: "x", options: [] });
  expect(hudStore.getState().specializationChoice).toBeNull();
});

test("specialization_choice drops options missing a usable id", () => {
  handleGameEvent({
    type: "specialization_choice",
    milestone_id: "warrior_identity",
    options: [
      { name: "No Id", description: "missing id" },
      { id: "", name: "Empty Id", description: "empty id" },
      { id: 42, name: "Numeric Id", description: "non-string id" },
      { id: "warrior_berserker", name: "Berserker", description: "Rage state." },
    ],
  });
  const choice = hudStore.getState().specializationChoice;
  expect(choice).not.toBeNull();
  expect(choice!.options).toHaveLength(1);
  expect(choice!.options[0].id).toBe("warrior_berserker");
});

test("specialization_choice with valid options but missing milestone_id is a no-op", () => {
  // The milestoneId is the choice_id the tap echoes to the agent's select verb;
  // without it every tap is dropped agent-side, so the overlay must not render.
  handleGameEvent({ type: "specialization_choice", options: OPTIONS });
  expect(hudStore.getState().specializationChoice).toBeNull();
});

test("specialization_choice with only malformed options is a no-op", () => {
  handleGameEvent({
    type: "specialization_choice",
    milestone_id: "warrior_identity",
    options: [{ name: "No Id" }, { id: "", name: "Empty" }],
  });
  expect(hudStore.getState().specializationChoice).toBeNull();
});

// --- independence from level-up (AC3) ---

test("xp_awarded level-up pushes a level_up overlay and does NOT set the choice state", () => {
  characterStore.getState().setCharacter(SAMPLE_CHARACTER);
  handleGameEvent({
    type: "xp_awarded",
    new_xp: 1000,
    new_level: 5,
    level_up: true,
    xp_gained: 100,
  });
  expect(hudStore.getState().specializationChoice).toBeNull();
  expect(hudStore.getState().overlays.some((o) => o.type === "level_up")).toBe(true);
});

// --- tap-send hint (AC2) ---

interface PublishCall {
  data: Uint8Array;
  opts: { reliable?: boolean; topic?: string };
}

function mockRoom(calls: PublishCall[]) {
  return {
    localParticipant: {
      publishData: (data: Uint8Array, opts: { reliable?: boolean; topic?: string }) => {
        calls.push({ data, opts });
      },
    },
  };
}

type RoomArg = Parameters<typeof sendSpecializationChoice>[0];

test("sendSpecializationChoice publishes a player_hints tap hint with both ids", () => {
  const calls: PublishCall[] = [];
  sendSpecializationChoice(
    mockRoom(calls) as unknown as RoomArg,
    "warrior_identity",
    "warrior_battle_master",
  );
  expect(calls).toHaveLength(1);
  expect(calls[0].opts.reliable).toBe(true);
  expect(calls[0].opts.topic).toBe("player_hints");
  const decoded = JSON.parse(new TextDecoder().decode(calls[0].data)) as Record<string, unknown>;
  expect(decoded).toEqual({
    type: "specialization_choice_tap",
    milestone_id: "warrior_identity",
    specialization_id: "warrior_battle_master",
  });
});

test("sendSpecializationChoice is a no-op without a room", () => {
  expect(() =>
    sendSpecializationChoice(null, "warrior_identity", "warrior_battle_master"),
  ).not.toThrow();
});
