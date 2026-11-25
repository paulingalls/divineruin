"""Target and resource checks at the combat command boundary."""

from unittest.mock import patch

import pytest
from acceptance._capstone_helpers import _d20, _damage_die
from acceptance.mawling_harness import MawlingHarness
from acceptance.test_architect_fight import pos
from acceptance.test_architect_terrain import set_favor
from acceptance.test_cleave_and_whirlwind import CLEAVE, WHIRLWIND, battlefield
from acceptance.test_cleave_and_whirlwind import warrior as warrior
from acceptance.test_martial_core_kit import declare, weapon_attack
from acceptance.test_opportunity_strike import participant
from acceptance.test_self_buff_electives import discovered, receipt, stamina
from acceptance.test_still_anchors import fresh_session
from acceptance.test_still_anchors import mock_combat_agent_factory as mock_combat_agent_factory
from acceptance.test_strike_riders_guards import activate_variant

import ability_persistence
import combat_spatial
import combat_structures
import conditions
import db_mutations
import db_queries
from combat_phase import advance_combat_phase

KELDARAN = "warrior_cleaving_blow_keldaran"


@pytest.mark.parametrize(
    "invalid",
    ["none", "duplicate", "unknown", "ally", "structure", "fallen", "dead", "zero", "cap", "explicit", "explicit_list"],
)
async def test_invalid_selection_refuses_without_writes(warrior: MawlingHarness, invalid: str) -> None:
    ability = WHIRLWIND if invalid.startswith("explicit") else CLEAVE
    first, second, third, _ = await battlefield(warrior, ability, (2, 3, 4))
    state = await warrior.reload()
    if invalid == "structure":
        combat_structures.add_wall(state, "slate", "Slate", pos(1, -1), pos(1, 1))
    target = participant(state, second)
    if invalid == "fallen":
        target.is_fallen = True
    if invalid == "dead":
        target.is_dead = True
    if invalid == "zero":
        target.hp_current = 0
    await warrior.persist()
    targets = {
        "none": [],
        "duplicate": [first, first],
        "unknown": [first, "missing"],
        "ally": [first, warrior.players[0]],
        "structure": [first, "slate"],
        "fallen": [first, second],
        "dead": [first, second],
        "zero": [first, second],
        "cap": [first, second, third],
        "explicit": [first],
        "explicit_list": [first, second],
    }[invalid]
    before = await warrior.snapshot()
    with patch("check_resolution.dice_roll") as d20:
        error = await declare(warrior, ability, targets, error=True)
        d20.assert_not_called()
    assert ("Leave targets empty" if ability == WHIRLWIND else "distinct standing foes") in error
    assert await warrior.snapshot() == before


async def test_mixed_cleave_targets_refuse(warrior: MawlingHarness) -> None:
    first, second, *_ = await battlefield(warrior, CLEAVE, (2, 3))
    state = await warrior.reload()
    with pytest.raises(ValueError, match="distinct standing foes"):
        advance_combat_phase(
            state,
            {warrior.players[0]: {"type": "ability", "action": CLEAVE, "target_id": first, "target_ids": [second]}},
        )


