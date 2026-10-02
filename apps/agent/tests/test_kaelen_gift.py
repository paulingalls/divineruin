import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest
from sample_fixtures import make_context

import _gods_content
import conditions
from kaelen_gift import trigger_iron_resolve
from session_data import CombatParticipant, CombatState


def player(pid="player_1", hp=4, kind="player"):
    return CombatParticipant(id=pid, name=pid, type=kind, initiative=15, hp_current=hp, hp_max=20, ac=14)


def setup(patron="kaelen"):
    ctx = make_context(party_member_ids=["player_2"])
    ctx.userdata.party.primary.patron_id = patron
    return ctx.userdata


def test_crossing_triggers_once():
    session = setup()
    target = player()
    assert trigger_iron_resolve(session, target, 10) == "Iron Resolve"
    assert target.iron_resolve_spent
    assert target.conditions == [{"type": "iron_resolve", "duration": 2, "source": "kaelen_iron_resolve", "stacks": 1}]
    target.hp_current = 3
    assert trigger_iron_resolve(session, target, 10) is None
    assert len(target.conditions) == 1


@pytest.mark.parametrize(
    "patron,kind,before,after,fires",
    [
        ("kaelen", "player", 5, 4, True),
        ("kaelen", "player", 10, 5, False),
        ("kaelen", "player", 10, 0, False),
        ("kaelen", "player", 4, 3, False),
        ("kaelen", "player", 4, 4, False),
        ("aelora", "player", 10, 4, False),
        ("none", "player", 10, 4, False),
        ("kaelen", "companion", 10, 4, False),
        ("kaelen", "enemy", 10, 4, False),
    ],
)
def test_crossing_eligibility_boundaries(patron, kind, before, after, fires):
    target = player(hp=after, kind=kind)
    assert bool(trigger_iron_resolve(setup(patron), target, before)) == fires
    assert target.iron_resolve_spent == fires
    assert bool(target.conditions) == fires


@pytest.mark.parametrize("host,guest,fires", [("kaelen", "none", False), ("none", "kaelen", True)])
def test_target_member_controls_binding(host, guest, fires):
    session = setup(host)
    session.party.member("player_2").patron_id = guest
    assert bool(trigger_iron_resolve(session, player("player_2"), 10)) == fires


def test_missing_player_member_fails_loud():
    with pytest.raises(ValueError, match="party member"):
        trigger_iron_resolve(setup(), player("missing"), 10)


@pytest.mark.parametrize("amount", [2, 3])
def test_attack_and_save_use_authored_amount(amount, tmp_path, monkeypatch):
    rows = deepcopy(_gods_content.load_gods())
    next(row for row in rows if row["god_id"] == "kaelen")["layer_1_gift"]["mechanics"]["amount"] = amount
    path = tmp_path / "gods.json"
    path.write_text(json.dumps(rows))
    script = """
import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd() / "tests"))
import _gods_content
_gods_content._GODS_JSON_PATH = Path(sys.argv[1])
import random
from dataclasses import asdict
from test_kaelen_gift import player, setup
from kaelen_gift import trigger_iron_resolve
from check_resolution_attack import resolve_attack
from check_resolution_save import resolve_saving_throw
target = player()
assert trigger_iron_resolve(setup(), target, 10) == "Iron Resolve"
boosted = asdict(target)
clean = {**boosted, "conditions": []}
weapon = {"name": "Sword", "damage": "1d8", "damage_type": "slashing", "properties": []}
a = resolve_attack(clean, weapon, 5, 100, rng=random.Random(10))
b = resolve_attack(boosted, weapon, 5, 100, rng=random.Random(10))
assert b.attack_total - a.attack_total == int(sys.argv[2])
assert b.damage == a.damage
a = resolve_saving_throw(clean, "wisdom", 12, "fear", rng=random.Random(10))
b = resolve_saving_throw(boosted, "wisdom", 12, "fear", rng=random.Random(10))
assert b.total - a.total == int(sys.argv[2])
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(path), str(amount)],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_two_wrap_lifetime():
    target = player()
    assert trigger_iron_resolve(setup(), target, 10)
    target.conditions, _events = conditions.tick_conditions(target.conditions)
    assert target.conditions[0]["duration"] == 1
    target.conditions, _events = conditions.tick_conditions(target.conditions)
    assert target.conditions == []
    assert target.iron_resolve_spent


def test_latch_serialization_and_legacy_default():
    target = player()
    assert trigger_iron_resolve(setup(), target, 10)
    state = CombatState(combat_id="test", participants=[target], initiative_order=[target.id])
    raw = state.to_dict()
    loaded = CombatState.from_dict(raw).get_participant(target.id)
    assert loaded is not None
    assert loaded.iron_resolve_spent
    del raw["participants"][0]["iron_resolve_spent"]
    legacy = CombatState.from_dict(raw).get_participant(target.id)
    assert legacy is not None
    assert not legacy.iron_resolve_spent
