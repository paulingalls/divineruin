import { test, expect, beforeEach } from "bun:test";
import {
  hudStore,
  type StatusEffect,
  type CombatTrackerState,
  type CreationCard,
} from "@/stores/hud-store";

beforeEach(() => {
  hudStore.getState().reset();
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
