from unittest.mock import patch

import pytest
from _mortaen_threshold_fixtures import (
    ENCOUNTER,
    FOE,
    GIFT,
    OTHER_GIFTS,
    active,
    attack_event,
    checkpoint,
    claw,
    declare,
    drain,
    field_damage,
    fight,
    follower,
    incoming_spell,
    position,
    reflected_bolt,
    rolls,
    serenity_touch,
    snapshot,
    survivor,
    walk,
)
from _patron_engine_fixtures import configure
from _unbound_path_fixtures import row
from _unbound_path_fixtures import world as world
from _zhael_fate_fixtures import attack, game_tools
from livekit.agents.llm import ToolError
from voice_condition_fixtures import participant

import character_spells
import combat_phase
import db_mutations
from activate_tools import activate
from query_tools import query_info


async def walk_outside_combat(world):
    await configure(world, "mortaen", "warrior", divine_favor={"patron": "mortaen", "level": 75, "max": 100})
    call = game_tools(world.ctx.userdata, query_info, activate)
    gift = next(g for g in (await call("query_info", kind="patron"))["abilities"] if g["id"] == GIFT)
    result = await call("activate", id=gift["id"])
    assert "threshold" in result["dm_cue"].lower()
    player = await row(world, 0)
    assert player["patron_gifts"][GIFT] == {"spent": True}
    assert not player.get("conditions")
    assert world.ctx.userdata.combat_state is None


async def scenario(world, run, *args):
    await run(world, *args)


async def weapon_exchange(world, dtype, magical):
    async with fight(world) as call:
        host = world.ids[0]
        position(world)
        foe = participant(active(world), FOE)
        outgoing = dtype == "slashing" and not magical
        if outgoing:
            foe.hp_current = foe.hp_max = 100
            foe.damage_affinities["vulnerable"] = ["necrotic"]
        mode = {"type": "ranged", "properties": ["ranged"]} if dtype == "piercing" else {}
        enemy_attack = claw(world, damage_type=dtype, magical=magical, **mode)
        await checkpoint(world)
        before = await row(world, 0)
        await walk(call)
        await declare(world, call, enemy_attack, *([attack(host, FOE)] if outgoing else []))
        with rolls(*(5, 18, 18, 15) if outgoing else (18, 15)):
            packets, result = await drain(world, call)
        if outgoing:
            after = await row(world, 0)
            assert after["patron_gifts"] == {**before["patron_gifts"], GIFT: {"spent": True}}
            assert [after[k] for k in ("focus", "stamina", "resonance")] == [
                before[k] for k in ("focus", "stamina", "resonance")
            ]
            hit = next(p for p in packets if p["actor_id"] == host)
            assert (hit["damage_type"], hit["damage"]) == ("necrotic", 20)
            assert participant(active(world), FOE).hp_current == 80
            assert attack_event(world, "Rook")["roll"] == 18
        incoming = next(p for p in packets if p["actor_id"] == FOE)
        assert (incoming["hit"], incoming["damage"]) == (True, 0)
        assert attack_event(world, foe.name)["roll"] == 15
        assert isinstance(result, dict) and not result.get("threshold_walk_returns")
        assert [c["type"] for c in follower(world).conditions] == ["incorporeal"]
        await survivor(world, 100)


async def inner_fire(world):
    async with fight(world, hp=3, race="draethar") as call:
        await walk(call)
        with rolls():
            result = await call("activate", id="draethar_inner_fire")
        assert (result["fire_damage"], result["hp_remaining"]) == (10, 1)
        await survivor(world)


async def lethal_claw(world, shape, protected=True, vulnerable=False, hp=3):
    gifts = {**OTHER_GIFTS, "mortaen_death_ward": {"spent": True}}
    async with fight(world, hp=hp, gifts=gifts) as call:
        position(world)
        changes = {"damage_type": "fire", "magical": True}
        if shape != "attack":
            changes.update(resolution=shape, save="DEX", dc=14, conditions_on_failure=[], conditions_on_success=[])
        if shape == "save":
            changes.update(to_hit=0, save_success_damage="half")
        enemy_attack = claw(world, **changes)
        if vulnerable:
            follower(world).damage_affinities["vulnerable"] = ["fire"]
        await checkpoint(world)
        if protected:
            await walk(call)
        await declare(world, call, enemy_attack)
        with rolls(18, 15, 7) if shape != "save" else rolls(7):
            packets, _ = await drain(world, call)
        receipt = next(p for p in packets if p["actor_id"] == FOE)
        assert (receipt["damage"], receipt["damage_type"], receipt["target_fallen"]) == (
            20 if vulnerable else 10,
            "fire",
            not protected,
        )
        if protected:
            assert receipt["context"] != "killing_blow"
            if shape != "save":
                event = attack_event(world, participant(active(world), FOE).name)
                assert event["roll"] == 15 and event["context"] != "killing_blow"
            await survivor(world, max(1, hp - receipt["damage"]))