@pytest.mark.parametrize("warrior", [(10, 10)], indirect=True)
@pytest.mark.parametrize(
    ("guard", "message"),
    [
        ("reach", "outside main-hand melee reach"),
        ("wall", "Line blocked"),
        ("empty", "requires a standing foe"),
        ("charm", "is Charmed"),
        ("missing", "requires an equipped main-hand melee weapon"),
        ("ranged", "requires an equipped main-hand melee weapon"),
        ("unowned", "hasn't learned"),
        ("level", "hasn't learned"),
        ("class", "hasn't learned"),
        ("inactive", "does not have"),
        ("stamina", "Stamina"),
        ("focus", "Focus"),
    ],
)
async def test_resolution_preflight_refuses_before_an_earlier_ally_writes(
    warrior: MawlingHarness, guard: str, message: str
) -> None:
    actor, ally = warrior.players
    ability = WHIRLWIND if guard in ("empty", "charm") else CLEAVE
    first, second, *_ = await battlefield(warrior, ability, (2, 9 if guard in ("reach", "empty") else 5))
    state = await warrior.reload()
    if guard == "empty":
        combat_spatial.place(state, actor, pos(-10))
        combat_spatial.place(state, ally, pos(2))
    else:
        combat_spatial.place(state, ally, pos(0))
    if guard == "charm":
        attacker = participant(state, actor)
        attacker.conditions = conditions.apply_condition(attacker.conditions, "charmed", source=second)
    if guard == "wall":
        combat_structures.add_wall(state, "slate", "Slate", pos(3, -1), pos(3, 1))
    participant(state, ally).initiative = participant(state, actor).initiative + 1
    state.initiative_order.remove(ally)
    state.initiative_order.insert(0, ally)
    await warrior.persist()

    action = ability
    if guard in ("focus", "inactive"):
        action = KELDARAN
    if guard == "focus":
        await activate_variant(warrior, CLEAVE, KELDARAN)
        await ability_persistence.update_player_resources(actor, focus=0, conn=warrior.pool)
    if guard == "stamina":
        await ability_persistence.update_player_resources(actor, stamina=3, conn=warrior.pool)
    if guard == "unowned":
        await warrior.pool.execute(
            "DELETE FROM character_abilities WHERE player_id=$1 AND ability_id=$2", actor, CLEAVE
        )
    if guard in ("missing", "ranged", "level", "class"):
        replacement = {
            "missing": '{"equipment":{}}',
            "ranged": '{"equipment":{"main_hand":{"name":"Shortbow","damage":"1d6","ranged":true}}}',
            "level": '{"level":3}',
            "class": '{"class":"rogue"}',
        }[guard]
        await warrior.pool.execute("UPDATE players SET data=data || $2::jsonb WHERE player_id=$1", actor, replacement)
    await warrior.command(
        "declare_phase",
        {
            "declarations": [
                weapon_attack(ally, first, ""),
                {
                    "kind": "ability",
                    "actor_id": actor,
                    "action": action,
                    "targets": [] if ability == WHIRLWIND else [first, second],
                    "argument_type": "",
                    "reshape": [],
                },
            ]
        },
    )
    before, player_rows = await warrior.snapshot()
    with (
        patch("check_resolution.dice_roll", return_value=_d20(15)) as d20,
        patch.object(db_mutations, "update_player_hp", wraps=db_mutations.update_player_hp) as hp,
        patch.object(
            ability_persistence, "update_player_resources", wraps=ability_persistence.update_player_resources
        ) as pay,
    ):
        assert message in await warrior.command("resolve_phase", {}, error=True)
        d20.assert_not_called()
        hp.assert_not_awaited()
        pay.assert_not_awaited()
    assert await warrior.snapshot() == ({**before, "beat": "declaration", "pending_declarations": {}}, player_rows)


async def test_single_target_active_variant_spends_its_own_cost(warrior: MawlingHarness) -> None:
    first, *_ = await battlefield(warrior, CLEAVE, (5,))
    actor = warrior.players[0]
    await activate_variant(warrior, CLEAVE, KELDARAN)
    assert (await discovered(warrior, CLEAVE))["active_variant_id"] == KELDARAN
    before = await db_queries.get_player(actor)
    assert before is not None
    await declare(warrior, KELDARAN, [first])
    with (
        patch("check_resolution.dice_roll", side_effect=[_d20(15), _d20(18)]) as d20,
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)) as damage,
    ):
        result = receipt(await warrior.drain(), actor)
    assert result["variant_id"] == KELDARAN
    assert [(s["target_id"], s["roll"], s["damage"]) for s in result["attacks"]] == [(first, 15, 5)]
    assert d20.call_count == 2 and damage.call_count == 1
    after = await db_queries.get_player(actor)
    assert after is not None
    assert after["stamina"]["current"] == before["stamina"]["current"] - 3
    assert after["focus"]["current"] == before["focus"]["current"] - 1


@pytest.mark.parametrize("warrior", [(10, 10)], indirect=True)
@pytest.mark.parametrize("ability", [CLEAVE, WHIRLWIND])
async def test_empty_start_spends_nothing_after_ally_drops_only_foe(warrior: MawlingHarness, ability: str) -> None:
    first, *_ = await battlefield(warrior, ability, (2,))
    actor, ally = warrior.players
    state = await warrior.reload()
    participant(state, first).hp_current = 1
    participant(state, ally).initiative = participant(state, actor).initiative + 1
    state.initiative_order.remove(ally)
    state.initiative_order.insert(0, ally)
    combat_spatial.place(state, ally, pos(0))
    await warrior.persist()
    before = await stamina(actor)
    await warrior.command(
        "declare_phase",
        {
            "declarations": [
                weapon_attack(ally, first, ""),
                {
                    "kind": "ability",
                    "actor_id": actor,
                    "action": ability,
                    "targets": [first] if ability == CLEAVE else [],
                    "argument_type": "",
                    "reshape": [],
                },
            ]
        },
    )
    with (
        patch("check_resolution.dice_roll", side_effect=[_d20(15)]) as d20,
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)) as damage,
    ):
        packets = (await warrior.command("resolve_phase", {}))["packets"]
    assert receipt(packets, ally)["target_fallen"] is True
    result = receipt(packets, actor)
    assert result["resolved"] is False
    assert d20.call_count == damage.call_count == 1
    assert await stamina(actor) == before


