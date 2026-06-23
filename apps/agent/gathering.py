"""Gathering & resource-discovery resolution — pure engine (M4.6c / story-001). Zero IO, zero RNG.

Turns a gathering attempt — a material category, the character's skill tier, the region's
gathering DC, a caller-supplied skill roll, and the region's rarity-keyed resource table — into
a gathering outcome: a result tier (rich_find / success / partial / nothing), the harvested
materials drawn from the table, the time the attempt costs, a discovery flag for a rare/rich
find, a dramatic-dice verdict (routed through the M4.5 dramatic.py SSOT), and a narration cue.
The caller rolls the d20 + skill modifier and supplies `roll_total`; this module never touches
RNG, the DB, or world state, mirroring travel.py and social_resolution.py.

`material_type` drives skill routing (which check the caller should have rolled) and narration;
within a rarity bucket it does not further filter — per-category filtering is a later refinement.
The harvested `materials` are a RAW multiset (rich_find lists a material id twice); the apply
site (story-003's gathering tool) sums them into inventory. This module never touches inventory.

Spec: docs/game_mechanics/game_mechanics_combat.md §Gathering During Travel (L977-1060).
"""

from dataclasses import dataclass

from dramatic import DramaticContext, evaluate_dramatic_context

# Material category -> gating skill (spec L979-988). `None` is general foraging -> survival
# (spec L987). Categories mirror the spec's worked example branches.
GATHERING_SKILLS: dict[str, str] = {
    "metals": "survival",
    "stone": "survival",
    "gems": "survival",
    "wood": "nature",
    "plant": "nature",
    "herbs": "nature",
    "arcane_components": "arcana",
}

_DEFAULT_FORAGE_SKILL = "survival"


def gathering_skill(material_type: str | None) -> str:
    """Return the gating skill for a `material_type`. `None` -> general foraging (survival).
    Fail loud off-catalog — an unknown category is a caller bug, not a default, mirroring
    travel.travel_mode_params."""
    if material_type is None:
        return _DEFAULT_FORAGE_SKILL
    try:
        return GATHERING_SKILLS[material_type]
    except KeyError:
        raise ValueError(
            f"unknown material type {material_type!r}; expected one of {tuple(GATHERING_SKILLS)} or None"
        ) from None


# Rarity buckets in ascending order — the canonical rarity vocabulary (public SSOT). Material
# selection walks this; content conformance validates resource_table keys against it.
RARITY_ORDER: tuple[str, ...] = ("common", "uncommon", "rare")


# Which rarities a skill tier can even attempt to gather (spec L1018-1022). Untrained is common
# only; each tier unlocks the next bucket; expert and master both reach rare (master's edge is the
# rich-find threshold + always-find floor, handled in the result-tier logic, not access).
ACCESSIBLE_RARITIES: dict[str, tuple[str, ...]] = {
    "untrained": ("common",),
    "trained": ("common", "uncommon"),
    "expert": ("common", "uncommon", "rare"),
    "master": ("common", "uncommon", "rare"),
}


def accessible_rarities(skill_tier: str) -> tuple[str, ...]:
    """Return the rarity buckets a `skill_tier` may gather from. Fail loud off-catalog — an
    unknown tier is a caller bug."""
    try:
        return ACCESSIBLE_RARITIES[skill_tier]
    except KeyError:
        raise ValueError(f"unknown skill tier {skill_tier!r}; expected one of {tuple(ACCESSIBLE_RARITIES)}") from None


# Result-tier thresholds (spec L997-1006). rich_find at dc+10 (dc+5 for a master, spec L1022),
# success at dc, partial at dc-5, else nothing. A master never comes up empty (spec L1021).
RICH_FIND_MARGIN = 10
MASTER_RICH_FIND_MARGIN = 5
PARTIAL_MARGIN = 5


def gathering_result_tier(roll_total: int, dc: int, *, master: bool) -> str:
    """Classify a gathering roll into a result tier. Master lowers the rich-find threshold by 5
    and floors the worst outcome at `partial` ("always find something")."""
    rich_margin = MASTER_RICH_FIND_MARGIN if master else RICH_FIND_MARGIN
    if roll_total >= dc + rich_margin:
        return "rich_find"
    if roll_total >= dc:
        return "success"
    if roll_total >= dc - PARTIAL_MARGIN or master:
        return "partial"
    return "nothing"