async def expiry(world, terminal):
    async with fight(world) as call:
        host = world.ids[0]
        position(world)
        position(world, "mawling_2")
        await checkpoint(world)
        await walk(call)
        await declare(world, call, *([attack(host, "mawling_2")] if terminal else []))
        with rolls(5, 18):
            _, first = await drain(world, call)
        assert isinstance(first, dict) and not first.get("threshold_walk_returns")
        assert [(c["type"], c["duration"]) for c in follower(world).conditions] == [("incorporeal", 1)]
        if terminal:
            old = active(world).combat_id
            assert participant(active(world), "mawling_2").is_fallen
            await declare(world, call, attack(host, FOE))
            original_wrap = combat_phase._wrap

            def terminal_wrap(state):
                outcome = original_wrap(state)
                assert outcome.combat_ended and outcome.outcome == "victory"
                assert not participant(state, host).conditions
                assert not outcome.threshold_walk_returns
                return outcome

            with rolls(5, 18), patch.object(combat_phase, "_wrap", side_effect=terminal_wrap) as inspected:
                _, handoff = await drain(world, call)
            inspected.assert_called_once()
            assert isinstance(handoff, tuple) and "threshold_walk_returns" not in handoff[1]
            await new_fight(world, call, old)
            return
        await declare(world, call)
        _, returned = await drain(world, call)
        assert [c["type"] for c in follower(world).conditions] == ["shaken"]
        assert isinstance(returned, dict)
        [cue] = returned["threshold_walk_returns"]
        assert (cue["actor_id"], cue["actor_name"]) == (host, "Rook")
        assert "Rook" in cue["dm_cue"] and "shaken" in cue["dm_cue"].lower()
        await declare(world, call, claw(world), attack(host, "mawling_2"))
        with rolls(18, 7, 18):
            packets, following = await drain(world, call)
        assert attack_event(world, "Rook")["roll"] == 7
        assert not follower(world).conditions
        assert next(p for p in packets if p["actor_id"] == FOE)["damage"] == 10
        assert attack_event(world, participant(active(world), FOE).name)["roll"] == 18
        await survivor(world, 90)
        assert isinstance(following, dict) and not following.get("threshold_walk_returns")


async def new_fight(world, call, old_id):
    assert await db_mutations.load_combat_state(old_id, conn=world.pool) is None
    player = await row(world, 0)
    assert not {"incorporeal", "shaken"} & {c["type"] for c in player.get("conditions", [])}
    assert player["patron_gifts"][GIFT] == {"spent": True}
    await call("enter_mode", mode="combat", encounter_id=ENCOUNTER)
    assert active(world).combat_id != old_id
    assert not {"incorporeal", "shaken"} & {c["type"] for c in follower(world).conditions}


async def early_end(world):
    exhausted = {"type": "exhausted", "source": "travel", "duration": None, "stacks": 1}
    async with fight(world, conditions=(exhausted,)) as call:
        old_id = active(world).combat_id
        await walk(call)
        await call("end_combat", outcome="fled")
        await new_fight(world, call, old_id)
        assert (await row(world, 0))["conditions"] == follower(world).conditions == [exhausted]


async def test_tier_and_session_refusals_preserve_state(world):
    async with fight(world, favor=74) as call:
        before = await snapshot(world)
        with pytest.raises(ToolError, match="Exalted"):
            await call("activate", id=GIFT)
        assert await snapshot(world) == before
        await configure(world, "mortaen", "warrior", divine_favor={"patron": "mortaen", "level": 75, "max": 100})
        await walk(call)
        before = await snapshot(world)
        with pytest.raises(ToolError, match="Already spent"):
            await call("activate", id=GIFT)
        assert await snapshot(world) == before


@pytest.mark.parametrize("patron", ["mortaen", "syrath"])
@pytest.mark.parametrize("phase", ["ally", "hostile"])
async def test_both_gifts_preserve_live_fate_offer(world, patron, phase):
    ability = GIFT if patron == "mortaen" else "syrath_veilstep"
    args = {"destination": {"x": 5, "y": 0, "z": 0}} if patron == "syrath" else {}
    async with fight(world, patron=patron, guest="zhael") as call:
        position(world)
        await checkpoint(world)
        await declare(world, call, attack(world.ids[0], FOE) if phase == "ally" else claw(world))
        session = world.ctx.userdata
        with rolls(18):
            for _ in range(5):
                result = await call("resolve_phase")
                if "fate_offer" in result:
                    break
            else:
                pytest.fail("No Fate offer")
            offering = session.fate_offer
            before = await snapshot(world)
            assert bool(active(world).ally_continuation) is (phase == "ally")
            assert bool(active(world).held_actions) is (phase == "hostile")
            if phase == "hostile":
                assert "fate_attack" in active(world).held_actions[0]
            with pytest.raises(ToolError, match="partially resolved"):
                await call("activate", id=ability, **args)
            assert session.fate_offer is offering
            assert await snapshot(world) == before
            await drain(world, call)
        await call("activate", id=ability, **args)
        assert (await row(world, 0))["patron_gifts"][ability] == {"spent": True}


