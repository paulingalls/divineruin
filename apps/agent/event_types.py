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
# Combat HUD condition + tracker push (M12) — emitted by combat_turn._resolve_phase_impl at the
# Beat-4 wrap POST-tick (save-cleared conditions are absent), only when combat does NOT end on the
# wrap (the terminal wrap path relies on COMBAT_ENDED + hudStore.clearCombatState). Also emitted
# directly by combat_init.start_combat after COMBAT_STARTED so the HUD has live combatants from
# round 1 (story-001 close fix). The wrap-time packet is built by combat_ui_update.build_combat_ui_update
# and rides the buffered EventSink, so a rolled-back phase tx publishes nothing.
#   Packet: {round, combatants:[{id, name, isAlly, hpCurrent, hpMax,
#           conditions:[{type, stacks, source}], isActive}]}
# `round` reflects the NEW round at wrap (advance_combat_phase has already incremented round_number
# before the emit). `isActive=True` marks initiative_order[current_turn_index] — the next-up LIVE
# actor (fallen/dead are skipped). Conditions are projected to {type, stacks, source} only (mobile
# parseCondition reads no more); duration/stage stay server-side.
# Mirror const in apps/mobile/src/audio/event-types.ts.
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

# Currency (M4.7 story-002) — coin granted on combat victory (role-scaled, calculate_currency_drop).
# Packet: {player_id, amount, currency, source, new_balance} where `amount` is the gold
# gained this victory (aggregated across all defeated enemies, converted sp->gp at the grant
# boundary via silver_per_gold — story-008), `currency` is the unit ("gold"), `source` the grant
# context ("combat"), and `new_balance` the player's resulting players.data.gold (gold crowns).
# The HUD renders a glanceable "+N gp" chip from {amount, currency}; the DM voices the haul.
# Mirror const in apps/mobile/src/audio/event-types.ts.
CURRENCY_GAINED = "currency_gained"

# Magic (M3.1)
# Resonance state push. Packet: {state, caster_id} — the qualitative state only on the game_events
# topic; the raw number never crosses to the client (no-number spec magic.md:98, story-004).
# `caster_id` (M14 story-004) names WHICH party member the state belongs to so a multi-player client
# updates its single global HUD tracker only for the local player's pushes (game-event-handler.ts
# filters on it); it defaults to the session primary. Mirror const in apps/mobile/src/audio/event-types.ts.
RESONANCE_CHANGED = "resonance_changed"

# Magic (M3.2) — Veil Ward toggle push. Packet: {active} — the minimal on/off toggle only (the
# HUD shows a glanceable ward zone indicator; the source archetype is narration the DM voices,
# not wire state). Mirror const in apps/mobile/src/audio/event-types.ts (story-005).
VEIL_WARD_CHANGED = "veil_ward_changed"

# Magic (M3.2) — Hollow Echo result push. Packet: {band} — the qualitative band only (the dramatic
# dice overlay maps band -> label/colour; the raw roll stays server-side, no-number discipline).
# Auto-rolled by cast_spell at Overreach. Mirror const in apps/mobile/src/audio/event-types.ts (story-005).
HOLLOW_ECHO_RESULT = "hollow_echo_result"

# Magic (M3.5) — Vaelti Hyper-awareness 1-round advance warning (story-009). Bus-only,
# server-internal: emitted when a Vaelti's cast reaches Overreach and consumed by
# bg_event_handlers, which queues the DM warning speech. Not pushed to the client.
VAELTI_ECHO_WARNING = "vaelti_echo_warning"

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
