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

// World
export const HOLLOW_CORRUPTION_CHANGED = "hollow_corruption_changed" as const;
export const DISPOSITION_CHANGED = "disposition_changed" as const;
export const WORLD_EVENT = "world_event" as const;

// Transcript
export const TRANSCRIPT_ENTRY = "transcript_entry" as const;

// Character creation
export const CREATION_CARDS = "creation_cards" as const;
export const CREATION_CARD_SELECTED = "creation_card_selected" as const;

// Client → Agent hints
export const CREATION_CARD_TAP = "creation_card_tap" as const;
