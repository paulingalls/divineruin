import json
from copy import deepcopy
from pathlib import Path
from random import Random

import pytest

from companion_profiles import parse_companion_row
from encounter_budget import calculate_encounter_budget
from encounter_builder import build_encounter
from encounter_references import validate_encounter_references
from encounter_roles import derive_role_stats

ROOT = Path(__file__).resolve().parents[3]
CATALOG = json.loads((ROOT / "content/creatures.json").read_text())
PROFILES = {
    row["id"]: parse_companion_row(row["id"], row) for row in json.loads((ROOT / "content/companions.json").read_text())
}
ENV = {"region": "greyvale", "terrain": "forest"}
DPR = {
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

WINDOWS = {"standard": (3, 5), "tough": (4, 6), "boss": (5, 7)}


def party(levels=(6,), companion="companion_kael", owner=0):
    players = [{"id": f"p{i}", "type": "player", "level": level} for i, level in enumerate(levels)]
    return [
        *players,
        {
            "id": companion,
            "type": "companion",
            "player_id": f"p{owner}",
            "hp_factor": PROFILES[companion].scaling_rules.hp_factor,
        },
    ]


def row(hp, **changes):
    return {"id": "control", "tier": 2, "hp": hp, "regions": ["greyvale"], "terrains": ["forest"], **changes}


def check(refs, catalog, tier, members, environment=ENV, difficulty="standard"):
    players = {p["id"]: p["level"] for p in members if p["type"] == "player"}
    level = sum(players.values()) // len(players)
    validate_encounter_references(
        {"id": "generated", "recommended_party_level": level, "enemies": refs},
        {r["id"] for r in catalog},
    )
    companions = [p for p in members if p["type"] == "companion"]
    headcount = len(players) + sum(p["hp_factor"] for p in companions)
    damage = sum(DPR[level] for level in players.values()) + sum(
        p["hp_factor"] * DPR[players[p["player_id"]]] for p in companions
    )
    budget = calculate_encounter_budget(refs, level)
    assert 0 < budget["total"] <= budget["thresholds"][difficulty] * headcount / 1.75
    assert not budget["all_minion"] and not budget["too_many_bosses"]
    by_id = {r["id"]: r for r in catalog}
    hp = 0
    for ref in refs:
        creature = by_id[ref["creature_id"]]
        assert creature["tier"] in (tier, tier - 1)
        assert (creature.get("hollow") or {}).get("class") != "named"
        assert environment["region"] in creature["regions"]
        assert environment["terrain"] in creature["terrains"]
        hp += derive_role_stats(creature, ref["role"])["hp"]
    assert any(by_id[ref["creature_id"]]["tier"] == tier for ref in refs)
    low, high = WINDOWS[difficulty]
    assert low <= round(hp / damage, 9) <= high
    return budget["total"], hp


def test_personal_level_progression_at_builder_boundary():
    for level, damage in DPR.items():
        members = [{"id": "player", "type": "player", "level": level}]
        with pytest.raises(ValueError) as error:
            build_encounter([row(10000)], 2, members, ENV, "standard", Random(0))
        assert f"party_DPR={damage}" in str(error.value)


def test_catalog_selection():
    before = deepcopy(CATALOG)
    members = party()
    results = [build_encounter(CATALOG, 2, members, ENV, "standard", Random(seed)) for seed in range(50)]
    assert results[0] == build_encounter(CATALOG, 2, members, ENV, "standard", Random(0))
    assert len({json.dumps(refs) for refs in results}) > 1
    for refs in results:
        check(refs, CATALOG, 2, members)
    assert before == CATALOG


def test_two_players_scale_above_solo_ceiling():
    members = party((6, 6))
    for catalog in (CATALOG, [row(15)]):
        refs = build_encounter(catalog, 2, members, ENV, "standard", Random(0))
        cost, _ = check(refs, catalog, 2, members)
        if catalog != CATALOG:
            assert 4 < cost <= 44 / 7


def test_sable_factor_controls_budget_and_damage():
    members = party(companion="companion_sable")
    assert members[-1]["hp_factor"] == 0.5
    check(build_encounter(CATALOG, 2, members, ENV, "standard", Random(0)), CATALOG, 2, members)
    with pytest.raises(ValueError, match=r"No fit.*headcount=1.5"):
        build_encounter([row(13)], 2, members, ENV, "standard", Random(0))
    check(build_encounter([row(13)], 2, party(), ENV, "standard", Random(0)), [row(13)], 2, party())


def test_mountain_requires_both_memberships():
    environment = {"region": "keldaran_mountains", "terrain": "mountain"}
    members = party()
    check(build_encounter(CATALOG, 2, members, environment, "standard", Random(0)), CATALOG, 2, members, environment)
    eligible = row(20, regions=["sunward_coast"], terrains=["mountain"])
    eel = next(r for r in CATALOG if r["id"] == "tidecaller_eel")
    foreign = row(20, id="foreign", regions=["elsewhere"], terrains=["mountain"])
    environment = {"region": "sunward_coast", "terrain": "mountain"}
    catalog = [eligible, eel, foreign]
    refs = build_encounter(catalog, 2, members, environment, "standard", Random(0))
    check(refs, catalog, 2, members, environment)
    for excluded in ([eel], [foreign]):
        with pytest.raises(ValueError, match=r"No candidates.*sunward_coast.*mountain"):
            build_encounter(excluded, 2, members, environment, "standard", Random(0))


def test_no_candidates_and_no_fit_name_request():
    with pytest.raises(ValueError, match=r"No candidates.*ocean.*abyss"):
        build_encounter(CATALOG, 2, party(), {"region": "ocean", "terrain": "abyss"}, "standard", Random(0))
    with pytest.raises(
        ValueError, match=r"No fit.*tier=2.*level_band=5-8.*standard.*greyvale.*forest.*budget=.*party_DPR="
    ):
        build_encounter([row(1000)], 2, party(), ENV, "standard", Random(0))


def test_round_window_includes_exact_endpoints():
    # L4 + Sable: exact party DPR 11.4, so 57 HP is exactly 5.0 rounds; float sums give 11.3999...
    sable = party((4,), "companion_sable")
    check(build_encounter([row(57)], 2, sable, ENV, "standard", Random(0)), [row(57)], 2, sable)
    members = party()
    members[-1]["hp_factor"] = 16 / 9.11 - 1
    for hp in (48, 80):
        catalog = [row(hp)]
        results = [build_encounter(catalog, 2, members, ENV, "standard", Random(seed)) for seed in range(50)]
        totals = {check(refs, catalog, 2, members)[1] for refs in results}
        assert hp in totals
    with pytest.raises(ValueError, match="No fit"):
        build_encounter([row(81)], 2, members, ENV, "standard", Random(0))
    for seed in range(50):
        refs = build_encounter([row(47)], 2, members, ENV, "standard", Random(seed))
        check(refs, [row(47)], 2, members)


def test_hollow_eligible_named_excluded_and_tier_four_refuses():
    hollow = [r for r in CATALOG if r["category"] == "hollow"]
    refs = build_encounter(hollow, 2, party(), ENV, "standard", Random(0))
    check(refs, hollow, 2, party())
    named = row(20, id="named", hollow={"class": "named"})
    with pytest.raises(ValueError, match="No candidates"):
        build_encounter([named], 2, party(), ENV, "standard", Random(0))
    catalog = [row(20), named]
    check(build_encounter(catalog, 2, party(), ENV, "standard", Random(0)), catalog, 2, party())
    with pytest.raises(ValueError, match=r"No candidates.*tier=4"):
        build_encounter(CATALOG, 4, party((15,)), ENV, "boss", Random(0))


def test_mixed_levels_use_owner_damage_and_floor_mean_budget():
    catalog = [row(15)]
    observed = []
    for owner in (0, 1):
        members = party((4, 7), owner=owner)
        results = [build_encounter(catalog, 2, members, ENV, "standard", Random(seed)) for seed in range(50)]
        hps = {check(refs, catalog, 2, members)[1] for refs in results}
        observed.append(hps)
        assert results[0] == build_encounter(catalog, 2, members[::-1], ENV, "standard", Random(0))
    assert 72 in observed[0] and 72 not in observed[1]
    with pytest.raises(ValueError, match=r"No fit.*level_band=3-4"):
        build_encounter([row(14)], 2, party((4, 5)), ENV, "standard", Random(0))


def test_all_candidate_cells_over_fifty_seeds():
    expected = {
        1: (
            (29, 29, 33, 33, 33, 33, 33, 33, 33, 33, 32, 32, 32, 29, 33, 33, 33, 33, 33, 33),
            (32, 32, 39, 33, 39, 39, 33, 33, 39, 33, 33, 33, 33, 33, 33, 33, 33, 33, 33, 33),
            (33, 33, 33, 33, 33, 33, 33, 33, 33, 33, 33, 33, 33, 32, 33, 33, 33, 33, 33, 33),
        ),
        2: (
            (42, 42, 42, 47, 47, 47, 47, 47, 47, 47, 47, 47, 47, 47, 47, 47, 47, 47, 47, 47),
            (47, 47, 47, 47, 47, 47, 47, 47, 47, 47, 47, 47, 47, 47, 47, 47, 47, 47, 47, 47),
            (47, 47, 47, 42, 47, 47, 47, 47, 47, 47, 47, 47, 47, 47, 47, 47, 47, 47, 47, 47),
        ),
        3: (
            (0, 0, 0, 0, 20, 20, 21, 25, 25, 25, 25, 25, 25, 25, 25, 25, 25, 25, 25, 25),
            (0, 0, 20, 20, 25, 25, 25, 25, 25, 25, 25, 25, 25, 25, 25, 25, 25, 25, 25, 25),
            (20, 20, 21, 25, 25, 25, 25, 22, 25, 25, 25, 25, 25, 25, 25, 25, 25, 25, 25, 25),
        ),
    }
    supported = set()
    cells = 0
    for tier in (1, 2, 3):
        pairs = sorted(
            {
                (region, terrain)
                for r in CATALOG
                if r["tier"] in (tier, tier - 1)
                for region in r["regions"]
                for terrain in r["terrains"]
            }
        )
        assert len(pairs) >= 25
        for level in range(1, 21):
            for di, difficulty in enumerate(WINDOWS):
                successes = 0
                for region, terrain in pairs:
                    cells += 1
                    environment = {"region": region, "terrain": terrain}
                    members = party((level,))
                    try:
                        refs = build_encounter(CATALOG, tier, members, environment, difficulty, Random(0))
                    except ValueError as error:
                        assert str(error).startswith(("No fit:", "No candidates:"))
                        assert all(value in str(error) for value in (f"tier={tier}", difficulty, region, terrain))
                    else:
                        check(refs, CATALOG, tier, members, environment, difficulty)
                        if level in (1, 2, 3, 4, 5, 8, 9, 14, 15, 20):
                            for seed in range(1, 50):
                                refs = build_encounter(CATALOG, tier, members, environment, difficulty, Random(seed))
                                check(refs, CATALOG, tier, members, environment, difficulty)
                        supported.add((tier, difficulty))
                        successes += 1
                assert successes == expected[tier][di][level - 1]
    assert cells >= 3000 and len(supported) == 9
