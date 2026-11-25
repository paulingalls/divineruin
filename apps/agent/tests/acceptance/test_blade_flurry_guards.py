"""Blade Flurry eligibility and preflight at the combat command boundary."""

from unittest.mock import patch

import pytest
from acceptance._capstone_helpers import _d20
from acceptance.mawling_harness import MawlingHarness
from acceptance.test_architect_fight import pos
from acceptance.test_blade_flurry import FLURRY, KELDARAN, bandit, rolls
from acceptance.test_blade_flurry import mock_combat_agent_factory as mock_combat_agent_factory
from acceptance.test_blade_flurry import rogue as rogue
from acceptance.test_martial_core_kit import declare, weapon_attack
from acceptance.test_opportunity_strike import participant
from acceptance.test_self_buff_electives import receipt
from acceptance.test_strike_riders_guards import activate_variant

import ability_persistence
import combat_spatial
from combat_phase import advance_combat_phase


async def test_without_advantage_or_nearby_ally(rogue: MawlingHarness) -> None:
    target = await bandit(rogue, prone=False)
    await declare(rogue, FLURRY, [target])
    with rolls((15, 16, 17), (3, 4, 5)) as (d20, damage):
        result = receipt(await rogue.drain(), rogue.players[0])
    assert d20.call_count == 3
    assert [call.args[0] for call in damage.call_args_list] == ["1d6"] * 3
    assert [(s["hit"], s["sneak_attack_dice"]) for s in result["attacks"]] == [(True, None)] * 3


@pytest.mark.parametrize("invalid", ["none", "multiple", "fallen"])
async def test_requires_one_standing_foe(rogue: MawlingHarness, invalid: str) -> None:
    target_id = await bandit(rogue)
    state = await rogue.reload()
    if invalid == "fallen":
        participant(state, target_id).is_fallen = True
        await rogue.persist()
    other = next(p.id for p in state.participants if not p.is_ally and p.id != target_id)
    targets = {"none": [], "multiple": [target_id, other], "fallen": [target_id]}[invalid]
    before = await rogue.snapshot()
    with patch("check_resolution.dice_roll") as d20:
        assert "Blade Flurry requires one standing foe" in await declare(rogue, FLURRY, targets, error=True)
        d20.assert_not_called()
    assert await rogue.snapshot() == before


async def test_rejects_a_mixed_target_declaration(rogue: MawlingHarness) -> None:
    target_id = await bandit(rogue)
    state = await rogue.reload()
    other = next(p.id for p in state.participants if not p.is_ally and p.id != target_id)
    with pytest.raises(ValueError, match="Blade Flurry requires one standing foe"):
        advance_combat_phase(
            state,
            {rogue.players[0]: {"type": "ability", "action": FLURRY, "target_id": target_id, "target_ids": [other]}},
        )


@pytest.mark.parametrize("rogue", [(9, 9)], indirect=True)
@pytest.mark.parametrize(
    ("guard", "message"),
    [
        ("unowned", "hasn't learned"),
        ("level", "hasn't learned"),
        ("class", "hasn't learned"),
        ("stamina", "Stamina"),
        ("focus", "Focus"),
        ("inactive", "does not have"),
        ("missing", "requires an equipped main-hand melee weapon"),
        ("ranged", "requires an equipped main-hand melee weapon"),
    ],
)
async def test_preflight_refuses_before_earlier_ally_attacks(rogue: MawlingHarness, guard: str, message: str) -> None:
    actor, ally = rogue.players
    target_id = await bandit(rogue, prone=False)
    state = await rogue.reload()
    combat_spatial.place(state, ally, pos(0))
    participant(state, ally).initiative = participant(state, actor).initiative + 1
    state.initiative_order.remove(ally)
    state.initiative_order.insert(0, ally)
    await rogue.persist()
    action = KELDARAN if guard in ("focus", "inactive") else FLURRY
    await rogue.command(
        "declare_phase",
        {
            "declarations": [
                weapon_attack(ally, target_id, ""),
                {
                    "kind": "ability",
                    "actor_id": actor,
                    "action": action,
                    "targets": [target_id],
                    "argument_type": "",
                    "reshape": [],
                },
            ]
        },
    )

    if guard == "unowned":
        await rogue.pool.execute("DELETE FROM character_abilities WHERE player_id=$1 AND ability_id=$2", actor, FLURRY)
    elif guard == "stamina":
        await ability_persistence.update_player_resources(actor, stamina=3, conn=rogue.pool)
    elif guard == "focus":
        await activate_variant(rogue, FLURRY, KELDARAN)
        await ability_persistence.update_player_resources(actor, focus=0, conn=rogue.pool)
    elif guard != "inactive":
        replacement = {
            "level": '{"level":7}',
            "class": '{"class":"warrior"}',
            "missing": '{"equipment":{}}',
            "ranged": '{"equipment":{"main_hand":{"name":"Shortbow","damage":"1d6","ranged":true}}}',
        }[guard]
        await rogue.pool.execute("UPDATE players SET data=data || $2::jsonb WHERE player_id=$1", actor, replacement)

    before, player_rows = await rogue.snapshot()
    with patch("check_resolution.dice_roll", return_value=_d20(15)) as d20:
        assert message in await rogue.command("resolve_phase", {}, error=True)
        d20.assert_not_called()
    assert await rogue.snapshot() == ({**before, "beat": "declaration", "pending_declarations": {}}, player_rows)
