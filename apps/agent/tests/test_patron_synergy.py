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
AUTHORED = {"veythar", "kaelen", "aelora", "thyra", "syrath"}
ROSTER = {row["id"] for row in json.loads((ROOT / "content/archetypes.json").read_text())}


def doc_rows():
    with (ROOT / "docs/game_mechanics/game_mechanics_patrons.md").open() as source:
        text = "".join(itertools.islice(source, 39, 181))
    sections = re.split(r"^### ", text, flags=re.M)[1:]
    assert {s.split(",", 1)[0].lower() for s in sections} == AUTHORED
    expected = {}
    for section in sections:
        patron = section.split(",", 1)[0].lower()
        table = section.split("**Layer 4 — Archetype Resonance**", 1)[1]
        rows = re.findall(r"^\| ([^|]+) \| (Natural|Divine|Unexpected) \| ([^|]+) \|$", table, re.M)
        assert len(rows) == 3
        for archetypes, kind, effect in rows:
            for archetype in archetypes.lower().split(", "):
                if (patron, archetype, kind) == ("veythar", "seeker", "Unexpected"):
                    continue
                expected[patron, archetype] = (kind.lower(), effect)
    assert len(expected) == 29
    return expected


def test_doc_authored_effects_are_verbatim():
    catalog = {g["god_id"]: g for g in load_gods()}
    for (patron, archetype), (kind, effect) in doc_rows().items():
        row = catalog[patron]["layer_4_synergy_matrix"][archetype]
        assert row["type"] == kind, (patron, archetype)
        assert " ".join(c["effect"] for c in row["clauses"]) == effect, (patron, archetype)


def test_registry_targets_are_real_callables():
    registry = json.loads((ROOT / "content/engine_implementations.json").read_text())
    assert "kaelen_iron_resolve" in registry
    for target in registry.values():
        module, symbol = target.split(":")
        assert callable(getattr(importlib.import_module(module), symbol))
    assert registry["kaelen_iron_resolve"] == "kaelen_gift:trigger_iron_resolve"


@pytest.mark.parametrize(
    "archetype,kind,statuses", [("warrior", "natural", ["pending", "pending"]), ("bard", "unexpected", ["pending"])]
)
def test_public_kaelen_lookup(archetype, kind, statuses):
    from patron_synergy import get_archetype_synergy

    row = get_archetype_synergy(archetype, "kaelen")
    assert row is not None
    assert row["type"] == kind
    assert " ".join(c["effect"] for c in row["clauses"]) == doc_rows()["kaelen", archetype][1]
    assert [c["status"] for c in row["clauses"]] == statuses


@pytest.mark.parametrize(
    "archetype,patron,error",
    [
        ("unknown", "kaelen", "archetype"),
        ("unknown", "none", "archetype"),
        ("warrior", "unknown", "patron"),
        *(("warrior", p, "not yet authored") for p in ("orenthel", "valdris", "mortaen", "nythera", "zhael")),
    ],
)
def test_lookup_rejects_invalid_or_unauthored(archetype, patron, error):
    from patron_synergy import get_archetype_synergy

    with pytest.raises(ValueError, match=error):
        get_archetype_synergy(archetype, patron)


def test_public_unbound_lookup():
    from patron_synergy import get_archetype_synergy

    assert get_archetype_synergy("warrior", "none") is None


async def test_all_authored_pairs_and_guest_selection(dev_db_pool):
    catalog = load_gods()
    authored = {g["god_id"]: g["layer_4_synergy_matrix"] for g in catalog if g["layer_4_synergy_matrix"] is not None}
    assert set(authored) == AUTHORED
    assert {g["god_id"] for g in catalog if g["layer_4_synergy_matrix"] is None} == {
        "orenthel",
        "valdris",
        "mortaen",
        "nythera",
        "zhael",
    }
    assert len(ROSTER) == 18
    assert sum(len(m) for m in authored.values()) == 90
    async with AbilityWalk(dev_db_pool) as w:
        for patron, matrix in authored.items():
            assert set(matrix) == ROSTER
            for archetype, expected in matrix.items():
                await w.patch(**{"class": archetype, "divine_favor": {"patron": patron, "level": 40, "max": 100}})
                result = await w.command("query_info", {"kind": "patron"})
                assert result["synergy"] == expected, (patron, archetype)
        async with AbilityWalk(dev_db_pool) as guest:
            w.sd.party.members.append(guest.sd.party.primary)
            await guest.patch(**{"class": "warrior", "divine_favor": {"patron": "kaelen", "level": 40, "max": 100}})
            result = await w.command("query_info", {"kind": "patron"}, actor=guest.player)
            assert result["synergy"] == authored["kaelen"]["warrior"]
            await guest.patch(**{"class": "bard"})
            result = await w.command("query_info", {"kind": "patron"}, actor=guest.player)
            assert result["synergy"] == authored["kaelen"]["bard"]
        for archetype in (None, "unknown"):
            await w.patch(**{"class": archetype, "divine_favor": {"patron": "kaelen", "level": 40, "max": 100}})
            assert "archetype" in await w.command("query_info", {"kind": "patron"}, error=True)
        await w.patch(divine_favor={"patron": "unknown", "level": 40, "max": 100})
        assert "unknown patron" in await w.command("query_info", {"kind": "patron"}, error=True)
        await w.patch(divine_favor={"patron": "orenthel", "level": 40, "max": 100})
        result = await w.command("query_info", {"kind": "patron"})
        assert result["patron_id"] == "orenthel" and result["synergy"] is None
        assert result["layer_1_gift"] and result["abilities"]
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
