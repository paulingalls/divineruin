from contextlib import AsyncExitStack
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from _patron_engine_fixtures import configure
from _unbound_path_fixtures import world as world
from _zhael_fate_fixtures import game_tools
from acceptance._capstone_helpers import _d20
from combat.test_spell_damage_lands import spell_fight as spell_fight
from sample_fixtures import published_payloads
from test_aelora_gift import _live_party
from voice_condition_fixtures import participant

import world_season
from check_tools import check
from rules_engine import SKILLS

MIGRATIONS = Path(__file__).resolve().parents[3] / "scripts" / "migrations"


@pytest.mark.parametrize("upgrade", [False, True])
async def test_world_season_migration(dev_db_pool, upgrade):
    files = sorted(MIGRATIONS.glob("*.sql"))
    season_migration = MIGRATIONS / "066_world_season.sql"
    schema = f"season_{uuid4().hex}"
    async with dev_db_pool.acquire() as conn:
        transaction = conn.transaction()
        await transaction.start()
        try:
            await conn.execute(f'CREATE SCHEMA "{schema}"')
            await conn.execute(f'SET LOCAL search_path TO "{schema}"')
            for path in files:
                if upgrade and path == season_migration:
                    with pytest.raises(ValueError, match="season"):
                        await world_season.current_season(conn=conn)
                    await conn.execute("INSERT INTO world_flags (flag_name, data) VALUES ('unrelated', '{}')")
                await conn.execute(path.read_text())
            assert await world_season.current_season(conn=conn) == "spring"
            if upgrade:
                assert await conn.fetchval("SELECT data::text FROM world_flags WHERE flag_name = 'unrelated'") == "{}"
            for season in ("summer", "autumn", "winter", "spring"):
                await conn.execute(
                    "UPDATE world_flags SET data = jsonb_build_object('value', $1::text) WHERE flag_name = 'season'",
                    season,
                )
                assert await world_season.current_season(conn=conn) == season
            for invalid in ("{}", '{"value":null}', '{"value":"monsoon"}'):
                await conn.execute("UPDATE world_flags SET data = $1::jsonb WHERE flag_name = 'season'", invalid)
                with pytest.raises(ValueError, match="season"):
                    await world_season.current_season(conn=conn)
            await conn.execute("DELETE FROM world_flags WHERE flag_name = 'season'")
            with pytest.raises(ValueError, match="season"):
                await world_season.current_season(conn=conn)
        finally:
            await transaction.rollback()


THYRA = {"patron": "thyra", "level": 0, "max": 100}


async def seasonal_skill(world, season, skill, patron, bonus):
    session = world.ctx.userdata
    await configure(world, patron, "mage", divine_favor={**THYRA, "patron": patron})
    async with AsyncExitStack() as stack:
        if patron != "thyra":
            await configure(world, "thyra", "mage", index=1, divine_favor=THYRA)
            stack.push_async_callback(_live_party(session, *world.ids).aclose)
            assert session.allies_present_for(world.ids[0]) == 1
        call = game_tools(session, check)
        with (
            patch.object(world_season, "current_season", new=AsyncMock(return_value=season)),
            patch("check_resolution.dice_roll", return_value=_d20(11)),
        ):
            packet = await call(
                "check",
                roll={
                    "kind": "skill",
                    "skill": skill,
                    "difficulty": "moderate",
                    "context_description": "Read the situation",
                    "hearing_only": False,
                },
            )
    event = [p for p in published_payloads(session.room) if p["type"] == "dice_roll"][-1]
    assert (packet["modifier"], packet["total"], event["total"]) == (bonus, 11 + bonus, 11 + bonus)


SCENARIOS = {
    "thyra_seasonal_attunement": (
        "thyra_seasons:skill_bonus",
        seasonal_skill,
        [
            (season, skill, "thyra", int(skill == active))
            for season, active in (("autumn", "insight"), ("winter", "stealth"))
            for skill in SKILLS
        ]
        + [(season, skill, "thyra", 0) for season in ("spring", "summer") for skill in ("insight", "stealth")]
        + [("autumn", "insight", "veythar", 0)],
    ),
}


