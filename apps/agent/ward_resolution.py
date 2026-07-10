"""The one place Veil Ward resolution lives (story-004, M24).

``veil_ward_scope_model.md`` §3 defines a covering-scope OR:

    is_warded(caster) := encounter_ward_active(session.combat_state)
                         or location_ward_active(session.location_id)

and then warns, in the same breath, why it must not be re-derived at each call site:

    "Producers must compute ``active`` from ``is_warded``, not from the scope they just mutated."

A consumer that keys its answer to one scope turns the ward light off — or halves nothing —
while another covering scope still wards the party. That is the same class of silent lie this
milestone exists to remove, rebuilt one layer up. So every consumer that must answer "is the
party warded" — the cast path (``spell_casting``), arrival (``movement_tools``), and the
activation tool (``veil_ward_tools``) — calls ``resolve_scope_ward``. None re-derives it.

``veil_ward_tools`` joined them in story-005, when the tool gained encounter-vs-location
targeting: from that point a raise can land on a scope the party is not actually resolved
against. Its "a Veil Ward is already active" gate therefore asks whether the PARTY is warded,
not whether the scope it is about to write is — a party fighting on a Sacred site is already
covered, and charging them for an encounter ward that halves nothing twice would be that same
lie. It still names its own scope for the WRITE (raise inserts there, dismiss deletes there);
only the question "is anything covering us?" routes through here.

**This is the cast path's authority, and it reads the database.** The in-memory
``SessionData.location_ward`` is a HUD mirror with no correctness consumer: it cannot see a
ward whose ``expires_at`` lapsed mid-session, because expiry is lazy (nothing sweeps
``veil_wards``; a read simply does not return an expired row — §"Durations need no world
clock"). Querying per cast is what makes that model true rather than merely stated. It costs one
indexed lookup on ``(scope_kind, scope_id)``, inside the caller's existing transaction, and it
honors golden rule #4: the DB is the source of truth, and the DM agent queries it every turn.

The encounter scope is checked first: it lives on ``CombatState`` (in ``combat_instances.data``),
so resolving it is free, and ward effects do not stack — the first covering scope wins.
"""

import asyncpg

import db_mutations_veil_ward
from session_data import SessionData
from veil_ward import WardScope


async def resolve_scope_ward_with_scope(
    session: SessionData,
    *,
    conn: asyncpg.Connection | asyncpg.Pool,
    location_id: str | None = None,
    ward_mutations_mod=db_mutations_veil_ward,
) -> tuple[dict | None, WardScope | None]:
    """Return ``(ward, scope)`` for the ward covering ``session``, or ``(None, None)``.

    The same covering-scope OR as ``resolve_scope_ward``, but it also names WHICH scope answered.
    VEIL_WARD_CHANGED carries ``scope_kind``/``scope_id`` (§6), and a producer that re-derived
    them would be re-deriving resolution — the exact duplication this module exists to prevent.
    An unwarded party has no scope to name, hence ``(None, None)`` rather than a bare scope.

    See ``resolve_scope_ward`` for the ``location_id`` override and the transaction contract.
    """
    combat = session.combat_state
    if combat is not None and combat.veil_ward is not None:
        return combat.veil_ward, WardScope.encounter(combat.combat_id)
    scope = WardScope.location(location_id or session.location_id)
    ward = await ward_mutations_mod.read_active_ward(scope, conn=conn)
    return (ward, scope) if ward is not None else (None, None)


async def resolve_scope_ward(
    session: SessionData,
    *,
    conn: asyncpg.Connection | asyncpg.Pool,
    location_id: str | None = None,
    ward_mutations_mod=db_mutations_veil_ward,
) -> dict | None:
    """Return the ward covering ``session``, or None when no scope wards it.

    None means "no ward" — never a default-inactive placeholder, so a caller cannot confuse the
    absence of a ward with an inactive one.

    ``location_id`` overrides ``session.location_id``. Arrival needs it: the ward for the
    DESTINATION must be resolved from inside ``apply_arrival``'s transaction, which commits
    before ``session.location_id`` is updated. An empty location fails loud via ``WardScope``
    rather than silently reading the wrong rows.

    Joins the caller's transaction through ``conn``; it never opens its own.

    Delegates to ``resolve_scope_ward_with_scope`` and drops the scope, so the covering-scope OR
    exists in exactly one place.
    """
    ward, _scope = await resolve_scope_ward_with_scope(
        session, conn=conn, location_id=location_id, ward_mutations_mod=ward_mutations_mod
    )
    return ward
