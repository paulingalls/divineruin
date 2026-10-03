import random

import pytest

from check_resolution_attack import resolve_attack
from dice import roll

ACTOR = {"attributes": {"strength": 20, "dexterity": 8}, "level": 1}
CATALOG = {"name": "Bite", "damage": "1d8+2", "attack_source": "catalog", "to_hit": 9}


def test_catalog_to_hit_overrides_attribute_bonus():
    result = resolve_attack(ACTOR, CATALOG, 10, 50, rng=random.Random(0), attack_mod=2)
    assert result.roll == 13
    assert result.attack_modifier == 11
    assert result.attack_total == 24


def test_catalog_damage_includes_fixed_bonus_once():
    rng = random.Random(0)
    rng.randint(1, 20)
    expected = roll("1d8+2", rng=rng).total
    result = resolve_attack(ACTOR, CATALOG, 10, 50, rng=random.Random(0))
    assert result.damage == expected


def test_equipment_keeps_attribute_damage_with_same_notation():
    equipment = {key: value for key, value in CATALOG.items() if key != "attack_source"}
    result = resolve_attack(ACTOR, equipment, 10, 50, rng=random.Random(0))
    assert result.attack_modifier == 6
    assert result.damage == 14


def test_catalog_role_and_conditions_apply_once():
    actor = {**ACTOR, "conditions": [{"type": "exhausted", "stacks": 2}, {"type": "enraged"}]}
    result = resolve_attack(actor, CATALOG, 10, 50, rng=random.Random(0), attack_mod=2, damage_mult=1.5)
    assert result.attack_modifier == 9
    assert result.damage == 16


@pytest.mark.parametrize("bonus", [None, True, "9"])
def test_catalog_source_requires_authored_bonus(bonus):
    action = {**CATALOG, "to_hit": bonus}
    with pytest.raises(ValueError, match="to_hit"):
        resolve_attack(ACTOR, action, 10, 50, rng=random.Random(0))


class CountedRandom(random.Random):
    def __init__(self, seed):
        super().__init__(seed)
        self.d20_count = 0

    def randint(self, a, b):
        if (a, b) == (1, 20):
            self.d20_count += 1
        return super().randint(a, b)


def test_catalog_advantage_and_disadvantage_cancel():
    rng = CountedRandom(1)
    result = resolve_attack(ACTOR, {**CATALOG, "advantage": True}, 10, 50, rng=rng)
    assert result.roll == 19
    assert rng.d20_count == 2
    actor = {**ACTOR, "conditions": [{"type": "blinded"}]}
    rng = CountedRandom(1)
    result = resolve_attack(actor, {**CATALOG, "advantage": True}, 10, 50, rng=rng)
    assert result.roll == 5
    assert rng.d20_count == 1


@pytest.mark.parametrize(
    "field,value", [("attack_source", "unknown"), ("to_hit", True), ("to_hit", None), ("self_heal", "raw_damage")]
)
def test_catalog_extensions_rejected_at_real_load_boundary(field, value):
    from combat_init_validation import validate_enemy_action_shapes

    with pytest.raises(ValueError, match=field):
        validate_enemy_action_shapes([{"id": "catalog", "action_pool": [{**CATALOG, field: value}]}])


@pytest.mark.parametrize("held", [False, True])
async def test_catalog_math_and_mark_modifier_survive_held_replay(held):
    import copy

    from combat._catalog_fixtures import deps, hold, setup
    from sample_fixtures import make_context

    import combat_hold
    from combat_packet import _resolve_one_packet

    state, actor, packet = setup(CATALOG)
    actor.attributes = ACTOR["attributes"]
    actor.attack_mod = 2
    source = copy.deepcopy(actor)
    source.id = "commander"
    state.participants.append(source)
    assert state.spatial is not None
    state.spatial["positions"][source.id] = dict(state.spatial["positions"][actor.id])
    state.spatial["speeds"][source.id] = state.spatial["speeds"][actor.id]
    state.focus_marks = {"player_1": {"source_id": source.id, "kind": "command"}}
    d = deps()
    if held:
        hold(state, actor)
        await combat_hold.pump(make_context().userdata, state, packet_deps=d)
        await combat_hold.pump(make_context().userdata, state, packet_deps=d)
        summary = (await combat_hold.pump(make_context().userdata, state, packet_deps=d))[0]
    else:
        summary = await _resolve_one_packet(make_context().userdata, state, packet, **d)
    assert summary["attack_total"] == 26
    assert summary["damage"] == 9
    d["resolver"].resolve_attack.assert_called_once()