@pytest.mark.parametrize("patron", ["mortaen", "syrath"])
async def test_both_gifts_refuse_an_offer_outside_the_round_fields(world, patron):
    """Wrap saves, Inner Fire and death saves hold an offer with no ally_continuation or held_actions."""
    ability = GIFT if patron == "mortaen" else "syrath_veilstep"
    args = {"destination": {"x": 5, "y": 0, "z": 0}} if patron == "syrath" else {}
    async with fight(world, patron=patron, guest="zhael") as call:
        position(world)
        await checkpoint(world)
        session = world.ctx.userdata
        offering = object()
        session.fate_offer = offering
        assert not active(world).ally_continuation and not active(world).held_actions
        before = await snapshot(world)
        with pytest.raises(ToolError, match="partially resolved"):
            await call("activate", id=ability, **args)
        assert session.fate_offer is offering
        assert await snapshot(world) == before
        session.fate_offer = None


@pytest.mark.parametrize("tool", ["activate", "learn"])
async def test_unrelated_commands_still_settle_fate(world, tool):
    async with fight(world, guest="zhael") as call:
        position(world)
        await checkpoint(world)
        await declare(world, call, attack(world.ids[0], FOE))
        with rolls(18):
            result = await call("resolve_phase")
            assert "fate_offer" in result and active(world).ally_continuation
            args = {"id": "mortaen_speak_with_dead"} if tool == "activate" else {"id": GIFT, "kind": "unknown"}
            with pytest.raises(ToolError, match="settled_fate"):
                await call(tool, **args)
        assert world.ctx.userdata.fate_offer is None
        assert (await row(world, 0))["patron_gifts"] == {"mortaen_speak_with_dead": {"spent": True}}


async def outgoing_spell(world, protected):
    async with fight(world, archetype="mage") as call:
        host = world.ids[0]
        await character_spells.record_learned(host, "arcane_bolt", "training", is_prepared=True, conn=world.pool)
        position(world)
        foe = participant(active(world), FOE)
        foe.hp_current = foe.hp_max = 100
        foe.damage_affinities = {"immune": [], "resistant": [], "vulnerable": ["necrotic"]}
        await checkpoint(world)
        if protected:
            await walk(call)
            action = {
                "kind": "ability",
                "actor_id": host,
                "action": "arcane_bolt",
                "targets": [FOE],
                "argument_type": "",
            }
        else:
            action = attack(host, FOE)
        await declare(world, call, action)
        with rolls(5, 18) if protected else rolls(18):
            packets, _ = await drain(world, call)
        packet = next(p for p in packets if p["actor_id"] == host)
        damage = packet["cast"]["damage_result"] if protected else packet
        assert (damage["damage_type"], damage["damage"]) == (
            "force" if protected else "slashing",
            14 if protected else 10,
        )
        assert attack_event(world, "Rook")["roll"] == 18
        assert participant(active(world), FOE).hp_current == (86 if protected else 90)


@pytest.mark.parametrize("archetype,stage", [("mage", "pre_roll"), ("rogue", "post_roll")])
async def test_reaction_holds_refuse_walk(world, archetype, stage):
    async with fight(world, archetype=archetype) as call:
        position(world)
        await checkpoint(world)
        await declare(world, call, claw(world))
        with rolls(18):
            for _ in range(4):
                await call("resolve_phase")
                if active(world).open_window and active(world).open_window["stage"] == stage:
                    break
            else:
                pytest.fail(f"No {stage} reaction")
            before = await snapshot(world)
            assert active(world).held_actions and active(world).ally_continuation is None
            with pytest.raises(ToolError, match="partially resolved"):
                await call("activate", id=GIFT)
            assert await snapshot(world) == before
            await drain(world, call)
        await walk(call)