async def test_patron_query_reports_active_season(dev_db_pool):
    from patron_ability_walk import AbilityWalk

    async with AbilityWalk(dev_db_pool) as walk:
        assert "seasonal_attunement" not in await walk.command("query_info", {"kind": "patron"})
        await walk.patch(divine_favor=THYRA)
        bonuses = {
            "spring": "+1 healing received per heal.",
            "summer": "+1 damage per fire or lightning roll.",
            "autumn": "+1 to Insight checks.",
            "winter": "+1 to Stealth checks.",
        }
        for season, bonus in bonuses.items():
            with patch.object(world_season, "current_season", new=AsyncMock(return_value=season)):
                receipt = await walk.command("query_info", {"kind": "patron"})
            assert receipt["seasonal_attunement"] == {
                "id": "thyra_seasonal_attunement",
                "season": season,
                "active_bonus": bonus,
            }


@pytest.mark.parametrize(
    "source,combat,season,standing,hp,healed",
    [
        ("spell", False, "spring", THYRA, 3, 6),
        ("spell", True, "spring", THYRA, 3, 6),
        ("item", False, "spring", THYRA, 3, 6),
        ("item", True, "spring", THYRA, 3, 6),
        ("spell", False, "spring", THYRA, 16, 4),
        ("spell", True, "spring", THYRA, 16, 4),
        ("item", False, "summer", THYRA, 3, 5),
        ("spell", False, "autumn", THYRA, 3, 5),
        ("item", True, "winter", THYRA, 3, 5),
        ("item", True, "spring", None, 3, 5),
        ("spell", False, "spring", {"patron": "none", "level": 0, "max": 100}, 3, 5),
        ("spell", True, "spring", {**THYRA, "level": 90}, 3, 6),
    ],
)
async def test_spring_healing_lands_on_the_recipient(dev_db_pool, source, combat, season, standing, hp, healed):
    from _item_heal_fixtures import ItemHealWalk, heal_roll
    from _spell_heal_fixtures import WOUNDS

    async with ItemHealWalk(dev_db_pool) as walk:
        if source == "spell":
            await walk.prepare(WOUNDS, wisdom=10)
            await walk.patch(divine_favor={**THYRA, "patron": "aelora"})
        else:
            await walk.put()
        ally = await walk.add_player(hp=hp)
        await walk.patch_row(ally, divine_favor=standing)
        if standing is None:
            await walk.patch(divine_favor=THYRA)
        if combat:
            await walk.fight()
        with patch.object(world_season, "current_season", new=AsyncMock(return_value=season)), heal_roll(5):
            if source == "spell":
                result = await walk.cast(WOUNDS, targets=[ally], combat=combat)
            elif combat:
                await walk.declare_item(target=ally)
                result = await walk.resolve_item()
            else:
                result = await walk.consume(target=ally)
        effect = result["healing_results"][0]
        assert (effect["target_id"], effect["healed"], effect["hp_current"]) == (ally, healed, hp + healed)
        assert (await walk.read(ally))["hp"]["current"] == hp + healed
        events = published_payloads(walk.sd.room)
        if combat:
            assert participant(await walk.checkpoint(), ally).hp_current == hp + healed
            tracker = [event for event in events if event["type"] == "combat_ui_update"][-1]
            assert next(p["hpCurrent"] for p in tracker["combatants"] if p["id"] == ally) == hp + healed
        else:
            assert any(event["type"] == "hp_changed" and event["current"] == hp + healed for event in events)


async def test_spring_regenerate_surge_tick_and_settle(dev_db_pool):
    from _spell_heal_fixtures import REGENERATE, HealWalk
    from test_heal_over_time import declare_defend, effects, heal_die, regeneration

    async with HealWalk(dev_db_pool) as walk:
        await walk.prepare(REGENERATE)
        ally = await walk.add_player(hp=3, maximum=40)
        await walk.patch_row(ally, divine_favor=THYRA)
        state = await walk.fight()
        participant(state, ally).initiative = participant(state, walk.player).initiative + 1
        with patch.object(world_season, "current_season", new=AsyncMock(return_value="spring")), heal_die(19):
            cast = await walk.cast(REGENERATE, targets=[ally], combat=True)
            assert cast["healing_results"][0]["healed"] == 20
            await declare_defend(walk, walk.player, ally)
            assert [(e["healed"], e["hp_current"]) for e in effects(await walk.wrap())] == [(2, 25)]
            regeneration(participant(walk.fight_state, ally))[0]["ticks_remaining"] = 2
            await walk.save()
            await walk.register_end()
            await walk.command("end_combat", {"outcome": "fled"})
            assert (await walk.read(ally))["hp"]["current"] == 29


