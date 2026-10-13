"""Fictional hearing/speech restrictions leave real microphone commands and DM receipts active."""

import json

import pytest
from acceptance.multiplayer_voice._harness import MultiplayerVoiceHarness
from acceptance.seeds import seed_player_with_pools
from acceptance.voice_condition_harness import ScenarioModel, assert_hud_floor, run_voice_commands

import db
import db_mutations
import db_queries
from combat_agent import CombatAgent
from session_data import CombatParticipant, CombatState, SessionData

CASES = ("deafened_sight", "silenced_cast", "silenced_legal", "outside_cast", "guest_sight", "silenced_social")


def scene(host, guest, case):
    actors = [
        CombatParticipant(id=pid, name=pid, type="player", initiative=15, hp_current=28, hp_max=28, ac=15)
        for pid in (host, guest)
    ]
    if case in ("deafened_sight", "guest_sight"):
        actors[1 if case == "guest_sight" else 0].conditions = [
            {"type": "deafened", "duration": 3, "source": "fixture"}
        ]
    if case == "silenced_social":
        actors.append(
            CombatParticipant(
                id="merchant_1", name="Merchant", type="enemy", initiative=10, hp_current=20, hp_max=20, ac=12
            )
        )
    positions = {host: {"x": 0, "y": 0, "z": 0}, guest: {"x": 50, "y": 0, "z": 0}}
    if case == "silenced_social":
        positions["merchant_1"] = {"x": 50, "y": 0, "z": 0}
    return CombatState(
        combat_id="voice-" + host,
        participants=actors,
        initiative_order=[host, guest],
        spatial={
            "positions": positions,
            "speeds": {pid: 30 for pid in positions},
            "locations": {"quiet_center": {"x": 0 if case.startswith("silenced") else 100, "y": 0, "z": 0}},
            "zones": {"quiet": {"kind": "silence", "center_id": "quiet_center", "radius_ft": 10}},
        },
    )


def commands(case, host):
    sight = (
        "check",
        {
            "roll": {
                "kind": "skill",
                "skill": "perception",
                "difficulty": "easy",
                "context_description": "look at the wall",
                "hearing_only": False,
            }
        },
    )
    save = ("check", {"roll": {"kind": "save", "save_type": "dexterity", "dc": 8, "effect_on_fail": "stumble"}})
    cast_spell = (
        "declare_phase",
        {
            "declarations": [
                {"kind": "ability", "actor_id": host, "action": "arcane_bolt", "targets": [], "argument_type": ""}
            ]
        },
    )
    if case == "silenced_social":
        return [
            (
                "check",
                {"roll": {"kind": "social", "npc_id": "merchant_1", "skill": "persuasion", "difficulty": "easy"}},
            ),
            save,
        ]
    if case == "silenced_cast":
        return [cast_spell, save]
    if case == "outside_cast":
        return [cast_spell, ("resolve_phase", {})]
    return [save] if case == "silenced_legal" else [sight]


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES)
async def test_microphone_reaches_real_gameplay_verb_and_dm_receipt(case, livekit_server, reset_db_pool, monkeypatch):
    for key, field in (("LIVEKIT_URL", "ws_url"), ("LIVEKIT_API_KEY", "api_key"), ("LIVEKIT_API_SECRET", "api_secret")):
        monkeypatch.setenv(key, livekit_server[field])
    harness = MultiplayerVoiceHarness(livekit_server)
    host, guest = harness.player_one_identity, harness.player_two_identity
    pool = await db.get_pool()
    for pid in (host, guest):
        await seed_player_with_pools(
            pool, player_id=pid, class_="mage", focus_current=0 if case == "silenced_cast" else 10
        )
    sd = SessionData(player_id=host, location_id="accord_guild_hall")
    state = scene(host, guest, case)
    await db_mutations.save_combat_state(state.combat_id, state.to_dict())
    sd.combat_state = await db_mutations.load_combat_state(state.combat_id)
    assert sd.combat_state is not None and sd.combat_state.spatial == state.spatial
    model = ScenarioModel(commands(case, host))
    hud = await run_voice_commands(
        harness,
        sd,
        model,
        CombatAgent(),
        monkeypatch,
        speaker=guest if case == "guest_sight" else host,
    )
    outputs = list(model.receipts.values())
    if case == "silenced_social":
        refusal, legal = outputs
        assert refusal.name == "check" and refusal.is_error and "silenced" in refusal.output
        assert legal.name == "check" and not legal.is_error
        assert "cannot speak" in model.narration
    elif case == "silenced_cast":
        refusal = next(output for output in outputs if output.name == "declare_phase")
        assert refusal.is_error and "silenced" in refusal.output
        assert "cannot speak" in model.narration
        assert sd.combat_state.pending_declarations == {}
        row = await db_queries.get_player(host)
        assert row is not None and row["focus"]["current"] == 0
    else:
        assert all(not output.is_error for output in outputs)
    if case == "guest_sight":
        assert (await db_queries.get_single_skill_advancement(guest, "perception"))["use_counter"] == 1
        assert (await db_queries.get_single_skill_advancement(host, "perception"))["use_counter"] == 0
    assert_hud_floor(hud)