# Quantity a result tier harvests: rich_find doubles (spec L999), partial/success single, nothing
# none. Expressed as a count of the chosen material id in the returned multiset.
_QUANTITY_BY_RESULT: dict[str, int] = {"nothing": 0, "partial": 1, "success": 1, "rich_find": 2}

# A partial find downgrades to the common bucket (spec L1003: a common material instead of the
# uncommon one you wanted). success/rich_find take the best accessible, non-empty bucket.
_PARTIAL_RARITY = "common"


def select_materials(
    resource_table: dict[str, tuple[str, ...]],
    result: str,
    skill_tier: str,
) -> tuple[str, ...]:
    """Pick harvested material ids from a rarity-keyed `resource_table` for a `result` tier.

    Deterministic (no RNG, stays pure): walk the accessible rarity buckets from the result tier's
    ceiling downward and take the first non-empty bucket's first material id, repeated by the
    tier's quantity. `nothing` -> (). `partial` downgrades to the common bucket. Returns () when no
    accessible bucket holds a material (a region with nothing in range). Selection does not filter
    within a bucket by category — per-category filtering is a later refinement (see module docstring).
    """
    quantity = _QUANTITY_BY_RESULT[result]
    if quantity == 0:
        return ()

    accessible = accessible_rarities(skill_tier)
    if result == "partial":
        candidates: tuple[str, ...] = (_PARTIAL_RARITY,) if _PARTIAL_RARITY in accessible else ()
    else:
        # Best accessible bucket first: highest rarity the tier can reach, walking down.
        candidates = tuple(r for r in reversed(RARITY_ORDER) if r in accessible)

    for rarity in candidates:
        bucket = resource_table.get(rarity, ())
        if bucket:
            return (bucket[0],) * quantity
    return ()


# Time cost per result tier in hours (spec L1010: 30 min to 2 hours). Fixed representative values
# keep the resolver pure (no RNG), mirroring travel's fixed time penalties — even a wholly-failed
# forage costs the spec's 30-minute floor.
_TIME_COST_BY_RESULT: dict[str, float] = {"nothing": 0.5, "partial": 1.0, "success": 1.0, "rich_find": 2.0}


# Narration cue by gathering outcome (a short qualitative word the DM voices, not a number).
_CUE_BY_RESULT: dict[str, str] = {
    "nothing": "empty-handed",
    "partial": "lean pickings",
    "success": "good haul",
    "rich_find": "rich find",
}


@dataclass(frozen=True)
class GatheringResult:
    """Outcome of one gathering attempt. `dramatic`/`context` come from the M4.5 SSOT; `materials`
    is a RAW multiset the apply site sums into inventory; `discovery` flags a rare/rich find worth
    a discovery narrative beat."""

    result: str
    materials: tuple[str, ...]
    dc: int
    margin: int
    discovery: bool
    dramatic: bool
    context: str
    time_cost: float
    narrative_cue: str


def resolve_gathering(
    *,
    material_type: str | None,
    skill_tier: str,
    gathering_dc: int,
    roll_total: int,
    resource_table: dict[str, tuple[str, ...]],
    raw_die: int | None = None,
) -> GatheringResult:
    """Resolve one gathering attempt (spec L989-1010). Pure: the caller supplies `roll_total`
    (d20 + the gating skill's modifier) and the region's `gathering_dc` and `resource_table`.

    The roll's margin over the DC sets the result tier (rich_find / success / partial / nothing);
    the tier plus the character's `skill_tier` selects materials from the rarity-keyed table. A
    `rich_find` flags `discovery` for a discovery beat. The dramatic verdict and its label are
    delegated to dramatic.evaluate_dramatic_context (M4.5 SSOT) via the margin and the optional
    `raw_die` — gathering is not inherently dramatic. Raises ValueError for an unknown
    `material_type` or `skill_tier`.
    """
    gathering_skill(material_type)  # validate the category up front (fail loud)
    master = skill_tier == "master"
    margin = roll_total - gathering_dc
    result = gathering_result_tier(roll_total, gathering_dc, master=master)
    materials = select_materials(resource_table, result, skill_tier)

    verdict = evaluate_dramatic_context(DramaticContext(margin=margin, raw_die=raw_die))
    return GatheringResult(
        result=result,
        materials=materials,
        dc=gathering_dc,
        margin=margin,
        discovery=result == "rich_find",
        dramatic=verdict.dramatic,
        context=verdict.context,
        time_cost=_TIME_COST_BY_RESULT[result],
        narrative_cue=_CUE_BY_RESULT[result],
    )
