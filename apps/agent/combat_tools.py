"""Combat tools — re-exports for backward compatibility during migration."""

from combat_end import _end_combat_impl, end_combat
from combat_init import _start_combat_impl, start_combat
from combat_support import _participant_summary, _publish_sounds, _require_combat
from combat_turn import (
    _request_death_save_impl,
    _resolve_enemy_turn_impl,
    request_death_save,
    resolve_enemy_turn,
)
from game_events import publish_game_event

__all__ = [
    "_end_combat_impl",
    "_participant_summary",
    "_publish_sounds",
    "_request_death_save_impl",
    "_require_combat",
    "_resolve_enemy_turn_impl",
    "_start_combat_impl",
    "end_combat",
    "publish_game_event",
    "request_death_save",
    "resolve_enemy_turn",
    "start_combat",
]
