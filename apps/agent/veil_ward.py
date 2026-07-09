"""Veil Ward rules engine (story-002, M3.2) — pure, no IO.

A Veil Ward locally reinforces the Veil so a caster can push harder with less danger.
While a ward is active it halves the Resonance a cast generates (round down), grants
+4 to Hollow Echo rolls, and dampens spells by -1 damage die and -1 DC. Like the
Resonance and Hollow Echo engines this is a deterministic closed-table mechanic
(CLAUDE.md golden rule #3): the modifier values and the per-archetype ward-source
costs are code constants, not DB-loaded content (same call as resonance.py).

This module owns the ward's pure effects, its scope types, and its source table. The persisted
ward state lives in db_mutations_veil_ward (the veil_wards table) and on CombatState for the
encounter scope; ward_resolution.resolve_scope_ward is the one place the two are resolved.
The activation tool and the cast-time halving compose these primitives.

Spec source: docs/game_mechanics/game_mechanics_magic.md §Veil Ward (189-217):
generation halved (round down), +4 echo, -1 damage die, -1 DC; sources Cleric L7 4F /
Druid L9 5F (natural terrain only) / Paladin L10 3F+3S, plus Artificer item and Sacred
sites. M3.2 scopes WARD_SOURCES to the Focus/Stamina caster sources; the Artificer item
and Sacred-site passive sources are deferred.

M24/story-002 adds the duration model on top of that unchanged source table:
docs/game_mechanics/veil_ward_scope_model.md defines four incompatible duration units
(encounter / rounds / real-time / permanent), so ``WardDuration`` replaces a bare int.
Only scope/duration/ownership/sources change in M24 — the four effect constants and
``halve_generation`` above are byte-identical to their pre-M24 values.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

# Ward combat modifiers (spec 195-200), uniform across every ward source. Consumed by
# the cast path (story-004): generation is halved, the Hollow Echo roll gets +4, and
# spell damage/DC drop by one each while the ward is active.
WARD_ECHO_BONUS = 4
WARD_DAMAGE_DIE_PENALTY = -1
WARD_DC_PENALTY = -1


class WardScopeKind(StrEnum):
    """What a ward is attached to. Values are persisted verbatim in veil_wards.scope_kind."""

    ENCOUNTER = "encounter"  # keyed by combat_id; lives on CombatState, dies with the combat row
    LOCATION = "location"  # keyed by location_id; lives in the veil_wards table


@dataclass(frozen=True)
class WardScope:
    """The thing a ward belongs to — a place or a fight, never a person.

    A ward's effects apply to every caster in its scope, while Resonance and Hollow Echo stay
    per-caster (veil_ward_scope_model.md §1). Value semantics: two scopes naming the same place
    are the same scope, so this is a legal dict key and set member.

    ``kind`` participates in identity: encounter "x" and location "x" are different scopes.
    Note this pair is a LOOKUP key, not a ward's row identity — many wards may cover one scope
    (a 1-hour Artificer anchor coexists with a permanent Sacred site), so veil_wards is keyed
    by a surrogate ward_id and resolution is a boolean OR over covering rows (§3).
    """

    kind: WardScopeKind
    id: str

    def __post_init__(self):
        # An empty id would silently read and write the wrong rows. Fail at construction rather
        # than let a null session.location_id quietly resolve to "unwarded" forever.
        if not self.id:
            raise ValueError(f"{self.kind} scope requires a non-empty id, got {self.id!r}")

    @classmethod
    def location(cls, location_id: str) -> "WardScope":
        """The scope of a place — persisted in veil_wards, expiring lazily against NOW()."""
        return cls(WardScopeKind.LOCATION, location_id)

    @classmethod
    def encounter(cls, combat_id: str) -> "WardScope":
        """The scope of a fight — held on CombatState, never persisted in veil_wards."""
        return cls(WardScopeKind.ENCOUNTER, combat_id)


class WardDurationKind(StrEnum):
    """How a ward's lifetime is bounded (veil_ward_scope_model.md duration table)."""

    ENCOUNTER = "encounter"  # bounded by the fight; raised out of combat => until dismissed
    ROUNDS = "rounds"  # ticks at the combat WRAP beat; combat-only
    REAL_TIME = "real_time"  # absolute expires_at compared to NOW()
    PERMANENT = "permanent"  # expires_at IS NULL


