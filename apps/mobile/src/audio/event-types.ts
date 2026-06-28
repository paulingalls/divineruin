/**
 * Canonical game event type constants.
 *
 * These strings arrive over the LiveKit data channel from the Python agent.
 * Keep in sync with apps/agent/event_types.py.
 */

// Audio / music
export const PLAY_SOUND = "play_sound" as const;
export const SET_MUSIC_STATE = "set_music_state" as const;

// Dice
// Payload {roll, modifier, total, success, roll_type, narrative}. Optional `dramatic`
// (boolean): when explicitly true, the HUD plays the full tumble-and-reveal; false/absent
// suppresses it (scarcity gate, story-006). The agent does not emit `dramatic` until
// stories 004/005, so live rolls carry no flag yet and stay suppressed in the interim.
export const DICE_ROLL = "dice_roll" as const;
export const DICE_RESULT = "dice_result" as const;

// Session lifecycle
export const SESSION_INIT = "session_init" as const;
export const SESSION_END = "session_end" as const;

// Location
export const LOCATION_CHANGED = "location_changed" as const;

// Combat
export const COMBAT_STARTED = "combat_started" as const;
export const COMBAT_ENDED = "combat_ended" as const;
// Combat HUD condition + tracker push (M12) — mirrors apps/agent/event_types.py COMBAT_UI_UPDATE.
// Emitted by the agent at Beat-4 wrap POST-tick (save-cleared conditions are absent) and ONLY when
// combat does NOT end on the wrap (the terminal wrap path relies on COMBAT_ENDED +
// hudStore.clearCombatState — a same-flush UI_UPDATE would flash state on then off). The packet
// rides the buffered EventSink so a rolled-back phase tx publishes nothing.
//   Packet: {phase, round, combatants:[{id, name, isAlly, hpCurrent, hpMax,
//           conditions:[{type, stacks, source}], isActive}]}
// `phase`/`round` reflect the NEW round (the agent's advance_combat_phase has already transitioned
// the wrap into the next declaration beat and incremented round_number before the emit). `isActive`
// marks initiative_order[current_turn_index] — the next-up actor. Conditions carry only
// {type, stacks, source}; agent-side duration/stage stay server-side. parseCombatant + parseCondition
// (game-event-handler.ts) implement the fail-soft defaults (isAlly default false, stacks default 1,
// source default ""). Drift guards live in use-game-events.overlays.test.ts.
export const COMBAT_UI_UPDATE = "combat_ui_update" as const;

// Character
export const XP_AWARDED = "xp_awarded" as const;
export const LEVEL_UP = "level_up" as const;
export const HP_CHANGED = "hp_changed" as const;
export const STATUS_EFFECT = "status_effect" as const;
export const DIVINE_FAVOR_CHANGED = "divine_favor_changed" as const;
export const PLAYER_PORTRAIT_READY = "player_portrait_ready" as const;

// Inventory & quests
export const ITEM_ACQUIRED = "item_acquired" as const;
export const INVENTORY_UPDATED = "inventory_updated" as const;
export const QUEST_UPDATE = "quest_update" as const;
export const QUEST_UPDATED = "quest_updated" as const;

// Currency (M4.7 story-002) — mirrors apps/agent/event_types.py CURRENCY_GAINED. Coin granted on
// combat victory, converted sp->gp at the grant boundary (story-008). Payload {player_id, amount,
// currency, source, new_balance} in gold crowns; the HUD renders a glanceable "+N gp" chip from
// {amount, currency} (see components/hud/currency-display.ts).
export const CURRENCY_GAINED = "currency_gained" as const;

// Magic (M3.1) — mirrors apps/agent/event_types.py RESONANCE_CHANGED.
// Payload {state, current, max}; the HUD renders only the qualitative state.
export const RESONANCE_CHANGED = "resonance_changed" as const;

// Magic (M3.2) — mirrors apps/agent/event_types.py. HOLLOW_ECHO_RESULT carries the
// qualitative {band} only (raw d20 stays server-side, like RESONANCE_CHANGED);
// VEIL_WARD_CHANGED carries {active} for the glanceable ward zone indicator.
export const HOLLOW_ECHO_RESULT = "hollow_echo_result" as const;
export const VEIL_WARD_CHANGED = "veil_ward_changed" as const;

// World
export const HOLLOW_CORRUPTION_CHANGED = "hollow_corruption_changed" as const;
export const DISPOSITION_CHANGED = "disposition_changed" as const;
export const WORLD_EVENT = "world_event" as const;

// Transcript
export const TRANSCRIPT_ENTRY = "transcript_entry" as const;

// Character creation
export const CREATION_CARDS = "creation_cards" as const;
export const CREATION_CARD_SELECTED = "creation_card_selected" as const;

// Archetype milestones (M2.3) — the L5 specialization fork the HUD glances (consumed story-005)
export const SPECIALIZATION_CHOICE = "specialization_choice" as const;

// Client → Agent hints
export const CREATION_CARD_TAP = "creation_card_tap" as const;
// M2.3: the player tapped an L5 specialization path on the HUD overlay (story-005).
// Agent-side consumption (hint -> resolve_milestone) is a future wire-up; the DM voice
// path already resolves via story-004's resolve_milestone tool.
export const SPECIALIZATION_CHOICE_TAP = "specialization_choice_tap" as const;
