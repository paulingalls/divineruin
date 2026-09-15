import { beforeEach, expect, test } from "bun:test";

import { handleGameEvent } from "@/audio/game-event-handler";
import { selectCompanionPortrait } from "@/components/hud/companion-portrait";
import { portraitStore } from "@/stores/portrait-store";

import { captureTimers, resetStores } from "./use-game-events.helpers";

beforeEach(resetStores);

function assignCompanion(primary: string | null = "/api/assets/images/sable-primary") {
  portraitStore.getState().setCompanionIdentity("Sable", "COMPANION_SABLE");
  portraitStore.getState().setCompanionPortraits(primary, "/api/assets/images/sable-alert");
}

test("matching companion cue shows the portrait and hides it after five seconds", () => {
  assignCompanion();

  const timers = captureTimers(() => {
    handleGameEvent({ type: "companion_cue", voice_id: "COMPANION_SABLE" });
  });

  expect(portraitStore.getState().companionVisible).toBe(true);
  const hide = timers.find((timer) => timer.delay === 5000);
  expect(hide).toBeDefined();
  hide!.fn();
  expect(portraitStore.getState().companionVisible).toBe(false);
});

test("another companion's cue does not show the assigned portrait", () => {
  assignCompanion();

  handleGameEvent({ type: "companion_cue", voice_id: "COMPANION_LIRA" });

  expect(portraitStore.getState().companionVisible).toBe(false);
});

test("companion cue leaves the active NPC portrait on screen", () => {
  assignCompanion();
  portraitStore.getState().setActiveNpc("Torin", "/api/assets/images/torin");

  handleGameEvent({ type: "companion_cue", voice_id: "COMPANION_SABLE" });

  expect(portraitStore.getState().activeNpc).toEqual({
    name: "Torin",
    url: "/api/assets/images/torin",
  });
});

test("companion cue with no primary portrait does not show", () => {
  assignCompanion(null);

  handleGameEvent({ type: "companion_cue", voice_id: "COMPANION_SABLE" });

  expect(portraitStore.getState().companionVisible).toBe(false);
});

test("dm transcript carrying a companion tag does not show the portrait", () => {
  assignCompanion();

  handleGameEvent({
    type: "transcript_entry",
    speaker: "dm",
    character: "COMPANION_SABLE",
    text: "Sable huffs and points down the road.",
  });

  expect(portraitStore.getState().companionVisible).toBe(false);
});

const PRIMARY = "/api/assets/images/sable-primary";
const ALERT = "/api/assets/images/sable-alert";

test("hidden companion has no selected portrait", () => {
  expect(
    selectCompanionPortrait({
      companionVisible: false,
      companionPrimaryUrl: PRIMARY,
      companionAlertUrl: ALERT,
      combatState: null,
    }),
  ).toBeNull();
});

test("visible companion selects primary outside combat", () => {
  expect(
    selectCompanionPortrait({
      companionVisible: true,
      companionPrimaryUrl: PRIMARY,
      companionAlertUrl: ALERT,
      combatState: null,
    }),
  ).toBe(PRIMARY);
});

test("visible companion selects alert during combat", () => {
  expect(
    selectCompanionPortrait({
      companionVisible: true,
      companionPrimaryUrl: PRIMARY,
      companionAlertUrl: ALERT,
      combatState: { round: 1, combatants: [] },
    }),
  ).toBe(ALERT);
});

test("visible companion with no selected variant has no portrait", () => {
  expect(
    selectCompanionPortrait({
      companionVisible: true,
      companionPrimaryUrl: null,
      companionAlertUrl: ALERT,
      combatState: null,
    }),
  ).toBeNull();
  expect(
    selectCompanionPortrait({
      companionVisible: true,
      companionPrimaryUrl: PRIMARY,
      companionAlertUrl: null,
      combatState: { round: 1, combatants: [] },
    }),
  ).toBeNull();
});
