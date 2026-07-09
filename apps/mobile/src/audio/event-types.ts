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
// Emitted at combat-start (after COMBAT_STARTED, before SOUND_COMBAT_START) AND at each Beat-4
// wrap POST-tick (save-cleared conditions are absent). Skipped on the terminal wrap so
// COMBAT_ENDED + hudStore.clearCombatState own the teardown. Wrap-time packet rides the buffered
// EventSink, so a rolled-back phase tx publishes nothing.
//   Packet: {round, combatants:[{id, name, isAlly, hpCurrent, hpMax,
//           conditions:[{type, stacks, source}], isActive}]}
// `round` reflects the NEW round at wrap (round_number was incremented by advance_combat_phase
// before the emit). `isActive` marks the next-up LIVE actor (fallen/dead skipped). Conditions
// carry only {type, stacks, source}; agent-side duration/stage stay server-side. parseCombatant
// + parseCondition (game-event-handler.ts) implement the fail-soft defaults (isAlly default false,
// stacks default 1, source default ""). Drift guards live in use-game-events.overlays.test.ts.
export const COMBAT_UI_UPDATE = "combat_ui_update" as const;

// Character
export const XP_AWARDED = "xp_awarded" as const;
export const LEVEL_UP = "level_up" as const;
export const HP_CHANGED = "hp_changed" as const;
export const STATUS_EFFECT = "status_effect" as const;
export const DIVINE_FAVOR_CHANGED = "divine_favor_changed" as const;
export const PLAYER_PORTRAIT_READY = "player_portrait_ready" as const;

// Inventory & quests
// ITEM_ACQUIRED combat-loot packet (M20 story-001) — mirrors apps/agent/event_types.py. Gains
// `player_id`, the recipient party member a round-robinned drop was granted to, mirroring
// CURRENCY_GAINED's player_id. game-event-handler.ts filters the overlay/SFX to the local
// recipient via isEventForLocalPlayer; a non-combat emitter that omits player_id still fires
// (back-compat, same convention as RESONANCE_CHANGED's caster_id default; VEIL_WARD_CHANGED
// carries no caster_id at all — it is scope-owned, see below).
export const ITEM_ACQUIRED = "item_acquired" as const;
export const INVENTORY_UPDATED = "inventory_updated" as const;
export const QUEST_UPDATE = "quest_update" as const;
export const QUEST_UPDATED = "quest_updated" as const;

// Currency (M4.7 story-002) — mirrors apps/agent/event_types.py CURRENCY_GAINED. Coin granted on
// combat victory, converted sp->gp at the grant boundary (story-008).
// Packet: {player_id, amount, currency, source, new_balance} in gold crowns; the HUD renders a
// glanceable "+N gp" chip from {amount, currency} (see components/hud/currency-display.ts).
export const CURRENCY_GAINED = "currency_gained" as const;

// Magic (M3.1) — mirrors apps/agent/event_types.py RESONANCE_CHANGED.
// Packet: {state, caster_id} — the qualitative state only; the raw number never crosses to the
// client (no-number spec, magic.md:98). `caster_id` (M14 story-004) names WHICH party member the
// state belongs to; game-event-handler.ts updates the single global HUD tracker ONLY when caster_id
// is the local player's, so another member's push never overwrites the local resonance state.
export const RESONANCE_CHANGED = "resonance_changed" as const;

// Magic (M3.2) — mirrors apps/agent/event_types.py. HOLLOW_ECHO_RESULT Packet: {band} — the
// qualitative band only (raw d20 stays server-side, like RESONANCE_CHANGED);
// VEIL_WARD_CHANGED Packet: {active, scope_kind, scope_id, source} (story-008) for the glanceable
// ward zone indicator. `active` is the party's RESOLVED warded state across all covering scopes.
//
// Deliberately NO caster_id: a ward belongs to a scope and halves EVERY caster in it, so every
// in-scope client lights up — there is nothing to filter on. RESONANCE_CHANGED above keeps its
// caster_id because Resonance is per-caster. Do not add a filter back here (scope_model.md §6).
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
