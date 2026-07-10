"""Client push path for the Veil Ward (story-004, reshaped in story-008; M24).

``publish_veil_ward_changed`` emits VEIL_WARD_CHANGED over the game_events data channel. It lived
inside veil_ward_tools until arrival needed it too — a party that walks out of a warded location
must not leave its indicator lit — so it moved to its own module beside
``resonance_events.publish_resonance_changed``.

The payload is {active, scope_kind, scope_id, source} (veil_ward_scope_model.md §6). There is **no
raiser id**: a ward belongs to a scope, and its effects apply to every caster in that scope, so
every in-scope client lights its indicator. There is nothing for a client to filter itself out of.
RESONANCE_CHANGED keeps its ``caster_id`` filter because Resonance is per-caster — that asymmetry
is deliberate (§6, "Asymmetry, on purpose"). Do not "restore consistency" by adding one back here.

``active`` must be the party's RESOLVED warded state across all covering scopes, never read off the
scope the caller just mutated (§3). On combat end the encounter ward dies, but if a location ward
still covers the party this event carries active=True; a producer that keyed the flag to the
expiring scope would turn the ward light off while the party's casts are still being halved.

The signature enforces that structurally: callers hand over the ``(ward, scope)`` pair that
``ward_resolution.resolve_scope_ward_with_scope`` returned, not a bare boolean they computed
themselves.
"""

from event_types import VEIL_WARD_CHANGED
from game_events import publish_game_event
from session_data import SessionData
from veil_ward import WardScope


def veil_ward_payload(ward: dict | None, scope: WardScope | None) -> dict:
    """Build the VEIL_WARD_CHANGED wire payload from a resolved ``(ward, scope)`` pair.

    Pinned against ``packages/shared/fixtures/event_wire.json`` on both language lanes. An unwarded
    party names no scope — the descriptive keys are None rather than a stale scope the client could
    latch onto.
    """
    return {
        "active": ward is not None,
        "scope_kind": scope.kind if scope is not None else None,
        "scope_id": scope.id if scope is not None else None,
        "source": ward.get("source") if ward is not None else None,
    }


async def publish_veil_ward_changed(session: SessionData, ward: dict | None, scope: WardScope | None) -> None:
    """Push the party's resolved warded state to every in-scope client as VEIL_WARD_CHANGED.

    ``ward``/``scope`` are what ``resolve_scope_ward_with_scope`` returned — ``(None, None)`` when
    no scope wards the party.
    """
    await publish_game_event(session.room, VEIL_WARD_CHANGED, veil_ward_payload(ward, scope), session.event_bus)