async def prepared_weapon(world):
    async with fight(world, guest="zhael") as call:
        host, guest = world.ids
        position(world)
        foe = participant(active(world), FOE)
        foe.hp_current = foe.hp_max = 100
        foe.damage_affinities["vulnerable"] = ["necrotic"]
        await checkpoint(world)
        await walk(call)
        await declare(world, call, attack(host, FOE))
        with rolls(5, 18, 7, 17):
            result = await call("resolve_phase")
            offer = result["fate_offer"]
            assert offer["die"] == 18
            await snapshot(world)
            assert participant(active(world), FOE).hp_current == 100
            with world.ctx.userdata._bind_authenticated_actor(guest, 4, lambda *_: None):
                args = {"id": "zhael_fates_thread", "offer_id": offer["offer_id"]}
                await call("activate", **args)
                kept = await call("activate", **args, keep="original")
        packet = next(p for p in kept["packets"] if p["actor_id"] == host)
        assert (packet["damage_type"], packet["damage"]) == ("necrotic", 20)
        await snapshot(world)
        assert participant(active(world), FOE).hp_current == 80


@pytest.mark.parametrize("invalid", ["missing", "enemy", "fallen", "dead", "zero_hp"])
async def test_walk_requires_a_standing_player(world, invalid):
    async with fight(world, hp=0 if invalid == "zero_hp" else 100) as call:
        follower_row = follower(world)
        if invalid == "missing":
            state = active(world)
            state.participants.remove(follower_row)
            state.initiative_order.remove(follower_row.id)
            for field in ("positions", "speeds"):
                del state.spatial[field][follower_row.id]
        if invalid == "enemy":
            follower_row.type = "enemy"
        if invalid == "fallen":
            follower_row.is_fallen = True
        if invalid == "dead":
            follower_row.is_dead = True
        await checkpoint(world)
        before = await snapshot(world)
        reason = "requires the acting player" if invalid in ("missing", "enemy") else "fallen or dead"
        with pytest.raises(ToolError, match=reason):
            await call("activate", id=GIFT)
        assert await snapshot(world) == before


async def held_lethal(world, fate):
    async with fight(world, hp=3, archetype="rogue", guest="zhael" if fate else "aelora") as call:
        position(world)
        target = claw(world, damage_type="fire", magical=True)
        await checkpoint(world)
        await walk(call)
        await declare(world, call, target)
        with rolls(18, 15):
            for _ in range(5):
                result = await call("resolve_phase")
                if "fate_offer" in result:
                    await snapshot(world)
                    assert active(world).held_actions[0]["fate_attack"]["prepared"]["original"]["roll"] == 15
                    break
                if active(world).open_window:
                    break
            else:
                pytest.fail("Hostile attack did not pause")
            if fate:
                guest = world.ids[1]
                with world.ctx.userdata._bind_authenticated_actor(guest, 4, lambda *_: None):
                    await call(
                        "activate", id="zhael_fates_thread", offer_id=result["fate_offer"]["offer_id"], keep="original"
                    )
            saved = await snapshot(world)
            assert saved[0]["hp"]["current"] == 3
            head = active(world).held_actions[0]
            assert active(world).open_window["stage"] == "post_roll"
            rolled = head["roll"]["attack_result"]
            assert (rolled["damage"], rolled["target_hp_remaining"], rolled["target_killed"], rolled["overkill"]) == (
                10,
                1,
                False,
                0,
            )
            event = attack_event(world, participant(active(world), FOE).name)
            assert event["roll"] == 15 and event["context"] != "killing_blow"
            if not fate:
                with world.ctx.userdata._bind_authenticated_actor(world.ids[0], 4, lambda *_: None):
                    await call("activate", id="rogue_uncanny_dodge")
                assert active(world).held_actions
            packets, _ = await drain(world, call)
        [receipt] = [p for p in packets if p["actor_id"] == FOE]
        assert (receipt["damage"], receipt["target_fallen"]) == (10 if fate else 5, False)
        assert receipt["context"] != "killing_blow"
        await survivor(world)


SCENARIOS = {
    GIFT: (
        "patron_combat_edges:threshold_walk",
        scenario,
        [
            (walk_outside_combat,),
            *(
                (weapon_exchange, dtype, magical)
                for dtype in ("slashing", "piercing", "bludgeoning")
                for magical in (False, True)
            ),
            (inner_fire,),
            *((lethal_claw, shape) for shape in ("attack", "save", "hit_then_save")),
            (lethal_claw, "save", False),
            (lethal_claw, "attack", True, True),
            (expiry, False),
            (expiry, True),
            (early_end,),
            (outgoing_spell, True),
            (outgoing_spell, False),
            (prepared_weapon,),
            (incoming_spell, "arcane_fireball", "fire"),
            (incoming_spell, "arcane_magic_missile", "force"),
            (incoming_spell, "primal_ice_storm", "cold"),
            (field_damage, "hollow_mawling_pack", "mawling_pack_adult"),
            (field_damage, "hollow_veilrender_boss", "veilrender"),
            (reflected_bolt,),
            (serenity_touch,),
            (held_lethal, False),
            (held_lethal, True),
            (lethal_claw, "attack", True, False, 100),
        ],
    ),
}
