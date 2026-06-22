"""Travel & exploration resolution — pure engine (M4.6b / story-001). Zero IO, zero RNG.

Turns a travel mode plus a terrain and a caller-supplied navigation roll into a travel
outcome: a navigation success/failure (DC by terrain), the time the segment costs, whether
the party got lost (wrong_area), an exhaustion delta (forced march + a bad lost-failure), the
mode's encounter rate and foraging availability, a dramatic-dice verdict (routed through the
M4.5 dramatic.py SSOT), and a narration cue. The caller rolls the d20 + Survival modifier and
supplies `roll_total`; this module never touches RNG, the DB, or world state, mirroring
social_resolution.py.

The returned `exhaustion_delta` is RAW — the apply site (story-003's travel tool) clamps it to
the character's Exhausted cap via rules_engine.exhaustion_stack_cap. This module never clamps.

Travel modes follow the game-mechanics spec (Compressed / Scenic / Dangerous), not the
milestone's stale Fast/Normal/Careful labels.

Spec: docs/game_mechanics/game_mechanics_combat.md §Travel and Exploration (L852-969).
"""

from dataclasses import dataclass

from dramatic import DramaticContext, evaluate_dramatic_context


@dataclass(frozen=True)
class TravelModeParams:
    """Per-mode travel parameters (spec L852-860). `time_multiplier` scales the segment's base
    travel time (montage < narrated < full gameplay); `encounter_rate` is the base per-segment
    chance the tool rolls against; `foraging_available` gates gathering nearby (spec L960)."""

    time_multiplier: float
    encounter_rate: float
    foraging_available: bool


# Travel modes (spec L856-860). Magnitudes are named constants — the spec pins the relative
# ordering (Compressed montage -> Scenic narrated -> Dangerous full gameplay) and the per-route
# encounter_frequency lives in world data (spec L887), so these are the mode's base contribution.
TRAVEL_MODES: dict[str, TravelModeParams] = {
    "compressed": TravelModeParams(time_multiplier=0.5, encounter_rate=0.0, foraging_available=False),
    "scenic": TravelModeParams(time_multiplier=1.0, encounter_rate=0.25, foraging_available=True),
    "dangerous": TravelModeParams(time_multiplier=1.5, encounter_rate=0.5, foraging_available=True),
}

TRAVEL_MODE_NAMES: tuple[str, ...] = tuple(TRAVEL_MODES)


def travel_mode_params(mode: str) -> TravelModeParams:
    """Return the parameters for a travel `mode`. Fail loud off-catalog — an unknown mode is a
    caller bug, not a default, mirroring social_resolution.social_dc_modifier."""
    try:
        return TRAVEL_MODES[mode]
    except KeyError:
        raise ValueError(f"unknown travel mode {mode!r}; expected one of {TRAVEL_MODE_NAMES}") from None


# Navigation DC by terrain (spec L922-929). `established_road` is auto-success (no roll). The
# rest are rolled against; navigation only matters in wilderness/underground/corrupted terrain.
NAVIGATION_DC: dict[str, int | None] = {
    "established_road": None,
    "known_trail": 8,
    "unmarked_wilderness": 12,
    "dense_forest": 14,
    "underground": 16,
    "hollow_corrupted": 18,
}


def navigation_dc(terrain: str) -> int | None:
    """Return the navigation DC for `terrain`, or None for auto-success (established road).
    Fail loud off-catalog — an unknown terrain is a content/caller bug."""
    try:
        return NAVIGATION_DC[terrain]
    except KeyError:
        raise ValueError(f"unknown terrain {terrain!r}; expected one of {tuple(NAVIGATION_DC)}") from None


@dataclass(frozen=True)
class _TerrainFailure:
    """The consequence of a failed navigation check in a given terrain (spec L922-929):
    extra travel time, whether the party is genuinely lost (wrong_area) vs a minor detour,
    and whether being lost costs an exhaustion stack (rations spent / corruption exposure)."""

    time_penalty: float
    wrong_area: bool
    exhausts: bool


# Failure consequences by terrain (spec L925-929). A known-trail miss is a minor detour (not
# lost); unmarked/forest are lost; underground (exhaust a ration) and hollow-corrupted (drawn
# toward corruption / Hollowed exposure) are lost AND cost an exhaustion stack. Time penalties
# use a fixed representative value of the spec's ranges so the resolver stays pure (no RNG).
_NAV_FAILURE: dict[str, _TerrainFailure] = {
    "known_trail": _TerrainFailure(time_penalty=2.0, wrong_area=False, exhausts=False),
    "unmarked_wilderness": _TerrainFailure(time_penalty=4.0, wrong_area=True, exhausts=False),
    "dense_forest": _TerrainFailure(time_penalty=2.0, wrong_area=True, exhausts=False),
    "underground": _TerrainFailure(time_penalty=4.0, wrong_area=True, exhausts=True),
    "hollow_corrupted": _TerrainFailure(time_penalty=4.0, wrong_area=True, exhausts=True),
}