@pytest.mark.parametrize(
    "spell_id,season,face,rolled,resistant,mixed,expected,patron",
    [
        ("arcane_fireball", "summer", 1, 7, False, False, [8], "thyra"),
        ("arcane_lightning_bolt", "summer", 1, 7, False, False, [8], "thyra"),
        ("arcane_elemental_burst", "summer", 1, 7, False, False, [7], "thyra"),
        ("arcane_fireball", "summer", 1, 7, False, True, [8, 7], "thyra"),
        ("arcane_fireball", "summer", 1, 6, True, False, [3], "thyra"),
        ("arcane_fireball", "summer", 20, 6, False, False, [3], "thyra"),
        ("arcane_fireball", "spring", 1, 7, False, False, [7], "thyra"),
        ("arcane_fireball", "autumn", 1, 7, False, False, [7], "thyra"),
        ("arcane_fireball", "winter", 1, 7, False, False, [7], "thyra"),
        pytest.param("arcane_fireball", "summer", 1, 7, False, False, [7], "aelora", id="other_patron"),
        ("primal_produce_flame", "summer", 15, 7, False, False, [8], "thyra"),
        ("primal_produce_flame", "summer", 1, 7, False, False, [0], "thyra"),
        ("divine_flame_strike", "summer", 1, 7, False, False, [8, 7], "thyra"),
    ],
)
async def test_summer_spell_damage(
    spell_fight, dev_db_pool, spell_id, season, face, rolled, resistant, mixed, expected, patron
):
    import json
    from dataclasses import replace
    from types import SimpleNamespace

    from _zhael_fate_fixtures import defend
    from combat.test_spell_damage_lands import load_combat, prepare_spell

    import spells
    from combat_spell_profile import parse_profile
    from combat_turn import declare_phase, resolve_phase

    ctx = spell_fight
    pid = ctx.userdata.player_id
    await dev_db_pool.execute(
        "UPDATE players SET data = jsonb_set(data, '{divine_favor}', $2::jsonb) WHERE player_id = $1",
        pid,
        json.dumps({**THYRA, "patron": patron}),
    )
    spell = await prepare_spell(ctx, spell_id)
    state = ctx.userdata.combat_state
    participant(state, pid).attributes = {}
    target = participant(state, "foe")
    state.spatial["positions"]["foe"]["x"] = 40
    if resistant:
        target.damage_affinities = {"resistant": ["fire"]}
    replacement = spell
    profile = spell.combat_damage
    assert profile is not None
    if mixed:
        replacement = replace(
            spell,
            combat_damage=parse_profile(
                {**profile, "components": [*profile["components"], {"dice": "1d6", "damage_type": "cold"}]}
            ),
        )
    get_spell = spells.get_spell
    with (
        patch.object(spells, "get_spell", side_effect=lambda key: replacement if key == spell_id else get_spell(key)),
        patch.object(world_season, "current_season", new=AsyncMock(return_value=season)),
        patch("check_resolution.dice_roll", return_value=_d20(face)),
        patch("dice.roll", return_value=SimpleNamespace(total=rolled)),
        patch("check_resolution_attack.dice_roll", return_value=SimpleNamespace(total=rolled)),
    ):
        call = game_tools(ctx.userdata, declare_phase, resolve_phase)
        strike = {
            **defend(pid),
            "kind": "ability",
            "action": spell_id,
            "targets": ["foe"],
            "argument_type": "cold" if spell_id == "arcane_elemental_burst" else "",
        }
        await call("declare_phase", declarations=[strike, defend("foe")])
        result = await call("resolve_phase")
    damage = next(p["cast"]["damage_result"] for p in result["packets"] if p["actor_id"] == pid)
    assert damage["damage"] == sum(expected)
    if profile["resolution"] != "attack":
        assert [part["damage"] for part in damage["damage_components"]] == expected
    saved = await load_combat(state.combat_id)
    assert participant(saved, "foe").hp_current == 100 - sum(expected)


