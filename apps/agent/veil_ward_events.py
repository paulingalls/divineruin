"""Client push path for the Veil Ward (story-004, M24).

``publish_veil_ward_changed`` emits VEIL_WARD_CHANGED over the game_events data channel. It lived
inside veil_ward_tools until arrival needed it too — a party that walks out of a warded location
must not leave its indicator lit — so it moved to its own module beside
``resonance_events.publish_resonance_changed``.

The payload is {active, caster_id}: the HUD shows a glanceable zone indicator, and the source
archetype is narration the DM voices, not wire state. story-008 rebuilds the payload as
scope-membership ({active, scope_kind, scope_id, source}) so every in-scope client lights up.

``active`` must be the party's RESOLVED warded state — computed via
``ward_resolution.resolve_scope_ward``, never read off the scope the caller just mutated
(veil_ward_scope_model.md §3). On combat end the encounter ward dies, but if a location ward still
covers the party this event carries active=True. A producer that keyed the flag to the expiring
scope would turn the ward light off while the party's casts are still being halved.
"""

from event_types import VEIL_WARD_CHANGED
from game_events import publish_game_event
from session_data import SessionData


async def publish_veil_ward_changed(session: SessionData, active: bool, caster_id: str) -> None:
    """Push the ward's resolved on/off state to the client as a VEIL_WARD_CHANGED event.

    ``caster_id`` is the resolved caster (the session primary, or an explicit non-primary member
    when one raises or dismisses). On arrival there is no caster, so callers pass the primary.
    """
    await publish_game_event(
        session.room, VEIL_WARD_CHANGED, {"active": active, "caster_id": caster_id}, session.event_bus
    )