# Forced march: travel beyond 8 hours in a day adds 1 Exhaustion stack per additional 4 hours
# (spec L944). Threshold and interval are spec constants.
_FORCED_MARCH_THRESHOLD_HOURS = 8
_FORCED_MARCH_STACK_INTERVAL = 4


def forced_march_exhaustion(hours: int) -> int:
    """Exhaustion stacks from a forced march of `hours` (spec L944): 0 at or under the 8-hour
    threshold, then 1 per full additional 4-hour block. Returns a non-negative int."""
    over = hours - _FORCED_MARCH_THRESHOLD_HOURS
    if over <= 0:
        return 0
    return over // _FORCED_MARCH_STACK_INTERVAL


# Narration cue by travel outcome (a short qualitative word the DM voices, not a number).
_CUE_UNEVENTFUL = "uneventful"  # established road, no navigation
_CUE_ON_COURSE = "on course"  # navigation succeeded
_CUE_DETOUR = "minor detour"  # failed, but only a known-trail detour
_CUE_LOST = "lost"  # failed and genuinely off course


@dataclass(frozen=True)
class TravelResult:
    """Outcome of one travel segment. `dramatic`/`context` come from the M4.5 SSOT; `dc`/`margin`
    are None on an auto-success (established road, no roll). `exhaustion_delta` is RAW — the apply
    site clamps it. `wrong_area` means the party is genuinely lost (vs a minor detour)."""

    success: bool
    dc: int | None
    margin: int | None
    dramatic: bool
    context: str
    time_cost: float
    exhaustion_delta: int
    encounter_rate: float
    foraging_available: bool
    wrong_area: bool
    narrative_cue: str


def resolve_travel_segment(
    *,
    mode: str,
    terrain: str,
    roll_total: int = 0,
    base_hours: int = 4,
    forced_march: bool = False,
    raw_die: int | None = None,
) -> TravelResult:
    """Resolve one travel segment (spec L852-951). Pure: the caller supplies `roll_total`
    (d20 + Survival modifier) and the segment's `base_hours`; the mode scales time and carries
    the encounter/foraging signals, the terrain sets the navigation DC.

    `established_road` (DC None) auto-succeeds with no roll and no chance of getting lost. Other
    terrain rolls `roll_total` against the terrain DC: a miss costs extra time, marks `wrong_area`
    when the party is genuinely lost, and may add an exhaustion stack (underground/corrupted).
    `forced_march` adds forced-march exhaustion from `base_hours` (spec L944). The dramatic verdict
    and its label are delegated to dramatic.evaluate_dramatic_context (M4.5 SSOT) via the margin
    and the optional `raw_die` — travel is not inherently dramatic. Raises ValueError for an
    unknown mode or terrain.
    """
    params = travel_mode_params(mode)
    dc = navigation_dc(terrain)  # None => auto-success (established road)

    # Defaults shared by the auto-success and rolled branches; a rolled failure mutates them below.
    time_cost = base_hours * params.time_multiplier
    wrong_area = False
    exhaustion_delta = forced_march_exhaustion(base_hours) if forced_march else 0

    if dc is None:
        margin: int | None = None
        success = True
        cue = _CUE_UNEVENTFUL
    else:
        margin = roll_total - dc
        success = roll_total >= dc
        if success:
            cue = _CUE_ON_COURSE
        else:
            failure = _NAV_FAILURE[terrain]
            time_cost += failure.time_penalty
            wrong_area = failure.wrong_area
            if failure.exhausts:
                exhaustion_delta += 1
            cue = _CUE_LOST if failure.wrong_area else _CUE_DETOUR

    verdict = evaluate_dramatic_context(DramaticContext(margin=margin, raw_die=raw_die))
    return TravelResult(
        success=success,
        dc=dc,
        margin=margin,
        dramatic=verdict.dramatic,
        context=verdict.context,
        time_cost=time_cost,
        exhaustion_delta=exhaustion_delta,
        encounter_rate=params.encounter_rate,
        foraging_available=params.foraging_available,
        wrong_area=wrong_area,
        narrative_cue=cue,
    )