async def test_spring_dawns_embrace_restores_the_recipient(world):
    from _dawns_embrace_fixtures import aim, embrace_fight, rolls
    from test_patron_engine_dawns_embrace import caught
    from test_patron_engine_death_ward import enemy_damage, resolve_until

    import combat_hold

    async with embrace_fight(world, patron="thyra", archetype="rogue") as call:
        await aim(world, call, world.ids[0])
        with (
            patch.object(world_season, "current_season", new=AsyncMock(return_value="spring")),
            patch.object(
                combat_hold, "build_attack_dice_roll_payload", wraps=combat_hold.build_attack_dice_roll_payload
            ) as preview,
            rolls(15, 15, 7, damage=10),
        ):
            await resolve_until(call, lambda r: (r["next"].get("waiting_on") or {}).get("stage") == "post_roll")
            assert preview.call_args.args[1].target_hp_remaining == 11
            receipt = await resolve_until(call, enemy_damage)
        await caught(world, world.ids[0], receipt, 11)


async def test_autumn_discovery_uses_insight_modifier(dev_db_pool):
    from _unbound_path_fixtures import MilestoneWalk

    async with MilestoneWalk(dev_db_pool) as walk:
        await walk.patch(divine_favor=THYRA, attributes={}, skill_proficiencies=[])
        with (
            patch.object(world_season, "current_season", new=AsyncMock(return_value="autumn")),
            patch("check_resolution.dice_roll", return_value=_d20(11)),
        ):
            receipt = await walk.command(
                "check",
                {"roll": {"kind": "discover", "skill": "insight", "target": "innkeeper", "hearing_only": False}},
            )
        event = next(p for p in published_payloads(walk.sd.room) if p["type"] == "dice_roll")
        assert (receipt["modifier"], receipt["total"], event["total"]) == (1, 12, 12)


@pytest.mark.parametrize("kind", ["second_wind", "hide"])
async def test_seasonal_martial_ability(dev_db_pool, kind):
    from _spell_heal_fixtures import HealWalk
    from _zhael_fate_fixtures import attack, defend
    from acceptance._capstone_helpers import _damage_die

    healing = kind == "second_wind"
    async with HealWalk(dev_db_pool) as walk:
        cls = "warrior" if healing else "rogue"
        await walk.patch(
            **{"class": cls},
            level=6,
            divine_favor=THYRA,
            attributes={},
            skill_proficiencies=[],
            hp={"current": 3, "max": 30},
            stamina={"current": 10, "max": 10},
        )
        state = await walk.fight()
        actor = participant(state, walk.player)
        actor.level, actor.archetype_id = 6, cls
        await walk.save()
        declaration = (
            {**defend(walk.player), "kind": "ability", "action": "warrior_second_wind"}
            if healing
            else {**attack(walk.player, "foe"), "rider": "hide"}
        )
        args = {"declarations": [declaration, defend("foe")]}
        await walk.command("declare_phase", args)
        with (
            patch.object(world_season, "current_season", new=AsyncMock(return_value="spring" if healing else "winter")),
            patch("check_resolution.dice_roll", side_effect=[_d20(15), _d20(9)]),
            patch("dice.roll", return_value=_damage_die(7)),
            patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
        ):
            packet = next(p for p in await walk.wrap() if p["actor_id"] == walk.player)
        row = await walk.row()
        if healing:
            assert (packet["healed"], row["hp"]["current"], row["stamina"]["current"]) == (14, 17, 6)
            assert participant(await walk.checkpoint(), walk.player).hp_current == 17
            assert "Second Wind" in await walk.command("declare_phase", args, error=True)
        else:
            assert (packet["cunning_action"]["roll"], packet["cunning_action"]["dc"]) == (9, 10)
            assert row["flags"]["concealed"] and row["stamina"]["current"] == 8


async def test_spring_respects_rest_hp_rules(dev_db_pool):
    from patron_ability_walk import AbilityWalk

    async with AbilityWalk(dev_db_pool) as walk:
        await walk.patch(divine_favor=THYRA, hp={"current": 3, "max": 20})
        with patch.object(world_season, "current_season", new=AsyncMock(return_value="spring")):
            for rest_type, hp in [("short", 3), ("long", 20)]:
                await walk.command("rest", {"rest_type": rest_type})
                assert (await walk.row())["hp"] == {"current": hp, "max": 20}


@pytest.mark.parametrize("revival", ["natural_20", "stabilize"])
async def test_spring_preserves_one_hp_transitions(dev_db_pool, revival):
    from _spell_heal_fixtures import HealWalk

    from combat_death_save import request_death_save

    async with HealWalk(dev_db_pool) as walk:
        await walk.patch(divine_favor=THYRA, hp={"current": 0, "max": 20})
        state = await walk.fight()
        participant(state, walk.player).is_fallen = True
        await walk.save()
        with patch.object(world_season, "current_season", new=AsyncMock(return_value="spring")):
            if revival == "natural_20":
                call = game_tools(walk.sd, request_death_save)
                with patch("combat_resolution.dice_roll", return_value=_d20(20)):
                    assert (await call("request_death_save"))["revived"]
                assert participant(await walk.checkpoint(), walk.player).hp_current == 1
            else:
                await walk.register_end()
                await walk.command("end_combat", {"outcome": "victory"})
        assert (await walk.row())["hp"] == {"current": 1, "max": 20}


