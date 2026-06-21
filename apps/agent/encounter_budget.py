"""Pure encounter-budget validator — the composition checker for the role overlay (M4.7, story-004).

Given a list of role-tagged enemies and the player's level, this reports the encounter's
*budget cost* (the sum of each role's ``budget_cost`` weight, with Minions at 0.5 and Named
ignored) against the difficulty thresholds for the player's level band, and flags the three
allocation-rule violations the DM should know about.

It is INFORMATIONAL, not gating: it returns a report and never blocks combat. There is no
encounter-builder to integrate with — this is a standalone validator the DM (or future
builder) can consult. It is pure: it reads only its arguments, never touches IO/RNG/DB.

Numbers + rules come from docs/game_mechanics/game_mechanics_encounter_roles.md:
- Budget point costs per role (L209-215) — sourced from ``ROLE_MODIFIERS.budget_cost``.
- Difficulty-budget thresholds by level band (L221-227).
- Allocation rules (L229-234): max one Boss (D80), Minions need a non-Minion anchor, Named
  ignores budget (D81).
"""

from encounter_roles import ROLE_MODIFIERS, EncounterRole

# Difficulty-budget thresholds by player-level band (doc L221-227). Each band maps to the
# standard / tough / boss-encounter budget ceilings. The boss column is the absolute ceiling:
# a composition costing more than it is flagged over_budget.
_LEVEL_BANDS: list[tuple[int, int, str, dict[str, float]]] = [
    (1, 2, "1-2", {"standard": 2.0, "tough": 3.0, "boss": 4.0}),
    (3, 4, "3-4", {"standard": 3.0, "tough": 4.5, "boss": 5.0}),
    (5, 8, "5-8", {"standard": 4.0, "tough": 6.0, "boss": 7.0}),
    (9, 14, "9-14", {"standard": 5.0, "tough": 7.5, "boss": 9.0}),
    (15, 20, "15-20", {"standard": 6.0, "tough": 9.0, "boss": 11.0}),
]


def _band_for_level(player_level: int) -> tuple[str, dict[str, float]]:
    """Return the (band label, thresholds) row for a level, failing loud off the 1-20 table."""
    for low, high, label, thresholds in _LEVEL_BANDS:
        if low <= player_level <= high:
            return label, thresholds
    raise ValueError(f"player_level {player_level} is outside the supported range 1-20")


def _budget_cost(role: str) -> float:
    """The budget weight of one enemy. Named carries no cost (D81); other roles read the
    canonical ``ROLE_MODIFIERS.budget_cost``. Unknown roles fail loud."""
    if role == EncounterRole.NAMED:
        return 0.0
    mod = ROLE_MODIFIERS.get(role)
    if mod is None:
        valid = sorted(r.value for r in EncounterRole)
        raise ValueError(f"Unknown encounter role {role!r}; valid roles are {valid}")
    return mod.budget_cost


def calculate_encounter_budget(enemies: list[dict], player_level: int) -> dict:
    """Score a role-tagged enemy list against the level band's difficulty budget.

    Each enemy dict supplies a ``role`` (an ``EncounterRole`` value). Returns a report:
    ``total`` (summed budget cost, Minions 0.5, Named 0), ``player_level``, ``level_band``,
    ``thresholds`` (the band's standard/tough/boss ceilings), and three violation flags —
    ``too_many_bosses`` (>1 Boss), ``all_minion`` (Minions present with no non-Minion anchor),
    and ``over_budget`` (total above the boss-encounter ceiling). Purely informational; the
    caller decides what to do with a flag.
    """
    band, thresholds = _band_for_level(player_level)
    roles = [enemy["role"] for enemy in enemies]

    total = sum(_budget_cost(role) for role in roles)
    boss_count = sum(1 for role in roles if role == EncounterRole.BOSS)
    minion_count = sum(1 for role in roles if role == EncounterRole.MINION)

    return {
        "total": total,
        "player_level": player_level,
        "level_band": band,
        "thresholds": thresholds,
        "too_many_bosses": boss_count > 1,
        # Minions present, but no enemy of any other role to anchor the fight (D-rule 2). A
        # Named anchors even though it carries no budget cost.
        "all_minion": minion_count > 0 and minion_count == len(roles),
        "over_budget": total > thresholds["boss"],
    }
