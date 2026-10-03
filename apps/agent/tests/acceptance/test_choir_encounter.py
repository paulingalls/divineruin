import json
from unittest.mock import patch

import pytest
from acceptance._capstone_helpers import _d20, _resolve_round
from acceptance._catalog_cutover_helpers import started as started
from livekit.agents.llm import ToolError
from sample_fixtures import make_context

import combat_end
import combat_turn
import db_mutations
import mode_tools


async def search(ctx, skill="arcana", face=20):
    state = ctx.userdata.combat_state
    declarations = {p.id: {"type": "defend"} for p in state.participants if not p.is_fallen}
    declarations[ctx.userdata.player_id] = {
        "type": "interact",
        "action": f"choir_search_{skill}",
        "target_id": "choir_sound",
    }
    await combat_turn._declare_phase_impl(ctx, declarations)
    with patch("check_resolution.dice_roll", return_value=_d20(face)):
        return await _resolve_round(ctx)


async def test_choir_live_victory_refused_without_effects(started):
    ctx, _ = await started("hollow_choir")
    for phase in ["search", "exposed"]:
        before = ctx.userdata.combat_state.to_dict()
        ctx.userdata.room.local_participant.publish_data.reset_mock()
        with pytest.raises(ToolError, match="destroyed"):
            await combat_end._end_combat_impl(ctx, "victory")
        assert ctx.userdata.combat_state.to_dict() == before
        saved = await db_mutations.load_combat_state(before["combat_id"])
        assert saved is not None and saved.to_dict() == before
        ctx.userdata.room.local_participant.publish_data.assert_not_called()
        if phase == "search":
            await search(ctx)


async def test_choir_flee_reload_reentry_preserves_owner(started):
    ctx, _ = await started("hollow_choir", player_class="mage")
    await search(ctx)
    await bolt(ctx)
    assert ctx.userdata.combat_state.get_participant("choir_zone").hp_current < 200
    before = ctx.userdata.combat_state.to_dict()
    await combat_end._end_combat_impl(ctx, "fled")
    fresh = make_context(ctx.userdata.player_id, room=ctx.userdata.room)
    fresh.userdata.location_id = before["location_id"]
    _, raw = await mode_tools._enter_mode_impl(fresh, "combat", "hollow_choir", "voices return")
    assert json.loads(raw)["choir"]["phase"] == "exposed"
    enemy = fresh.userdata.combat_state.get_participant("choir_zone")
    original = next(p for p in before["participants"] if p["id"] == enemy.id)
    assert enemy.hp_current == original["hp_current"]
    assert fresh.userdata.combat_state.choir_encounter["phase"] == "exposed"


async def test_choir_discovery_rollback_is_invisible(started, monkeypatch):
    ctx, _ = await started("hollow_choir")
    before = ctx.userdata.combat_state.to_dict()
    pid = ctx.userdata.player_id
    await combat_turn._declare_phase_impl(
        ctx,
        {
            pid: {"type": "interact", "action": "choir_search_arcana", "target_id": "choir_sound"},
            "choir_zone": {"type": "defend"},
        },
    )
    declared = ctx.userdata.combat_state.to_dict()
    ctx.userdata.room.local_participant.publish_data.reset_mock()
    original = db_mutations.save_combat_state

    async def fail(*args, **kwargs):
        await original(*args, **kwargs)
        raise RuntimeError("injected persist failure")

    with monkeypatch.context() as m, patch("check_resolution.dice_roll", return_value=_d20(20)):
        m.setattr(db_mutations, "save_combat_state", fail)
        with pytest.raises(RuntimeError, match="injected"):
            await combat_turn._resolve_phase_impl(ctx)
    assert ctx.userdata.combat_state.to_dict() == declared
    saved = await db_mutations.load_combat_state(before["combat_id"])
    assert saved is not None and saved.to_dict() == declared
    ctx.userdata.room.local_participant.publish_data.assert_not_called()
    with patch("check_resolution.dice_roll", return_value=_d20(20)):
        await _resolve_round(ctx)
    assert ctx.userdata.combat_state.choir_encounter["phase"] == "exposed"


