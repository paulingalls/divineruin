"""Write boundaries, target gates, and reloads for the rogue strike electives."""

import json
from unittest.mock import patch

import pytest
from acceptance._enemy_opportunity_helpers import declare, resolve_allies
from acceptance.mawling_harness import MawlingHarness
from acceptance.test_architect_entomb import favor
from acceptance.test_architect_fight import pos
from acceptance.test_martial_core_kit import weapon_attack
from acceptance.test_opportunity_strike import participant
from acceptance.test_self_buff_electives import discovered, receipt, stamina
from acceptance.test_still_anchors import mock_combat_agent_factory as mock_combat_agent_factory
from acceptance.test_strike_riders import CRIPPLING, STUDY, enter_ambush, marker, restart, rolls, study
from acceptance.test_strike_riders import rogue as rogue
from weapon_fixtures import DAGGER

import ability_persistence
import combat_structures
import conditions
import db_mutations
import db_queries
import mentor_variant_progress

KELDARAN = "rogue_crippling_strike_keldaran"
DRATHIAN = "rogue_exploit_weakness_drathian"


async def activate_variant(walk: MawlingHarness, ability: str, variant: str) -> None:
    actor = walk.players[0]
    await mentor_variant_progress.record_unlocked(actor, variant, conn=walk.pool)
    await ability_persistence.set_active_variant(actor, ability, variant, conn=walk.pool)


@pytest.mark.parametrize(
    ("ability", "guard"),
    [
        (CRIPPLING, "unowned"),
        (CRIPPLING, "stamina"),
        (CRIPPLING, "focus"),
        (STUDY, "unowned"),
        (STUDY, "stamina"),
        (STUDY, "inactive"),
    ],
)
async def test_preflight_refuses_before_ally_damage(rogue: MawlingHarness, ability: str, guard: str) -> None:
    actor, ally = rogue.players
    variant = KELDARAN if ability == CRIPPLING else DRATHIAN
    if guard != "inactive":
        await activate_variant(rogue, ability, variant)
    if guard == "unowned":
        await rogue.pool.execute("DELETE FROM character_abilities WHERE player_id=$1 AND ability_id=$2", actor, ability)
    elif guard in ("stamina", "focus"):
        pool = {"focus": 0} if guard == "focus" else {"stamina": 1 if ability == CRIPPLING else 4}
        await ability_persistence.update_player_resources(actor, **pool, conn=rogue.pool)
    foe, _ = await enter_ambush(rogue)
    state = await rogue.reload()
    participant(state, ally).initiative = participant(state, actor).initiative + 1
    await rogue.persist()
    action = (
        weapon_attack(actor, foe, "crippling_strike", weapon=DAGGER["name"])
        if ability == CRIPPLING
        else study(actor, foe, action=variant)
    )
    await declare(rogue, weapon_attack(ally, foe, ""), action)
    state_before, players_before = await rogue.snapshot()
    inventory_before = [await db_queries.get_player_inventory(pid) for pid in rogue.players]
    with (
        rolls(17) as (d20, _),
        patch.object(db_mutations, "update_player_hp", wraps=db_mutations.update_player_hp) as hp,
        patch.object(
            ability_persistence, "update_player_resources", wraps=ability_persistence.update_player_resources
        ) as pay,
    ):
        refusal = await rogue.command("resolve_phase", {}, error=True)
        d20.assert_not_called()
        hp.assert_not_awaited()
        pay.assert_not_awaited()
    assert {
        "unowned": "hasn't learned",
        "stamina": "Stamina",
        "focus": "Focus",
        "inactive": "does not have",
    }[guard].lower() in refusal.lower()
    assert await rogue.snapshot() == (
        {**state_before, "beat": "declaration", "pending_declarations": {}},
        players_before,
    )
    assert [await db_queries.get_player_inventory(pid) for pid in rogue.players] == inventory_before


@pytest.mark.parametrize(
    "invalid", ["empty", "multiple", "self", "ally", "missing", "fallen", "zero_hp", "dead", "structure"]
)
async def test_study_refuses_nonstanding_foes(rogue: MawlingHarness, invalid: str) -> None:
    actor, ally = rogue.players
    foe, other = await enter_ambush(rogue)
    state = await rogue.reload()
    target = participant(state, foe)
    if invalid == "zero_hp":
        target.hp_current = 0
    if invalid == "fallen":
        target.is_fallen = True
    if invalid == "dead":
        target.is_dead = True
    if invalid == "structure":
        wall = combat_structures.add_wall(
            state, "wall", "Thornwall", pos(35), {"x": 35, "y": 10, "z": 0}, kind=combat_structures.THORNWALL
        )
        foe = wall.id
    await rogue.persist()
    targets = {"empty": [], "multiple": [foe, other], "self": [actor], "ally": [ally], "missing": ["unknown"]}
    before = await rogue.snapshot()
    error = await rogue.command(
        "declare_phase", {"declarations": [study(actor, *targets.get(invalid, [foe]))]}, error=True
    )
    assert "standing foe" in error or (invalid == "missing" and "unknown" in error.lower())
    assert await rogue.snapshot() == before


