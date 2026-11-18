"""Authored patron enhancements through the content and registered command boundaries."""

import importlib
import itertools
import json
import re
from pathlib import Path

import pytest
from patron_ability_walk import AbilityWalk

from _gods_content import load_gods

ROOT = Path(__file__).resolve().parents[3]
PATRONS = json.loads((ROOT / "packages/shared/fixtures/god_profiles.json").read_text())["patron_ids"]
ROSTER = {row["id"] for row in json.loads((ROOT / "content/archetypes.json").read_text())}


def doc_rows():
    with (ROOT / "docs/game_mechanics/game_mechanics_patrons.md").open() as source:
        text = "".join(itertools.islice(source, 39, 321))
    sections = re.split(r"^### ", text, flags=re.M)[1:]
    assert {s.split(",", 1)[0].lower() for s in sections} == set(PATRONS)
    expected = {}
    for section in sections:
        patron = section.split(",", 1)[0].lower()
        table = section.split("**Layer 4 — Archetype Resonance**", 1)[1]
        rows = re.findall(r"^\| ([^|]+) \| (Natural|Divine|Unexpected|Primary) \| ([^|]+) \|$", table, re.M)
        assert len(rows) == 3
        for archetypes, kind, effect in rows:
            for archetype in archetypes.lower().split(", "):
                if (patron, archetype, kind) == ("veythar", "seeker", "Unexpected"):
                    continue
                if kind == "Primary":
                    assert (patron, archetype) == ("zhael", "oracle")
                    kind = "Natural"
                expected[patron, archetype] = (kind.lower(), effect)
    assert len(expected) == 55
    return expected


def test_doc_authored_effects_are_verbatim():
    catalog = {g["god_id"]: g for g in load_gods()}
    assert set(catalog) == set(PATRONS)
    for patron in PATRONS:
        assert any(row["type"] == "natural" for row in catalog[patron]["layer_4_synergy_matrix"].values())
    for (patron, archetype), (kind, effect) in doc_rows().items():
        row = catalog[patron]["layer_4_synergy_matrix"][archetype]
        assert row["type"] == kind, (patron, archetype)
        assert " ".join(c["effect"] for c in row["clauses"]) == effect, (patron, archetype)


def test_natural_rows_have_mechanics_and_stay_close_to_domain_roster():
    authored = doc_rows()
    for god in load_gods():
        patron = god["god_id"]
        natural = {a: r for a, r in god["layer_4_synergy_matrix"].items() if r["type"] == "natural"}
        baseline = sum(p == patron and kind == "natural" for (p, _), (kind, _) in authored.items())
        assert len(natural) <= baseline + 2, patron
        for archetype, row in natural.items():
            assert any(c["resolution"] == "engine" for c in row["clauses"]), (patron, archetype)


def test_registry_targets_are_real_callables():
    registry = json.loads((ROOT / "content/engine_implementations.json").read_text())
    assert "kaelen_iron_resolve" in registry
    for target in registry.values():
        module, symbol = target.split(":")
        assert callable(getattr(importlib.import_module(module), symbol))
    assert registry["kaelen_iron_resolve"] == "kaelen_gift:trigger_iron_resolve"


async def test_all_authored_pairs_and_guest_selection(dev_db_pool):
    from patron_synergy import get_archetype_synergy

    catalog = load_gods()
    assert len(PATRONS) == len(set(PATRONS)) == 10
    assert len(catalog) == len({g["god_id"] for g in catalog}) == 10
    authored = {g["god_id"]: g["layer_4_synergy_matrix"] for g in catalog}
    assert set(authored) == set(PATRONS)
    roster = json.loads((ROOT / "content/archetypes.json").read_text())
    assert len(roster) == len(ROSTER) == 18
    for matrix in authored.values():
        assert matrix is not None
        assert set(matrix) == ROSTER
    visited = set()
    async with AbilityWalk(dev_db_pool) as w, AbilityWalk(dev_db_pool) as guest:
        await w.patch(**{"class": "warrior", "divine_favor": {"patron": "kaelen", "level": 40, "max": 100}})
        w.sd.party.members.append(guest.sd.party.primary)
        for patron, matrix in authored.items():
            for archetype, expected in matrix.items():
                await guest.patch(**{"class": archetype, "divine_favor": {"patron": patron, "level": 40, "max": 100}})
                assert get_archetype_synergy(archetype, patron) == expected
                result = await w.command("query_info", {"kind": "patron"}, actor=guest.player)
                assert result["synergy"] == expected, (patron, archetype)
                visited.add((patron, archetype))
        assert visited == set(itertools.product(PATRONS, ROSTER))
        assert len(visited) == 180
        assert get_archetype_synergy("warrior", "none") is None
        for archetype, patron, error in (
            ("unknown", "kaelen", "archetype"),
            ("unknown", "none", "archetype"),
            ("warrior", "unknown", "patron"),
        ):
            with pytest.raises(ValueError, match=error):
                get_archetype_synergy(archetype, patron)
        for archetype in (None, "unknown"):
            await w.patch(**{"class": archetype, "divine_favor": {"patron": "kaelen", "level": 40, "max": 100}})
            assert "archetype" in await w.command("query_info", {"kind": "patron"}, error=True)
        await w.patch(divine_favor={"patron": "unknown", "level": 40, "max": 100})
        assert "unknown patron" in await w.command("query_info", {"kind": "patron"}, error=True)
        for favor in ({"patron": "none"}, {"patron": None}, {}):
            await w.patch(divine_favor={**favor, "level": 0, "max": 100})
            result = await w.command("query_info", {"kind": "patron"})
            assert result["synergy"] is None and result["state"] == "Unbound"
            assert result["resonance"] == {"current": 0, "state": "stable"}
            assert {c["id"] for c in result["capabilities"]} == {
                "unbound_veil_clarity",
                "unbound_raw_channeling",
                "unbound_veil_mastery",
            }