async def bolt(ctx, face=20):
    state = ctx.userdata.combat_state
    declarations = {p.id: {"type": "defend"} for p in state.participants if not p.is_fallen}
    declarations[ctx.userdata.player_id] = {"type": "ability", "action": "arcane_bolt", "target_id": "choir_zone"}
    await combat_turn._declare_phase_impl(ctx, declarations)
    with patch("check_resolution.dice_roll", return_value=_d20(face)):
        return await _resolve_round(ctx)


@pytest.mark.parametrize("face,redirect", [(20, False), (10, False), (20, True)])
async def test_choir_real_spell_lands_on_core(started, face, redirect):
    from types import SimpleNamespace

    import check_resolution_attack
    import db_queries
    from rules_engine import attribute_modifier, proficiency_bonus

    ctx, _ = await started("hollow_choir", player_class="mage")
    await search(ctx)
    pid = ctx.userdata.player_id
    before = await db_queries.get_player(pid)
    assert before is not None
    state = ctx.userdata.combat_state
    recipient = state.get_participant(pid if redirect else "choir_zone")
    hp_before = recipient.hp_current
    effective_ac = recipient.ac + (0 if redirect else 2)
    with (
        patch("check_resolution_attack.resolve_attack", wraps=check_resolution_attack.resolve_attack) as attack,
        patch("check_resolution_save.roll_participant_save", return_value=SimpleNamespace(success=not redirect)),
    ):
        result = await bolt(ctx, face)
    packet = next(p for p in result["packets"] if p["actor_id"] == pid)
    damage = packet["cast"]["damage_result"]
    modifier = attribute_modifier(before["attributes"]["intelligence"]) + proficiency_bonus(16)
    assert damage["attack_total"] == face + modifier
    assert damage["target_ac"] == effective_ac
    assert state.get_participant("choir_zone").ac == 18
    assert damage["hit"] is (face + modifier >= effective_ac)
    assert attack.call_args.args[1]["damage"] == "3d6"
    assert attack.call_args.args[1]["governing_attribute"] == "intelligence"
    assert packet["cast"]["target_id"] == recipient.id
    saved = await db_mutations.load_combat_state(state.combat_id)
    assert saved is not None
    target = saved.get_participant(recipient.id)
    assert target is not None and target.hp_current == hp_before - damage["damage"]
    assert damage["damage"] > 0 if damage["hit"] else damage["damage"] == 0
    if redirect:
        core = saved.get_participant("choir_zone")
        assert core is not None and core.hp_current == 200
    after = await db_queries.get_player(pid)
    assert after is not None and after["focus"] == before["focus"]


async def test_choir_core_destroyed_cleans_scene_and_rewards_once(started, monkeypatch):
    from unittest.mock import AsyncMock

    import choir_scene
    import combat_hollow_death
    import combat_rewards
    import db_queries

    death = AsyncMock(wraps=combat_hollow_death.accrue_death)
    rewards = AsyncMock(wraps=combat_rewards.grant_victory_rewards)
    monkeypatch.setattr(combat_hollow_death, "accrue_death", death)
    monkeypatch.setattr(combat_rewards, "grant_victory_rewards", rewards)
    ctx, _ = await started("hollow_choir", player_class="mage")
    await search(ctx)
    pid = ctx.userdata.player_id
    combat_id = ctx.userdata.combat_state.combat_id
    before = await db_queries.get_player(pid)
    assert before is not None
    for _round_index in range(30):
        result = await bolt(ctx)
        if isinstance(result, tuple):
            break
    else:
        raise AssertionError("core survived thirty rounds of legal Arcane Bolt")
    outcome = json.loads(result[1])
    assert outcome["outcome"] == "victory"
    assert outcome["xp_total"] == 3000
    assert outcome["choir"]["phase"] == "destroyed"
    assert "core_id" not in outcome["choir"]
    assert "stolen voice" in outcome["choir"]["cue"]
    assert ctx.userdata.combat_state is None
    assert await db_mutations.load_combat_state(combat_id) is None
    after = await db_queries.get_player(pid)
    assert after is not None
    assert after["xp"] - before["xp"] == 3000
    assert after["resonance"]["current"] - before.get("resonance", {}).get("current", 0) == 5
    death.assert_awaited_once()
    rewards.assert_awaited_once()
    assert len(rewards.call_args.args[0]) == 2
    scene = await choir_scene.load(ctx.userdata)
    assert scene is not None and scene["status"] == "destroyed"
    assert await choir_scene.facts(ctx.userdata) is None
    from unittest.mock import MagicMock

    import combat_init

    roll = MagicMock(wraps=combat_init.combat_resolution.roll_initiative)
    monkeypatch.setattr(combat_init.combat_resolution, "roll_initiative", roll)
    fresh = make_context(pid, room=ctx.userdata.room)
    try:
        with pytest.raises(ToolError, match="destroyed"):
            await mode_tools._enter_mode_impl(fresh, "combat", "hollow_choir", "replay")
    finally:
        roll.assert_not_called()
    with pytest.raises(ToolError, match="Not in combat"):
        await combat_end._end_combat_impl(ctx, "victory")
    replayed = await db_queries.get_player(pid)
    assert replayed == after
    death.assert_awaited_once()
    rewards.assert_awaited_once()


