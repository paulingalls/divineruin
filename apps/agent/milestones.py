"""Archetype milestones — DB-loaded content config (M2.3).

content/archetype_milestones.json is the single source of truth for every
archetype's four-tier milestone progression: the Identity (L5) specialization
fork and the Power (L10) / Mastery (L15) / Legend (L20) auto-grants. This module
is the Python loader, an exact mirror of abilities.py (M2.2): a module-global
dict populated by load_milestones() at process startup (or set_milestones() in
tests), a fail-loud parse_milestone_row shared by the DB loader and the JSON test
fixture, and sync accessors.

Records are self-contained (decision 4c0677dae1be): each embeds its granted
ability text directly and does NOT FK into archetype_abilities — milestone grants
are passive combat flags / markers, not the activatables that table holds. The
resolve_milestone tool (story-004) consumes get_milestone / get_archetype_milestones
and persists the chosen specialization + grant markers in players.data.
"""

import json
import logging
from dataclasses import dataclass
from typing import Literal, get_args

logger = logging.getLogger("divineruin.milestones")

MilestoneTier = Literal["identity", "power", "mastery", "legend"]
MilestoneKind = Literal["specialization_fork", "auto_grant"]

# Closed vocabularies — the loader owns fail-loud validation, mirroring
# abilities.parse_ability_row's ability_type check.
_TIERS = frozenset(get_args(MilestoneTier))
_KINDS = frozenset(get_args(MilestoneKind))


@dataclass(frozen=True)
class SpecializationOption:
    id: str
    name: str
    description: str


@dataclass(frozen=True)
class Grant:
    name: str
    effect: str
    flag: str | None  # combat-math marker (e.g. extra_attack) set in players.data; null if narrative-only


@dataclass(frozen=True)
class Milestone:
    id: str
    archetype_id: str
    tier: MilestoneTier
    level: int
    kind: MilestoneKind
    patron_deferred: bool
    specialization_options: tuple[SpecializationOption, ...]
    grant: Grant | None
    narration_cue: str


# Module-level runtime-loaded milestones, keyed by milestone id. Populated by
# load_milestones() at startup, or by set_milestones() in tests.
_milestones: dict[str, Milestone] = {}


def _parse_options(raw: object, ctx: str) -> tuple[SpecializationOption, ...]:
    if not isinstance(raw, list):
        raise ValueError(f"{ctx} is not a list")
    out: list[SpecializationOption] = []
    for i, opt in enumerate(raw):
        if not isinstance(opt, dict):
            raise ValueError(f"{ctx}[{i}] is not an object")
        out.append(SpecializationOption(id=opt["id"], name=opt["name"], description=opt["description"]))
    return tuple(out)


def _parse_grant(raw: object, ctx: str) -> Grant | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError(f"{ctx} is not an object")
    flag = raw["flag"]
    if flag is not None and not isinstance(flag, str):
        raise ValueError(f"{ctx}.flag is not a string or null")
    return Grant(name=raw["name"], effect=raw["effect"], flag=flag)


def parse_milestone_row(milestone_id: str, data: dict) -> Milestone:
    """Parse a raw dict (from JSON file or DB JSONB) into a Milestone.

    Shared by load_milestones (DB) and tests/archetype_milestones_config_fixture
    (JSON). Raises ValueError wrapping the underlying error with the row id for
    context; owns fail-loud validation of the tier/kind enums and the option/grant
    shapes. Full content invariants (2-option forks, patron set, tier<->level) are
    owned by story-001's content test, not duplicated here.
    """
    try:
        tier = data["tier"]
        if tier not in _TIERS:
            raise ValueError(f"milestone {milestone_id!r} tier {tier!r} not in {sorted(_TIERS)}")
        kind = data["kind"]
        if kind not in _KINDS:
            raise ValueError(f"milestone {milestone_id!r} kind {kind!r} not in {sorted(_KINDS)}")
        level = data["level"]
        # bool is a subclass of int — exclude it explicitly, mirroring abilities._parse_cost.
        if not isinstance(level, int) or isinstance(level, bool):
            raise ValueError(f"milestone {milestone_id!r} level is not an int")
        return Milestone(
            id=milestone_id,
            archetype_id=data["archetype_id"],
            tier=tier,
            level=level,
            kind=kind,
            patron_deferred=data["patron_deferred"],
            specialization_options=_parse_options(
                data["specialization_options"], f"{milestone_id}.specialization_options"
            ),
            grant=_parse_grant(data["grant"], f"{milestone_id}.grant"),
            narration_cue=data["narration_cue"],
        )
    except (KeyError, TypeError) as e:
        raise ValueError(f"Malformed archetype_milestones row {milestone_id!r}: {e}") from e


def set_milestones(config: dict[str, Milestone]) -> None:
    """Test seam: populate _milestones directly without going through the DB."""
    _milestones.clear()
    _milestones.update(config)


def get_milestone(milestone_id: str) -> Milestone:
    """Return the milestone for an id. Raises ValueError if not loaded/unknown."""
    if milestone_id not in _milestones:
        raise ValueError(f"Unknown milestone: {milestone_id!r}")
    return _milestones[milestone_id]


def get_archetype_milestones(archetype_id: str) -> tuple[Milestone, ...]:
    """Return all loaded milestones for an archetype, in load order.

    Empty tuple when the archetype has none loaded (e.g. an unknown id). Callers
    filter by level (e.g. the L5 specialization fork vs the L10/15/20 auto-grants).
    """
    return tuple(m for m in _milestones.values() if m.archetype_id == archetype_id)


def is_loaded() -> bool:
    """True once the milestones have been populated (startup load or test seam)."""
    return bool(_milestones)


async def load_milestones() -> None:
    """Load the archetype milestones from the DB into _milestones.

    Called from agent.py (dm_session, guarded) and async_worker.py startup. Fails
    loud if the query or a row errors. Builds a local dict then swaps in one
    synchronous step (no await between), so a malformed row fails loud WITHOUT
    wiping an already-loaded map and a concurrent get_milestone never observes a
    half-populated map.
    """
    import db

    pool = await db.get_pool()
    rows = await pool.fetch("SELECT id, data FROM archetype_milestones")
    loaded: dict[str, Milestone] = {}
    for row in rows:
        data = json.loads(row["data"]) if isinstance(row["data"], str) else row["data"]
        loaded[row["id"]] = parse_milestone_row(row["id"], data)
    _milestones.clear()
    _milestones.update(loaded)
    logger.info("Loaded %d archetype milestones", len(_milestones))