def test_companion_producer_keeps_attribute_damage():
    import json
    from pathlib import Path

    from check_resolution_attack import weapon_attribute_modifier
    from companion_profiles import parse_companion_row
    from companion_scaling import companion_attacks_to_action_pool

    rows = json.loads((Path(__file__).resolve().parents[4] / "content/companions.json").read_text())
    assert rows
    for row in rows:
        profile = parse_companion_row(row["id"], row)
        actions = companion_attacks_to_action_pool(profile)
        assert actions
        for action in actions:
            assert "attack_source" not in action
            actor = {"attributes": profile.base_attributes, "level": 1}
            rng = random.Random(0)
            rng.randint(1, 20)
            expected = roll(action["damage"], rng=rng).total + weapon_attribute_modifier(actor, action)
            result = resolve_attack(actor, action, 2, 100, rng=random.Random(0))
            assert result.damage == expected


async def test_catalog_save_emits_only_saving_throw():
    from combat._catalog_fixtures import deps, setup
    from sample_fixtures import make_context

    import event_types as E
    from combat_packet import _resolve_one_packet

    state, _actor, packet = setup(
        {
            "name": "Wave",
            "attack_source": "catalog",
            "damage": "1d1+5",
            "damage_type": "necrotic",
            "save": "constitution",
            "dc": 12,
            "half_on_success": True,
        }
    )
    d = deps()
    summary = await _resolve_one_packet(make_context().userdata, state, packet, **d)
    assert "save_roll" in summary
    assert "attack_total" not in summary
    d["resolver"].resolve_attack.assert_not_called()
    payloads = [c.args[2] for c in d["sink"].emit.call_args_list if c.args[1] == E.DICE_ROLL]
    assert len(payloads) == 1
    assert payloads[0]["roll_type"] == "saving_throw"


def test_unknown_catalog_source_fails_loud_at_resolution():
    with pytest.raises(ValueError, match="attack_source"):
        resolve_attack(ACTOR, {**CATALOG, "attack_source": "guessed"}, 10, 50, rng=random.Random(0))


def test_catalog_critical_keeps_authored_damage_without_attribute():
    seed = next(n for n in range(200) if random.Random(n).randint(1, 20) == 20)
    rng = random.Random(seed)
    rng.randint(1, 20)
    expected = roll("1d8+2", rng=rng).total + roll("1d8+2", rng=rng).total
    result = resolve_attack(ACTOR, CATALOG, 10, 50, rng=random.Random(seed))
    assert result.critical_success
    assert result.damage == expected


@pytest.mark.parametrize(
    "action,field",
    [
        (
            {
                "name": "Rally",
                "kind": "healing",
                "target_group": "allied_bandits",
                "healing": "1d8",
                "attack_source": "catalog",
            },
            "attack_source",
        ),
        (
            {
                "name": "Rally",
                "kind": "healing",
                "target_group": "allied_bandits",
                "healing": "1d8",
                "self_heal": "damage_dealt",
            },
            "self_heal",
        ),
        (
            {
                "name": "Blind",
                "kind": "attack",
                "damage": "0",
                "damage_type": "none",
                "applies_condition": "blinded",
                "save": "constitution",
                "dc": 12,
                "self_heal": "damage_dealt",
            },
            "self_heal",
        ),
    ],
)
def test_catalog_extensions_reject_contradictory_shapes(action, field):
    from combat_init_validation import validate_enemy_action_shapes

    with pytest.raises(ValueError, match=field):
        validate_enemy_action_shapes([{"id": "catalog", "action_pool": [action]}])