async def test_choir_scene_real_checks_use_disadvantage(started):
    from check_discovery import _check_discover_impl
    from check_tools import _check_skill_impl
    from scene_tools import _enter_location_impl

    ctx, _ = await started("hollow_choir")
    await search(ctx)
    await combat_end._end_combat_impl(ctx, "fled")
    fresh = make_context(ctx.userdata.player_id, room=ctx.userdata.room)
    scene = json.loads(await _enter_location_impl(fresh, ctx.userdata.location_id))
    assert scene["choir"]["encounter_id"] == "hollow_choir"
    for skill in ["perception", "insight", "investigation", "arcana"]:
        with patch("check_resolution.dice_roll", side_effect=[_d20(17), _d20(3)]) as rolls:
            raw = await _check_skill_impl(fresh, skill, "moderate", "voices")
        assert json.loads(raw)["roll"] == (17 if skill == "arcana" else 3)
        assert rolls.call_count == (1 if skill == "arcana" else 2)
    with patch("check_resolution.dice_roll", side_effect=[_d20(17), _d20(3)]):
        raw = await _check_discover_impl(fresh, "perception", "voices")
    assert json.loads(raw)["roll"] == 3


COMPANIONS = json.loads(__import__("sample_fixtures").CONTENT_ROOT.joinpath("content/companions.json").read_text())


def test_choir_diagnostic_companion_floor():
    assert len(COMPANIONS) == 4
    assert len({row["id"] for row in COMPANIONS}) == 4


@pytest.mark.parametrize("companion", [row["id"] for row in COMPANIONS])
async def test_choir_level16_actual_companion_diagnostic(started, companion):
    import db_queries
    from companion_profiles import get_companion_profile
    from companion_scaling import companion_attacks_to_action_pool

    ctx, _ = await started("hollow_choir", player_class="mage", companion=companion)
    pid = ctx.userdata.player_id
    player = await db_queries.get_player(pid)
    assert player is not None
    assert player["level"] == 16 and ctx.strength_events
    ally = ctx.userdata.combat_state.get_participant(companion)
    assert ally.action_pool == companion_attacks_to_action_pool(get_companion_profile(companion))
    assert ally.level == 16
    await search(ctx)
    magical_hit = False
    companion_acted = False
    for _round_index in range(30):
        state = ctx.userdata.combat_state
        actor = state.get_participant(pid)
        if actor.hp_current < actor.hp_max / 2:
            result = await combat_end._end_combat_impl(ctx, "fled")
            break
        declarations = {
            pid: {"type": "ability", "action": "arcane_bolt", "target_id": "choir_zone"},
            "choir_zone": {"type": "attack", "action": "Dissonant Chord", "target_id": pid},
        }
        ally = state.get_participant(companion)
        if not ally.is_fallen:
            declarations[companion] = {
                "type": "attack",
                "action": ally.action_pool[0]["name"],
                "target_id": "choir_zone",
            }
        await combat_turn._declare_phase_impl(ctx, declarations)
        with patch("check_resolution.dice_roll", return_value=_d20(20)):
            result = await _resolve_round(ctx)
        if isinstance(result, tuple):
            break
        magical_hit |= any(p.get("cast", {}).get("damage_result", {}).get("damage", 0) > 0 for p in result["packets"])
        companion_acted |= any(p["actor_id"] == companion and p.get("resolved") for p in result["packets"])
    else:
        raise AssertionError(f"Unbounded Choir diagnostic: {companion} {state.to_dict()}")
    outcome = json.loads(result[1])["outcome"]
    assert outcome in {"victory", "fled", "defeat"}
    assert magical_hit and companion_acted
    assert ctx.userdata.combat_state is None
    print(
        f"Choir level16 {companion}: {outcome}, {_round_index + 1} rounds, legal Arcane Bolt and actual companion actions"
    )