@pytest.mark.parametrize("critical", [True, False])
async def test_summer_does_not_change_the_physical_weapon_component(world, critical):
    from acceptance._capstone_helpers import _damage_die
    from combat.test_synergy_crit_edges import fight, saved_hp, weapon_round

    await configure(world, "thyra", "warrior")
    async with fight(world, ac=10) as state:
        with patch.object(world_season, "current_season", new=AsyncMock(return_value="summer")):
            packet, _ = await weapon_round(
                world, face=20 if critical else 15, damage=[_damage_die(5)] * 2 + [_damage_die(3)]
            )
        expected = 14 if critical else 5
        assert packet["damage"] == expected and await saved_hp(state) == 100 - expected
        assert (packet.get("synergy_damage", 0), packet.get("synergy_damage_type")) == (
            (4, "lightning") if critical else (0, None)
        )


@pytest.mark.parametrize("cast", [True, False])
async def test_summer_attack_roll_survives_fate_checkpoint(world, cast):
    from _zhael_fate_fixtures import attack, defend
    from acceptance._capstone_helpers import _damage_die
    from combat.test_synergy_crit_edges import fight, saved_hp

    import character_spells
    import db_mutations
    from activate_tools import activate
    from combat_turn import declare_phase, resolve_phase

    host, guest = world.ids
    await configure(world, "thyra", "druid" if cast else "warrior")
    await configure(world, "zhael", "mage", index=1)
    if cast:
        await character_spells.record_learned(
            host, "primal_produce_flame", "training", is_prepared=True, conn=world.pool
        )
    async with fight(world, ac=10, ally=True) as state:
        session = world.ctx.userdata
        lifecycle = _live_party(session, host, guest)
        call = game_tools(session, declare_phase, resolve_phase, activate)
        strike = (
            {**defend(host), "kind": "ability", "action": "primal_produce_flame", "targets": ["foe"]}
            if cast
            else attack(host, "foe")
        )
        try:
            await call("declare_phase", declarations=[strike, defend(guest), defend("foe")])
            season = AsyncMock(return_value="summer")
            with (
                patch.object(world_season, "current_season", new=season),
                patch("check_resolution.dice_roll", return_value=_d20(15 if cast else 20)),
                patch("check_resolution_attack.dice_roll", return_value=_damage_die(7)),
                patch("patron_synergy_combat.dice_roll", return_value=_damage_die(3)),
            ):
                offer = (await call("resolve_phase"))["fate_offer"]
                assert offer["roller_id"] == host and guest in offer["eligible_followers"]
                assert await saved_hp(state) == 100
                session.combat_state = await db_mutations.load_combat_state(state.combat_id)
                season.return_value = "spring"
                with session._bind_authenticated_actor(guest, 1, lifecycle.require_authorized):
                    result = await call(
                        "activate", id="zhael_fates_thread", offer_id=offer["offer_id"], keep="original"
                    )
            packet = next(p for p in result["packets"] if p["actor_id"] == host)
            damage = packet["cast"]["damage_result"] if cast else packet
            expected = 8 if cast else 18
            assert damage["damage"] == expected and await saved_hp(state) == 100 - expected
        finally:
            await lifecycle.aclose()


async def test_summer_inner_fire_counts_the_casters_fire_roll(world):
    from _dawns_embrace_fixtures import damage_ally, embrace_fight
    from _mortaen_threshold_fixtures import active
    from _unbound_path_fixtures import row
    from test_patron_engine_death_ward import saved_target

    async with embrace_fight(world, patron="thyra", hp=20) as call:
        with patch.object(world_season, "current_season", new=AsyncMock(return_value="summer")):
            receipt = await damage_ally(world, call, inner=True, damage=7)
        assert (receipt["fire_damage"], receipt["hp_remaining"]) == (8, 12)
        assert (await row(world, 0))["hp"]["current"] == 12
        assert (await saved_target(world, participant(active(world), world.ids[0]))).hp_current == 12
