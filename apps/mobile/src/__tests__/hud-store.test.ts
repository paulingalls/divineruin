import { test, expect, beforeEach } from "bun:test";
import {
  hudStore,
  HOLLOW_ECHO_DISPLAY,
  RESONANCE_TRACKER_BOTTOM_DEFAULT,
  type HollowEchoBand,
  type OverlayType,
  type StatusEffect,
  type CombatTrackerState,
  type CreationCard,
} from "@/stores/hud-store";
import { HUD_ANCHORS } from "@/constants/hud-anchors";
import { HOLLOW_ECHO_RESULT, VEIL_WARD_CHANGED } from "@/audio/event-types";
import { handleGameEvent, VALID_HOLLOW_ECHO_BANDS } from "@/audio/game-event-handler";

// The 7 Hollow Echo bands, mirroring the agent's hollow_echo._BANDS ids. The HUD
// flashes the band name when an Overreach cast tears the Veil (story-004 publishes
// HOLLOW_ECHO_RESULT {band}); only the band crosses the wire, never the raw d20.
const HOLLOW_ECHO_BANDS: HollowEchoBand[] = [
  "nothing",
  "whisper",
  "veil_scar",
  "sympathetic",
  "hollow_attention",
  "reality_fracture",
  "breach",
];

beforeEach(() => {
  hudStore.getState().reset();
});

// --- HUD_ANCHORS: single source of truth for bottom-anchored HUD insets (Try-1) ---
// The XP/divine-favor toasts and the combat tracker all anchor at the same bottom
// inset; before this they each hard-coded bottom:80, so a layout shift meant editing
// four places. HUD_ANCHORS centralizes the value (closes concern 61cae1d5).

test("HUD_ANCHORS.bottomToast is the shared 80px bottom inset", () => {
  expect(HUD_ANCHORS.bottomToast).toBe(80);
});

test("RESONANCE_TRACKER_BOTTOM_DEFAULT is sourced from HUD_ANCHORS (no drift)", () => {
  expect(RESONANCE_TRACKER_BOTTOM_DEFAULT).toBe(HUD_ANCHORS.bottomToast);
});

// --- HOLLOW_ECHO_DISPLAY: band -> dramatic label + accent color (story-005 M2) ---

test("HOLLOW_ECHO_DISPLAY resolves every band to a non-empty label and color (no gaps)", () => {
  for (const band of HOLLOW_ECHO_BANDS) {
    const display = HOLLOW_ECHO_DISPLAY[band];
    expect(display).toBeDefined();
    expect(display.label.length).toBeGreaterThan(0);
    expect(display.color.length).toBeGreaterThan(0);
  }
});

test("HOLLOW_ECHO_DISPLAY has no entries beyond the 7 canonical bands", () => {
  expect(Object.keys(HOLLOW_ECHO_DISPLAY).sort()).toEqual([...HOLLOW_ECHO_BANDS].sort());
});

// --- Veil Ward zone state (story-005 M2) ---

test("veilWardActive defaults to false (no ward indicator)", () => {
  expect(hudStore.getState().veilWardActive).toBe(false);
});

test("setVeilWardActive toggles the ward state", () => {
  hudStore.getState().setVeilWardActive(true);
  expect(hudStore.getState().veilWardActive).toBe(true);
  hudStore.getState().setVeilWardActive(false);
  expect(hudStore.getState().veilWardActive).toBe(false);
});

test("reset() clears veilWardActive", () => {
  hudStore.getState().setVeilWardActive(true);
  hudStore.getState().reset();
  expect(hudStore.getState().veilWardActive).toBe(false);
});

// --- Event dispatch: HOLLOW_ECHO_RESULT + VEIL_WARD_CHANGED (story-005 M3) ---

test("HOLLOW_ECHO_RESULT / VEIL_WARD_CHANGED mirror the agent wire values", () => {
  expect(HOLLOW_ECHO_RESULT).toBe("hollow_echo_result");
  expect(VEIL_WARD_CHANGED).toBe("veil_ward_changed");
});

test("VALID_HOLLOW_ECHO_BANDS covers exactly the 7 canonical bands", () => {
  expect([...VALID_HOLLOW_ECHO_BANDS].sort()).toEqual([...HOLLOW_ECHO_BANDS].sort());
});

test("hollow_echo_result with a known band pushes a hollow_echo overlay (AC1)", () => {
  handleGameEvent({ type: "hollow_echo_result", band: "breach" });
  const overlays = hudStore.getState().overlays;
  expect(overlays).toHaveLength(1);
  expect(overlays[0].type).toBe("hollow_echo");
  expect(overlays[0].payload.band).toBe("breach");
});

test("hollow_echo_result dispatches every valid band", () => {
  for (const band of HOLLOW_ECHO_BANDS) {
    hudStore.getState().reset();
    handleGameEvent({ type: "hollow_echo_result", band });
    expect(hudStore.getState().overlays[0]?.payload.band).toBe(band);
  }
});