async def test_choir_aura_concentration_member_isolation_reload(started):
    from uuid import uuid4

    from acceptance.seeds import seed_player_with_pools

    import db
    import db_queries
    from party_state import PartyState

    ctx, _ = await started("hollow_choir", player_class="cleric")
    await combat_end._end_combat_impl(ctx, "fled")
    other = "choir_ally_" + uuid4().hex
    pool = await db.get_pool()
    await seed_player_with_pools(pool, player_id=other, class_="cleric", known_spells=("divine_bless",))
    ctx.userdata.party.members.extend(PartyState.solo(other).members)
    try:
        await mode_tools._enter_mode_impl(ctx, "combat", "hollow_choir", "voices")
        pid = ctx.userdata.player_id
        await combat_turn._declare_phase_impl(
            ctx,
            {
                pid: {"type": "ability", "action": "divine_bless", "target_id": pid},
                other: {"type": "ability", "action": "divine_bless", "target_id": other},
                "choir_zone": {"type": "defend"},
            },
        )
        with patch("check_resolution.dice_roll", return_value=_d20(20)):
            await _resolve_round(ctx)
        assert all(m.concentration.spell_id == "divine_bless" for m in ctx.userdata.party.members)
        state = ctx.userdata.combat_state
        state.spatial["positions"][other] = {"x": 631, "y": 0, "z": 0}
        await db_mutations.save_combat_state(state.combat_id, state.to_dict())
        ctx.userdata.combat_state = await db_mutations.load_combat_state(state.combat_id)
        await combat_turn._declare_phase_impl(
            ctx, {pid: {"type": "defend"}, other: {"type": "defend"}, "choir_zone": {"type": "defend"}}
        )
        with patch("check_resolution.dice_roll", return_value=_d20(1)):
            await _resolve_round(ctx)
        assert ctx.userdata.member_state(pid).concentration.spell_id is None
        assert ctx.userdata.member_state(other).concentration.spell_id == "divine_bless"
        primary = await db_queries.get_player(pid)
        assert primary is not None and primary["concentration"]["spell_id"] is None
        other_player = await db_queries.get_player(other)
        assert other_player is not None and other_player["concentration"]["spell_id"] == "divine_bless"
    finally:
        await pool.execute("DELETE FROM players WHERE player_id = $1", other)


async def test_choir_failed_search_consumes_declared_action(started):
    from check_discovery import _check_discover_impl

    ctx, _ = await started("hollow_choir", player_class="mage")
    pid = ctx.userdata.player_id
    await combat_turn._declare_phase_impl(
        ctx,
        {
            pid: {"type": "interact", "action": "choir_search_arcana", "target_id": "choir_sound"},
            "choir_zone": {"type": "defend"},
        },
    )
    with pytest.raises(ToolError, match="beat"):
        await combat_turn._declare_phase_impl(
            ctx, {pid: {"type": "ability", "action": "arcane_bolt", "target_id": "choir_zone"}}
        )
    with patch("check_resolution.dice_roll", return_value=_d20(1)):
        result = await _resolve_round(ctx)
    packet = next(p for p in result["packets"] if p["actor_id"] == pid)
    assert packet["resolved"] and not packet["success"]
    assert ctx.userdata.combat_state.choir_encounter["phase"] == "search"
    with pytest.raises(ToolError, match="declared"):
        await _check_discover_impl(ctx, "perception", "choir_sound")
    assert ctx.userdata.combat_state.get_participant("choir_zone").hp_current == 200