@pytest.mark.asyncio
async def test_charm_held_reload_and_failed_landing_preserve_committed_state(reset_db_pool, monkeypatch):
    import uuid
    from unittest.mock import AsyncMock, MagicMock

    from combat._helpers import _call, _ctx_at_resolution, _resolve_deps

    import combat_events
    import conditions

    suffix = uuid.uuid4().hex
    pid, eid = "charm-player-" + suffix, "charm-enemy-" + suffix
    pool = await db.get_pool()
    await seed_player_with_pools(pool, player_id=pid, class_="mage")
    await db_mutations.update_player_hp(pid, 25)
    ctx = _ctx_at_resolution(player_hp=25, enemy_hp=30, reaction_ids=("skirmisher_sidestep", "rogue_uncanny_dodge"))
    raw = json.dumps(ctx.userdata.combat_state.to_dict()).replace("player_1", pid).replace("goblin_scout_1", eid)
    state = CombatState.from_dict(json.loads(raw))
    state.combat_id = "held-charm-" + suffix
    state.participants[0].conditions = [{"type": "charmed", "source": eid, "duration": 3}]
    state.pending_declarations[pid] = {"type": "defend", "action": "defend"}
    ctx.userdata = SessionData(player_id=pid, location_id="accord_guild_hall")
    ctx.userdata.combat_state = state
    await db_mutations.save_combat_state(state.combat_id, state.to_dict())
    deps: dict = _resolve_deps(damage=3)
    deps["mutations"] = db_mutations
    deps["db_mod"] = db
    deps["resonance_mutations"] = MagicMock(update_player_resonance=AsyncMock())
    for _ in range(3):
        await _call(ctx, deps)
    loaded = await db_mutations.load_combat_state(state.combat_id)
    assert loaded is not None
    ctx.userdata.combat_state = loaded
    before = loaded.to_dict()
    assert loaded.participants[0].hp_current == 25
    assert conditions.has_condition(loaded.participants[0].conditions, "charmed")
    save = db_mutations.save_combat_state

    async def fail_after_save(*args, **kwargs):
        await save(*args, **kwargs)
        raise RuntimeError("fault after held damage save")

    flush = AsyncMock()
    with monkeypatch.context() as fault:
        fault.setattr(db_mutations, "save_combat_state", fail_after_save)
        fault.setattr(combat_events.EventSink, "flush", flush)
        with pytest.raises(RuntimeError, match="fault after held damage save"):
            await _call(ctx, deps)
    flush.assert_not_awaited()
    assert ctx.userdata.combat_state is loaded
    assert loaded.to_dict() == before
    rolled_back = await db_mutations.load_combat_state(state.combat_id)
    assert rolled_back is not None and rolled_back.to_dict() == before
    row = await db_queries.get_player(pid)
    assert row is not None and row["hp"]["current"] == 25
    await _call(ctx, deps)
    committed = await db_mutations.load_combat_state(state.combat_id)
    assert committed is not None
    assert committed.participants[0].hp_current == 22
    assert not conditions.has_condition(committed.participants[0].conditions, "charmed")
    row = await db_queries.get_player(pid)
    assert row is not None and row["hp"]["current"] == 22


@pytest.mark.asyncio
@pytest.mark.parametrize("silenced", [True, False])
async def test_public_save_commits_spoken_die_eligibility_once(silenced, reset_db_pool, monkeypatch):
    import uuid
    from unittest.mock import AsyncMock

    from sample_fixtures import make_context

    from check_tools import _check_save_impl

    pid = "spoken-save-" + uuid.uuid4().hex
    pool = await db.get_pool()
    await seed_player_with_pools(pool, player_id=pid, class_="mage")
    state = scene(pid, "other", "silenced_legal" if silenced else "outside_cast")
    actor = state.participants[0]
    actor.conditions = [{"type": "inspired"}, {"type": "blessed"}]
    await db_mutations.save_combat_state(state.combat_id, state.to_dict())
    ctx = make_context(player_id=pid)
    ctx.userdata.combat_state = state
    monkeypatch.setattr("check_tools.publish_game_event", AsyncMock())
    await _check_save_impl(ctx, "wisdom", 8, "stunned")
    expected = [{"type": "inspired"}] if silenced else []
    assert ctx.userdata.combat_state.participants[0].conditions == expected
    loaded = await db_mutations.load_combat_state(state.combat_id)
    assert loaded is not None and loaded.participants[0].conditions == expected
    if silenced:
        assert loaded.spatial is not None
        loaded.spatial["positions"][pid]["x"] = 40
        await db_mutations.save_combat_state(loaded.combat_id, loaded.to_dict())
        ctx.userdata.combat_state = loaded
        await _check_save_impl(ctx, "wisdom", 8, "stunned")
        assert ctx.userdata.combat_state.participants[0].conditions == []
    await _check_save_impl(ctx, "wisdom", 8, "stunned")
    assert ctx.userdata.combat_state.participants[0].conditions == []
