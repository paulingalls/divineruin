import json
from collections import Counter
from dataclasses import fields
from pathlib import Path

from combat_participant import CombatParticipant
from creature_schema import validate_creature_stat_block

ROOT = Path(__file__).resolve().parents[3]
IDS = {
    "hollow_shadeling",
    "hollow_wisp",
    "hollow_mawling",
    "hollowed_scout",
    "bandit",
    "bandit_captain",
    "ashmark_soldier",
    "ashmark_sergeant",
    "hollow_warden",
    "cultist",
    "cult_fanatic",
    "cult_leader",
    "hollow_knight",
}
ATTRIBUTES = dict(
    zip(
        ("STR", "DEX", "CON", "INT", "WIS", "CHA"),
        ("strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"),
        strict=True,
    )
)


def catalog():
    return json.loads((ROOT / "content/creatures.json").read_text())


def selected(rows=None, validator=validate_creature_stat_block):
    rows = catalog() if rows is None else rows
    assert rows
    assert Counter(r["id"] for r in rows if r["id"] in IDS) == Counter({key: 1 for key in IDS})
    result = [r for r in rows if r["id"] in IDS]
    for row in result:
        assert validator(row) == []
    return result


def row(key):
    return next(r for r in selected() if r["id"] == key)


def participant(enemy):
    keys = {f.name for f in fields(CombatParticipant)} - {"hp_current", "hp_max", "type", "initiative"}
    return CombatParticipant(
        **{k: v for k, v in enemy.items() if k in keys},
        type="enemy",
        initiative=10,
        hp_current=enemy["hp"],
        hp_max=enemy["hp"],
    )