test("hollow_echo_result with an unknown band is dropped, store uncorrupted (AC3)", () => {
  handleGameEvent({ type: "hollow_echo_result", band: "cataclysm" });
  expect(hudStore.getState().overlays).toHaveLength(0);
});

test("hollow_echo_result with a missing band is dropped (fail-safe)", () => {
  handleGameEvent({ type: "hollow_echo_result" });
  expect(hudStore.getState().overlays).toHaveLength(0);
});

test("veil_ward_changed reflects the active toggle in the store (AC2)", () => {
  handleGameEvent({ type: "veil_ward_changed", active: true });
  expect(hudStore.getState().veilWardActive).toBe(true);
  handleGameEvent({ type: "veil_ward_changed", active: false });
  expect(hudStore.getState().veilWardActive).toBe(false);
});

test("veil_ward_changed with a non-boolean active is ignored (fail-safe)", () => {
  hudStore.getState().setVeilWardActive(true);
  handleGameEvent({ type: "veil_ward_changed", active: "yes" });
  // Unchanged — a malformed payload must not corrupt the ward state.
  expect(hudStore.getState().veilWardActive).toBe(true);
});

// --- pushOverlay ---

test("pushOverlay adds entry with generated id", () => {
  const id = hudStore.getState().pushOverlay("dice_result", { roll: 14 });
  const overlays = hudStore.getState().overlays;
  expect(overlays).toHaveLength(1);
  expect(overlays[0].id).toBe(id);
  expect(overlays[0].type).toBe("dice_result");
  expect(overlays[0].payload).toEqual({ roll: 14 });
  expect(overlays[0].ttl).toBe(3500);
});

test("pushOverlay uses custom ttl", () => {
  hudStore.getState().pushOverlay("xp_toast", { xp: 50 }, 2500);
  expect(hudStore.getState().overlays[0].ttl).toBe(2500);
});

test("pushOverlay enforces max 1 overlay — newer replaces older", () => {
  hudStore.getState().pushOverlay("dice_result", { roll: 10 });
  hudStore.getState().pushOverlay("item_acquired", { name: "Sword" });
  const overlays = hudStore.getState().overlays;
  expect(overlays).toHaveLength(1);
  expect(overlays[0].type).toBe("item_acquired");
});

test("pushOverlay records createdAt timestamp", () => {
  const before = Date.now();
  hudStore.getState().pushOverlay("dice_result", { roll: 10 });
  const after = Date.now();
  const overlay = hudStore.getState().overlays[0];
  expect(overlay.createdAt).toBeGreaterThanOrEqual(before);
  expect(overlay.createdAt).toBeLessThanOrEqual(after);
});

test("pushOverlay defaults TTL to 3500ms", () => {
  hudStore.getState().pushOverlay("dice_result", { roll: 10 });
  expect(hudStore.getState().overlays[0].ttl).toBe(3500);
});

test("pushOverlay accepts custom TTL", () => {
  hudStore.getState().pushOverlay("level_up", { newLevel: 5 }, 5000);
  expect(hudStore.getState().overlays[0].ttl).toBe(5000);
});

// --- dismissOverlay ---

test("dismissOverlay removes by id", () => {
  const id = hudStore.getState().pushOverlay("dice_result", {});
  hudStore.getState().dismissOverlay(id);
  expect(hudStore.getState().overlays).toHaveLength(0);
});

test("dismissOverlay with unknown id is no-op", () => {
  hudStore.getState().pushOverlay("dice_result", {});
  hudStore.getState().dismissOverlay("nonexistent");
  expect(hudStore.getState().overlays).toHaveLength(1);
});

// --- dismissAllOverlays ---

test("dismissAllOverlays clears all", () => {
  hudStore.getState().pushOverlay("dice_result", {});
  hudStore.getState().dismissAllOverlays();
  expect(hudStore.getState().overlays).toHaveLength(0);
});

// --- Status effects ---

test("addStatusEffect adds effect", () => {
  const effect: StatusEffect = { id: "buff-1", name: "Blessed", category: "buff" };
  hudStore.getState().addStatusEffect(effect);
  expect(hudStore.getState().statusEffects).toHaveLength(1);
  expect(hudStore.getState().statusEffects[0]).toEqual(effect);
});

test("addStatusEffect replaces existing effect with same id", () => {
  hudStore.getState().addStatusEffect({ id: "e1", name: "Old", category: "buff" });
  hudStore.getState().addStatusEffect({ id: "e1", name: "New", category: "debuff" });
  expect(hudStore.getState().statusEffects).toHaveLength(1);
  expect(hudStore.getState().statusEffects[0].name).toBe("New");
});

test("removeStatusEffect removes by id", () => {
  hudStore.getState().addStatusEffect({ id: "e1", name: "Blessed", category: "buff" });
  hudStore.getState().removeStatusEffect("e1");
  expect(hudStore.getState().statusEffects).toHaveLength(0);
});