@pytest.mark.parametrize("outcome", ["fled", "victory"])
async def test_choir_end_rollback_preserves_scene_owner_and_rewards(started, monkeypatch, outcome):
    import choir_scene
    import db_queries

    ctx, _ = await started("hollow_choir", player_class="mage")
    await search(ctx)
    pid = ctx.userdata.player_id
    before = await db_queries.get_player(pid)
    original = db_mutations.delete_combat_state
    expected = {}

    async def fail(*args, **kwargs):
        expected["state"] = ctx.userdata.combat_state.to_dict()
        expected["player"] = await db_queries.get_player(pid)
        ctx.userdata.room.local_participant.publish_data.reset_mock()
        await original(*args, **kwargs)
        raise RuntimeError("injected Choir teardown failure")

    with monkeypatch.context() as m:
        m.setattr(db_mutations, "delete_combat_state", fail)
        for _ in range(30):
            ctx.userdata.room.local_participant.publish_data.reset_mock()
            try:
                if outcome == "fled":
                    await combat_end._end_combat_impl(ctx, "fled")
                else:
                    await bolt(ctx)
            except RuntimeError as error:
                assert "injected Choir teardown" in str(error)
                break
        else:
            raise AssertionError("Choir never reached teardown")
    state = ctx.userdata.combat_state
    assert state.to_dict() == expected["state"]
    assert state.choir_encounter["phase"] == ("exposed" if outcome == "fled" else "destroyed")
    persisted = await db_mutations.load_combat_state(state.combat_id)
    assert persisted is not None and persisted.to_dict() == state.to_dict()
    assert await db_queries.get_player(pid) == expected["player"]
    if outcome == "fled":
        assert expected["player"] == before
    scene = await choir_scene.load(ctx.userdata)
    assert scene is not None and scene["status"] == "combat"
    ctx.userdata.room.local_participant.publish_data.assert_not_called()
    if outcome == "fled":
        await combat_end._end_combat_impl(ctx, "fled")
    else:
        with patch("check_resolution.dice_roll", return_value=_d20(20)):
            result = await _resolve_round(ctx)
        assert json.loads(result[1])["xp_total"] == 3000
    assert ctx.userdata.combat_state is None


async def test_choir_lethal_action_rollback_restores_core_and_death_receipt(started, monkeypatch):
    import db_queries

    ctx, _ = await started("hollow_choir", player_class="mage")
    await search(ctx)
    pid = ctx.userdata.player_id
    original = db_mutations.save_combat_state
    expected = {}

    async def fail(combat_id, data, **kwargs):
        await original(combat_id, data, **kwargs)
        if data["choir_encounter"]["phase"] == "destroyed":
            expected["state"] = ctx.userdata.combat_state.to_dict()
            expected["player"] = await db_queries.get_player(pid)
            ctx.userdata.room.local_participant.publish_data.reset_mock()
            raise RuntimeError("injected lethal save failure")

    with monkeypatch.context() as m:
        m.setattr(db_mutations, "save_combat_state", fail)
        for _ in range(30):
            try:
                await bolt(ctx)
            except RuntimeError as error:
                assert "injected lethal save" in str(error)
                break
        else:
            raise AssertionError("core never reached lethal damage")
    state = ctx.userdata.combat_state
    assert state.to_dict() == expected["state"]
    assert state.choir_encounter["phase"] == "exposed"
    source = state.get_participant("choir_zone")
    assert source.hp_current > 0 and not source.hollow_death_resolved
    persisted = await db_mutations.load_combat_state(state.combat_id)
    assert persisted is not None and persisted.to_dict() == state.to_dict()
    assert await db_queries.get_player(pid) == expected["player"]
    ctx.userdata.room.local_participant.publish_data.assert_not_called()
    with patch("check_resolution.dice_roll", return_value=_d20(20)):
        result = await _resolve_round(ctx)
    assert json.loads(result[1])["xp_total"] == 3000


async def test_choir_audio_entry_and_reload_queries(started):
    from query_tools import _query_info_impl

    ctx, response = await started("hollow_choir")
    assert "voice" in response["choir"]["cue"]
    for phase in ["search", "exposed"]:
        state = ctx.userdata.combat_state
        assert state is not None
        ctx.userdata.combat_state = await db_mutations.load_combat_state(state.combat_id)
        facts = json.loads(await _query_info_impl(ctx, "combat"))["choir"]
        assert facts["phase"] == phase
        if phase == "search":
            assert facts["search_target_id"] == "choir_sound"
            assert {a["action"] for a in facts["search_actions"]} == {"choir_search_perception", "choir_search_arcana"}
            assert "core_id" not in facts
            await search(ctx)
        else:
            assert facts["core_id"] == "choir_zone"
            assert "30 feet east" in facts["cue"]
            assert facts["engine_damage_spell_ids"] == ["arcane_bolt"]