async def seed_study(rogue: MawlingHarness, foe: str, *, duration: int = 1) -> None:
    state = await rogue.reload()
    owner = participant(state, rogue.players[0])
    owner.conditions = conditions.apply_condition(owner.conditions, "studied_weakness", source=foe, duration=duration)
    await rogue.persist()
    await restart(rogue)


@pytest.mark.parametrize(
    ("gate", "face", "expected_dice"),
    [
        ("not_ready", 17, ["1d8", "2d6"]),
        ("miss", 1, []),
        ("ineligible", 17, ["1d8"]),
        ("other_rogue", 17, ["1d8", "2d6"]),
    ],
)
async def test_only_studying_rogues_eligible_hit_consumes_the_mark(
    rogue: MawlingHarness, gate: str, face: int, expected_dice: list[str]
) -> None:
    owner, ally = rogue.players
    if gate == "other_rogue":
        await rogue.pool.execute(
            "UPDATE players SET data=data || $2::jsonb WHERE player_id=$1",
            ally,
            json.dumps({"class": "rogue", "equipment": {"main_hand": DAGGER}}),
        )
    foe, _ = await enter_ambush(rogue, ally_x=20 if gate == "ineligible" else 0)
    await seed_study(rogue, foe, duration=2 if gate == "not_ready" else 1)
    attacker = ally if gate == "other_rogue" else owner
    await declare(rogue, weapon_attack(attacker, foe, "", weapon=DAGGER["name"]))
    with rolls(face) as (_, damage):
        result = receipt(await resolve_allies(rogue), attacker)
    assert result["hit"] is (face != 1)
    assert [call.args[0] for call in damage.call_args_list] == expected_dice
    assert result["sneak_attack_raw_damage"] == (2 if "2d6" in expected_dice else 0)
    await rogue.reload()
    mark = marker(rogue, owner, "studied_weakness")
    assert mark is not None and mark["source"] == foe


@pytest.mark.parametrize("ability", [CRIPPLING, STUDY])
async def test_fate_pause_and_reload_finishes_once(rogue: MawlingHarness, ability: str) -> None:
    actor = rogue.players[0]
    await favor(rogue)
    variant = KELDARAN if ability == CRIPPLING else DRATHIAN
    await activate_variant(rogue, ability, variant)
    foe, _ = await enter_ambush(rogue)
    stamina_before = await stamina(actor)
    if ability == STUDY:
        await declare(rogue, study(actor, foe, action=variant))
        study_receipt = receipt(await rogue.drain(), actor)
        assert study_receipt["variant_id"] == variant
        assert await stamina(actor) == stamina_before - 5
    else:
        assert (await discovered(rogue, ability))["active_variant_id"] == variant
    balance = await stamina(actor)
    player = await db_queries.get_player(actor)
    assert player is not None
    focus = player["focus"]["current"]
    hp_before = participant(await rogue.reload(), foe).hp_current
    await declare(
        rogue, weapon_attack(actor, foe, "crippling_strike" if ability == CRIPPLING else "", weapon=DAGGER["name"])
    )
    with rolls(17) as (d20, damage):
        first = await rogue.command("resolve_phase", {})
        assert first["fate_offer"]["roller_id"] == actor
        state = await restart(rogue)
        assert participant(state, foe).hp_current == hp_before
        assert await stamina(actor) == balance
        assert bool(marker(rogue, actor, "studied_weakness")) is (ability == STUDY)
        damage.assert_not_called()
        finished = await rogue.command("resolve_phase", {})
        hit = receipt(finished["packets"], actor)
    d20.assert_called_once()
    assert hit["hit"]
    if ability == CRIPPLING:
        assert hit["variant_id"] == variant
        assert hit["condition_inflicted"] == "crippled"
        assert await stamina(actor) == balance - 2
        player = await db_queries.get_player(actor)
        assert player is not None and player["focus"]["current"] == focus - 1
    else:
        assert hit["sneak_attack_raw_damage"] == 12
        damage.assert_called_once()
        assert marker(rogue, actor, "studied_weakness") is None
    await restart(rogue)
    await rogue.drain()
    assert participant(await rogue.reload(), foe).hp_current == hp_before - hit["damage"]
    assert await stamina(actor) == balance - (2 if ability == CRIPPLING else 0)


@pytest.mark.parametrize("immune", [False, True])
async def test_crippling_does_not_mark_a_downed_or_warded_foe(rogue: MawlingHarness, immune: bool) -> None:
    actor = rogue.players[0]
    foe, _ = await enter_ambush(rogue)
    state = await rogue.reload()
    target = participant(state, foe)
    if immune:
        target.condition_immunities["crippled"] = "worn protection"
    else:
        target.hp_current = 1
    await rogue.persist()
    await declare(rogue, weapon_attack(actor, foe, "crippling_strike", weapon=DAGGER["name"]))
    with rolls(17):
        hit = receipt(await resolve_allies(rogue), actor)
    assert hit["hit"] and "condition_inflicted" not in hit
    assert hit.get("condition_immune") == ("crippled" if immune else None)
    await rogue.reload()
    assert marker(rogue, foe, "crippled") is None