test("setStatusEffects replaces all", () => {
  hudStore.getState().addStatusEffect({ id: "e1", name: "Old", category: "buff" });
  const effects: StatusEffect[] = [
    { id: "e2", name: "Cursed", category: "debuff" },
    { id: "e3", name: "Haste", category: "buff" },
  ];
  hudStore.getState().setStatusEffects(effects);
  expect(hudStore.getState().statusEffects).toHaveLength(2);
  expect(hudStore.getState().statusEffects[0].id).toBe("e2");
});

// --- Quest objective ---

test("setActiveObjective sets objective and makes visible", () => {
  hudStore.getState().setActiveObjective({
    questName: "Guild Initiation",
    objective: "Find the cartographer",
    updatedAt: 1000,
  });
  expect(hudStore.getState().activeObjective).not.toBeNull();
  expect(hudStore.getState().activeObjective!.questName).toBe("Guild Initiation");
  expect(hudStore.getState().questObjectiveVisible).toBe(true);
});

test("setQuestObjectiveVisible toggles visibility", () => {
  hudStore.getState().setActiveObjective({
    questName: "Q",
    objective: "O",
    updatedAt: 0,
  });
  hudStore.getState().setQuestObjectiveVisible(false);
  expect(hudStore.getState().questObjectiveVisible).toBe(false);
});

// --- Combat state ---

test("setCombatState sets combat tracker", () => {
  const combat: CombatTrackerState = {
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
  };
  hudStore.getState().setCombatState(combat);
  expect(hudStore.getState().combatState).not.toBeNull();
  expect(hudStore.getState().combatState!.round).toBe(2);
  expect(hudStore.getState().combatState!.combatants).toHaveLength(1);
});

test("clearCombatState clears combat", () => {
  hudStore.getState().setCombatState({ phase: "init", round: 1, combatants: [] });
  hudStore.getState().clearCombatState();
  expect(hudStore.getState().combatState).toBeNull();
});

// --- Creation cards ---

test("setCreationCards sets cards and clears selection", () => {
  const cards: CreationCard[] = [
    { id: "c1", title: "Warrior", description: "Strong fighter", category: "class" },
    { id: "c2", title: "Mage", description: "Arcane power", category: "class" },
  ];
  hudStore.getState().setCreationCards(cards);
  expect(hudStore.getState().creationCards).toHaveLength(2);
  expect(hudStore.getState().selectedCreationCard).toBeNull();
});

test("setSelectedCreationCard selects a card", () => {
  hudStore
    .getState()
    .setCreationCards([{ id: "c1", title: "Warrior", description: "Strong", category: "class" }]);
  hudStore.getState().setSelectedCreationCard("c1");
  expect(hudStore.getState().selectedCreationCard).toBe("c1");
});

test("clearCreationCards clears cards and selection", () => {
  hudStore
    .getState()
    .setCreationCards([{ id: "c1", title: "Warrior", description: "Strong", category: "class" }]);
  hudStore.getState().setSelectedCreationCard("c1");
  hudStore.getState().clearCreationCards();
  expect(hudStore.getState().creationCards).toHaveLength(0);
  expect(hudStore.getState().selectedCreationCard).toBeNull();
});

// --- overlay type exhaustiveness ---

test("all OverlayType values can be pushed to store", () => {
  // Keep in sync with OverlayType union in hud-store.ts.
  // If you add a new type, also add a renderer case in OverlayContent (overlay-manager.tsx).
  const ALL_OVERLAY_TYPES: OverlayType[] = [
    "dice_result",
    "item_acquired",
    "quest_update",
    "xp_toast",
    "level_up",
    "divine_favor",
    "hollow_echo",
  ];

  for (const type of ALL_OVERLAY_TYPES) {
    hudStore.getState().reset();
    hudStore.getState().pushOverlay(type, {});
    const overlay = hudStore.getState().overlays[0];
    expect(overlay).toBeDefined();
    expect(overlay.type).toBe(type);
  }
});

// --- reset ---

test("reset clears everything", () => {
  hudStore.getState().pushOverlay("dice_result", {});
  hudStore.getState().addStatusEffect({ id: "e1", name: "Buff", category: "buff" });
  hudStore.getState().setActiveObjective({ questName: "Q", objective: "O", updatedAt: 0 });
  hudStore.getState().setCombatState({ phase: "init", round: 1, combatants: [] });
  hudStore
    .getState()
    .setCreationCards([{ id: "c1", title: "T", description: "D", category: "cat" }]);

  hudStore.getState().reset();

  expect(hudStore.getState().overlays).toHaveLength(0);
  expect(hudStore.getState().statusEffects).toHaveLength(0);
  expect(hudStore.getState().activeObjective).toBeNull();
  expect(hudStore.getState().questObjectiveVisible).toBe(false);
  expect(hudStore.getState().combatState).toBeNull();
  expect(hudStore.getState().creationCards).toHaveLength(0);
  expect(hudStore.getState().selectedCreationCard).toBeNull();
});
