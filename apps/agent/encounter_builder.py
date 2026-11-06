"""Pure, seeded encounter composition from an explicitly supplied creature catalog."""

from functools import lru_cache
from math import ceil, floor
from random import Random

from encounter_budget import calculate_encounter_budget
from encounter_roles import ROLE_MODIFIERS, derive_role_stats

SOLO_PARTY_BASELINE = 1.75
# Authored reference progression; derivation in the bestiary's Encounter Building Guidelines.
EXPECTED_PLAYER_DAMAGE_PER_ROUND = {
    1: 6.31,
    2: 6.4,
    3: 6.83,
    4: 7.6,
    5: 9.02,
    6: 9.11,
    7: 9.59,
    8: 10.39,
    9: 11.47,
    10: 13.07,
    11: 13.38,
    12: 13.79,
    13: 13.83,
    14: 14.62,
    15: 14.27,
    16: 14.31,
    17: 14.6,
    18: 14.82,
    19: 15.03,
    20: 15.1,
}

ROUND_WINDOWS = {"standard": (3, 5), "tough": (4, 6), "boss": (5, 7)}


def _player_damage(level: int) -> float:
    return EXPECTED_PLAYER_DAMAGE_PER_ROUND[level]


@lru_cache(maxsize=128)
def _reachable(options: tuple[tuple[int, int, int], ...], ceiling: int, max_hp: int) -> tuple[tuple[int, ...], ...]:
    # Bits encode exact reachable HP; flags encode Boss, non-Minion anchor, requested tier.
    states = [[0] * 8 for _ in range(ceiling + 1)]
    states[0][0] = 1
    mask = (1 << (max_hp + 1)) - 1
    for cost, row in enumerate(states):
        for flags, hp_bits in enumerate(row):
            if not hp_bits:
                continue
            for units, hp, added_flags in options:
                if cost + units <= ceiling and not (flags & added_flags & 1):
                    states[cost + units][flags | added_flags] |= (hp_bits << hp) & mask
    return tuple(tuple(row) for row in states)


def build_encounter(
    catalog: list[dict], tier: int, party: list[dict], environment: dict, difficulty: str, rng: Random
) -> list[dict]:
    """Return fresh {id, creature_id, role} references; combat entry translates them once.

    Players supply {id, type: 'player', level}; companions supply {id, type:
    'companion', player_id, hp_factor}. The caller resolves profile factors and
    owner links, loads catalog rows, and resolves {region, terrain} before calling.
    Budget uses floor-mean player level; companion damage uses its owner's level.
    A requested-tier creature anchors the tier; species from the previous tier may supply adds.
    Species may repeat, with a non-Minion anchor and at most one Boss overall.
    An infeasible request raises ValueError naming the complete request.
    """
    players = {p["id"]: p["level"] for p in party if p["type"] == "player"}
    companions = [p for p in party if p["type"] == "companion"]
    level = sum(players.values()) // len(players)
    budget = calculate_encounter_budget([], level)
    headcount = len(players) + sum(p["hp_factor"] for p in companions)
    ceiling = budget["thresholds"][difficulty] * headcount / SOLO_PARTY_BASELINE
    damage = sum(_player_damage(level) for level in players.values()) + sum(
        p["hp_factor"] * _player_damage(players[p["player_id"]]) for p in companions
    )
    low, high = ROUND_WINDOWS[difficulty]
    # Exact products have at most four decimals; rounding first keeps inclusive endpoints exact.
    min_hp, max_hp = ceil(round(low * damage, 9)), floor(round(high * damage, 9))
    region, terrain = environment["region"], environment["terrain"]
    context = (
        f"tier={tier}, level_band={budget['level_band']}, difficulty={difficulty}, "
        f"region={region}, terrain={terrain}, headcount={headcount}, "
        f"budget={ceiling}, party_DPR={damage}"
    )
    candidates = sorted(
        (
            row
            for row in catalog
            if row["tier"] in (tier, tier - 1)
            and (row.get("hollow") or {}).get("class") != "named"
            and region in row["regions"]
            and terrain in row["terrains"]
        ),
        key=lambda row: row["id"],
    )
    if not candidates or not any(row["tier"] == tier for row in candidates):
        raise ValueError(f"No candidates: {context}")
    choices = [
        (
            row["id"],
            str(role),
            int(mod.budget_cost * 2),
            derive_role_stats(row, role)["hp"],
            int(role == "boss") | (2 if role != "minion" else 0) | (4 if row["tier"] == tier else 0),
        )
        for row in candidates
        for role, mod in ROLE_MODIFIERS.items()
    ]
    options = tuple((units, hp, flags) for _, _, units, hp, flags in choices)
    states = _reachable(options, floor(ceiling * 2), max_hp)
    terminals = [
        (cost, hp, flags)
        for cost, row in enumerate(states)
        for flags in (6, 7)
        for hp in range(min_hp, max_hp + 1)
        if row[flags] & (1 << hp)
    ]
    if not terminals:
        raise ValueError(f"No fit: {context}")
    cost, hp, flags = rng.choice(terminals)
    refs = []
    while cost:
        predecessors = [
            (index, previous)
            for index, (_, _, units, added_hp, added) in enumerate(choices)
            if units <= cost and added_hp <= hp
            for previous in range(8)
            if previous | added == flags
            and not (previous & added & 1)
            and states[cost - units][previous] & (1 << (hp - added_hp))
        ]
        index, previous = rng.choice(predecessors)
        creature_id, role, units, added_hp, _ = choices[index]
        refs.append({"id": f"generated_{len(refs) + 1}", "creature_id": creature_id, "role": role})
        cost, hp, flags = cost - units, hp - added_hp, previous
    return refs
