"""Canonical game event type constants.

These strings are sent over the LiveKit data channel to the client.
Keep in sync with apps/mobile/src/audio/event-types.ts.
"""

# Audio / music
PLAY_SOUND = "play_sound"
SET_MUSIC_STATE = "set_music_state"

# Dice
DICE_ROLL = "dice_roll"
DICE_RESULT = "dice_result"  # client-only alias for DICE_ROLL

# Session lifecycle
SESSION_INIT = "session_init"
SESSION_END = "session_end"

# Location
LOCATION_CHANGED = "location_changed"

# Combat
COMBAT_STARTED = "combat_started"
COMBAT_ENDED = "combat_ended"
COMBAT_UI_UPDATE = "combat_ui_update"

# Character
SKILL_TIER_ADVANCED = "skill_tier_advanced"
XP_AWARDED = "xp_awarded"
LEVEL_UP = "level_up"
HP_CHANGED = "hp_changed"
STATUS_EFFECT = "status_effect"
DIVINE_FAVOR_CHANGED = "divine_favor_changed"
PLAYER_PORTRAIT_READY = "player_portrait_ready"

# Inventory & quests
ITEM_ACQUIRED = "item_acquired"
INVENTORY_UPDATED = "inventory_updated"
ITEM_DURABILITY_HIT = "item_durability_hit"
QUEST_UPDATED = "quest_updated"
QUEST_UPDATE = "quest_update"  # client-only alias for QUEST_UPDATED

# Magic (M3.1)
# Resonance state push: carries the qualitative {state} only on the game_events topic
# — the raw number never crosses to the client (no-number spec magic.md:98, story-004).
# Mirror const in apps/mobile/src/audio/event-types.ts.
RESONANCE_CHANGED = "resonance_changed"

# Magic (M3.2) — Veil Ward toggle push: carries the minimal {active} only (the HUD shows a
# glanceable on/off zone indicator; the source archetype is narration the DM voices, not wire
# state). Mirror const in apps/mobile/src/audio/event-types.ts (story-005).
VEIL_WARD_CHANGED = "veil_ward_changed"

# Magic (M3.2) — Hollow Echo result push: carries the qualitative {band} only (the dramatic
# dice overlay maps band -> label/colour; the raw roll stays server-side, no-number discipline).
# Auto-rolled by cast_spell at Overreach. Mirror const in apps/mobile/src/audio/event-types.ts (story-005).
HOLLOW_ECHO_RESULT = "hollow_echo_result"

# World
HOLLOW_CORRUPTION_CHANGED = "hollow_corruption_changed"
DISPOSITION_CHANGED = "disposition_changed"
WORLD_EVENT = "world_event"
# Emitted by check(mode=discover) on a successful discovery (M6). Server-internal:
# the warm-layer rebuild + hot-layer record consumer lands in story-003 (bg_event_handlers
# does not yet handle it). Reveals reach the player via the DM's voice, not a HUD affordance
# — so this is intentionally NOT mirrored in apps/mobile (the client ignores unknown types).
HIDDEN_REVEALED = "hidden_revealed"

# Transcript
TRANSCRIPT_ENTRY = "transcript_entry"

# Character creation
CREATION_CARDS = "creation_cards"
CREATION_CARD_SELECTED = "creation_card_selected"

# Archetype milestones (M2.3) — the L5 specialization fork the HUD glances (story-005)
SPECIALIZATION_CHOICE = "specialization_choice"

# Client → Agent hints (received via data channel, topic "player_hints")
CREATION_CARD_TAP = "creation_card_tap"
# L5 specialization card tapped on the HUD during gameplay (story-008). Wire value
# matches apps/mobile/src/audio/event-types.ts SPECIALIZATION_CHOICE_TAP.
SPECIALIZATION_CHOICE_TAP = "specialization_choice_tap"