@dataclass(frozen=True)
class WardDuration:
    """A ward source's lifetime rule. Exactly one of ``rounds``/``seconds`` is set, and only
    for the matching ``kind`` — ``__post_init__`` fails loud on any mismatch.
    """

    kind: WardDurationKind
    rounds: int | None = None  # required iff kind is ROUNDS, must be > 0
    seconds: int | None = None  # required iff kind is REAL_TIME, must be > 0

    def __post_init__(self):
        if self.kind == WardDurationKind.ROUNDS:
            if self.rounds is None or self.rounds <= 0:
                raise ValueError(f"ROUNDS duration requires rounds > 0, got {self.rounds}")
            if self.seconds is not None:
                raise ValueError("ROUNDS duration must not carry seconds")
        elif self.kind == WardDurationKind.REAL_TIME:
            if self.seconds is None or self.seconds <= 0:
                raise ValueError(f"REAL_TIME duration requires seconds > 0, got {self.seconds}")
            if self.rounds is not None:
                raise ValueError("REAL_TIME duration must not carry rounds")
        else:
            if self.rounds is not None or self.seconds is not None:
                raise ValueError(f"{self.kind} duration must not carry rounds or seconds")


@dataclass(frozen=True)
class WardSource:
    """The level + resource cost at which an archetype can raise a Veil Ward, plus its
    duration rule and whether the DM activation tool may raise it (story-005 gates on
    ``tool_raisable``; this story only carries the flag, always True for the three
    caster sources below).
    """

    min_level: int
    duration: WardDuration
    focus: int
    stamina: int = 0
    tool_raisable: bool = False


# Archetype id -> ward source (spec 204-210). Only the enforceable cost fields are
# modeled: Druid's "natural terrain only" restriction is NOT a column because no runtime
# location->terrain map exists yet (an unenforced flag would be forward-wired dead state).
# story-003 gates level + Focus/Stamina from this table; the Druid terrain gate and the
# Artificer-item / Sacred-site (passive world entity) sources are deferred past M3.2, and
# story-005 adds their keys once the tool re-gates on ``tool_raisable`` — do not add them
# here (an artificer key would let a free-cost ward through the DM tool untended).
WARD_SOURCES: dict[str, WardSource] = {
    "cleric": WardSource(min_level=7, focus=4, duration=WardDuration(WardDurationKind.ENCOUNTER), tool_raisable=True),
    "druid": WardSource(min_level=9, focus=5, duration=WardDuration(WardDurationKind.ENCOUNTER), tool_raisable=True),
    "paladin": WardSource(
        min_level=10,
        focus=3,
        stamina=3,
        duration=WardDuration(WardDurationKind.ROUNDS, rounds=3),
        tool_raisable=True,
    ),
}


def halve_generation(generated: int) -> int:
    """Halve the Resonance a cast generates while a Veil Ward is active (round down, spec 197).

    Fails loud on a negative input — generation is always non-negative (cantrips are 0).
    """
    if generated < 0:
        raise ValueError(f"generated must be non-negative, got {generated}")
    return generated // 2


def tick_ward_rounds(rounds_remaining: int | None) -> int | None:
    """Advance a ROUNDS-duration ward one combat WRAP beat, floored at 0.

    ``None`` means no round clock (ENCOUNTER/REAL_TIME/PERMANENT wards never expire by
    rounds) and passes through unchanged, mirroring ``conditions.tick_conditions``.
    """
    if rounds_remaining is None:
        return None
    if rounds_remaining < 0:
        raise ValueError(f"rounds_remaining must be non-negative, got {rounds_remaining}")
    return max(0, rounds_remaining - 1)


def ward_rounds_expired(rounds_remaining: int | None) -> bool:
    """Whether a ROUNDS-duration ward has run out. ``None`` (no round clock) never expires."""
    if rounds_remaining is None:
        return False
    return rounds_remaining <= 0


def location_expires_at(duration: WardDuration, now: datetime) -> datetime | None:
    """Compute a location-owned ward's absolute expiry from its source duration.

    PERMANENT and ENCOUNTER wards have no absolute expiry (ENCOUNTER raised outside combat
    lasts until dismissed) so both return ``None``. REAL_TIME wards expire ``seconds`` after
    ``now``. ROUNDS is combat-only and has no absolute clock — a location-owned ward can
    never carry it, so this raises rather than silently producing a nonsensical answer.
    """
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    if duration.kind == WardDurationKind.ROUNDS:
        raise ValueError("ROUNDS duration has no absolute expiry; it is combat-only")
    if duration.kind == WardDurationKind.REAL_TIME:
        assert duration.seconds is not None  # guaranteed by WardDuration.__post_init__
        return now + timedelta(seconds=duration.seconds)
    return None


def location_ward_expired(expires_at: datetime | None, now: datetime) -> bool:
    """Whether a location-owned ward's absolute expiry has passed. ``None`` never expires."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    if expires_at is not None and expires_at.tzinfo is None:
        raise ValueError("expires_at must be timezone-aware")
    if expires_at is None:
        return False
    return expires_at <= now