@pytest.mark.parametrize("warrior", [(10, 10)], indirect=True)
async def test_first_real_swing_after_a_skip_reveals_a_concealed_warrior(warrior: MawlingHarness) -> None:
    first, second, *_ = await battlefield(warrior, CLEAVE, (2, 3))
    actor, ally = warrior.players
    state = await warrior.reload()
    participant(state, first).hp_current = 1
    participant(state, ally).initiative = participant(state, actor).initiative + 1
    state.initiative_order.remove(ally)
    state.initiative_order.insert(0, ally)
    combat_spatial.place(state, ally, pos(0))
    await warrior.persist()
    await warrior.pool.execute(
        """UPDATE players SET data = jsonb_set(data, '{flags}', COALESCE(data->'flags', '{}'::jsonb)
               || '{"concealed": true}'::jsonb) WHERE player_id = $1""",
        actor,
    )
    await warrior.command(
        "declare_phase",
        {"declarations": [weapon_attack(ally, first, ""), declare_cleave(actor, [first, second])]},
    )
    with (
        patch("check_resolution.dice_roll", side_effect=[_d20(face) for face in (15, 16, 17)]),
        patch("check_resolution_attack.dice_roll", side_effect=[_damage_die(4), _damage_die(4)]),
    ):
        packets = (await warrior.command("resolve_phase", {}))["packets"]
    assert receipt(packets, ally)["target_fallen"] is True
    result = receipt(packets, actor)
    assert [(s["target_id"], s.get("skipped")) for s in result["attacks"]] == [(first, True), (second, None)]
    assert result["concealment"] == {"player_id": actor, "before": True, "concealed": False, "ended_by": "attack"}
    player = await db_queries.get_player(actor)
    assert player is not None and player["flags"]["concealed"] is False


@pytest.mark.parametrize("warrior", [(10, 10)], indirect=True)
async def test_cleave_skips_foe_that_moves_out_of_reach_before_its_packet(warrior: MawlingHarness) -> None:
    ally, actor = warrior.players
    first, second, *_ = await battlefield(warrior, CLEAVE, (2, 3), actor=actor)
    state = await warrior.reload()
    participant(state, ally).initiative = participant(state, actor).initiative + 1
    state.initiative_order.remove(ally)
    state.initiative_order.insert(0, ally)
    combat_spatial.place(state, ally, pos(0))
    await warrior.persist()
    await set_favor(warrior, "zhael", 40)
    await warrior.command(
        "declare_phase",
        {"declarations": [weapon_attack(ally, first, ""), declare_cleave(actor, [first, second])]},
    )
    before = await stamina(actor)
    with (
        patch("check_resolution.dice_roll", side_effect=[_d20(face) for face in (15, 16, 17)]),
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
    ):
        held = await warrior.command("resolve_phase", {})
        assert held["fate_offer"]["roller_id"] == ally
        assert await stamina(actor) == before
        state = await warrior.reload()
        combat_spatial.place(state, second, pos(20))
        await set_favor(warrior, "mortaen", 0)
        member = warrior.sd.member_state(actor)
        await fresh_session(warrior, await warrior.persist())
        warrior.sd.party.members.append(member)
        resumed = await warrior.command("resolve_phase", {})
        result = receipt(resumed["packets"], actor)
    assert len(result["attacks"]) == 2
    hit, skipped = result["attacks"]
    assert hit["target_id"] == first and hit["damage"] > 0
    assert skipped["target_id"] == second and skipped.get("skipped") is True, skipped
    assert "outside main-hand melee reach" in skipped["reason"]
    assert participant(await warrior.reload(), second).hp_current == 100
    assert await stamina(actor) == before - 4


def declare_cleave(actor: str, targets: list[str]) -> dict:
    return {
        "kind": "ability",
        "actor_id": actor,
        "action": CLEAVE,
        "targets": targets,
        "argument_type": "",
        "reshape": [],
    }
