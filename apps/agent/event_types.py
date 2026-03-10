"""Canonical game event type constants.

These strings are sent over the LiveKit data channel to the client.
Keep in sync with apps/mobile/src/audio/event-types.ts.
"""

# Audio / music
PLAY_SOUND = "play_sound"
SET_MUSIC_STATE = "set_music_state"
PLAY_NARRATION = "play_narration"
STOP_NARRATION = "stop_narration"

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
XP_AWARDED = "xp_awarded"
HP_CHANGED = "hp_changed"
STATUS_EFFECT = "status_effect"
DIVINE_FAVOR_CHANGED = "divine_favor_changed"
PLAYER_PORTRAIT_READY = "player_portrait_ready"

# Inventory & quests
ITEM_ACQUIRED = "item_acquired"
INVENTORY_UPDATED = "inventory_updated"
QUEST_UPDATED = "quest_updated"
QUEST_UPDATE = "quest_update"  # client-only alias for QUEST_UPDATED

# World
HOLLOW_CORRUPTION_CHANGED = "hollow_corruption_changed"
DISPOSITION_CHANGED = "disposition_changed"
WORLD_EVENT = "world_event"

# Transcript
TRANSCRIPT_ENTRY = "transcript_entry"

# Character creation
CREATION_CARDS = "creation_cards"
CREATION_CARD_SELECTED = "creation_card_selected"
