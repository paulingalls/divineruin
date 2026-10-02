"""Executable runtime inputs with seeded species; catalog production belongs to story-137."""

import json
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from acceptance._capstone_helpers import _d20, _resolve_round
from acceptance._catalog_cutover_helpers import cold_catalog_reads as cold_catalog_reads
from acceptance.seeds import seed_player
from combat._catalog_actions import BITE, DIRTY, RALLY
from combat._catalog_fixtures import LUNGE
from sample_fixtures import make_context, make_mock_room

import combat_init
import combat_turn
import db
import db_mutations
import db_queries
import event_types as E
from combat_ui_update import build_combat_ui_update
from creature_catalog import query_creature_by_id


@pytest.fixture
async def runtime(reset_db_pool):
    pool = await db.get_pool()
    created = []
    originals = {}

    async def start(species, actions, role="standard"):
        row = await query_creature_by_id(species)
        uid = uuid4().hex
        player_id, encounter_id, enemy_id = f"p136_{uid}", f"e136_{uid}", f"foe_{uid}"
        await seed_player(pool, player_id=player_id, class_="warrior")
        from copy import deepcopy

        from creature_schema import validate_creature_stat_block

        catalog_row = deepcopy(row)
        originals.setdefault(species, deepcopy(row))
        attacks, actives = [], []
        for action in actions:
            if action.get("kind", "attack") == "attack":
                attacks.append({**row["attacks"][0], **action})
            else:
                actives.append(
                    {
                        "description": "Test-authored active.",
                        "narration_cue": "A sharp crack rings out.",
                        "audio": "test-active",
                        **action,
                    }
                )
        catalog_row["attacks"] = attacks or [row["attacks"][0]]
        catalog_row["actives"] = actives
        assert not validate_creature_stat_block(catalog_row)
        await pool.execute(
            "UPDATE creatures SET data = $2::jsonb WHERE id = $1", catalog_row["id"], json.dumps(catalog_row)
        )
        enemy = {"id": enemy_id, "creature_id": catalog_row["id"], "role": role}
        await pool.execute(
            "INSERT INTO encounter_templates (id, data) VALUES ($1, $2::jsonb)",
            encounter_id,
            json.dumps({"id": encounter_id, "recommended_party_level": 2, "enemies": [enemy]}),
        )
        ctx = make_context(player_id, room=make_mock_room())
        created.append((ctx, player_id, encounter_id, catalog_row["id"]))
        await combat_init._start_combat_impl(ctx, encounter_id, "A catalog combat input.")
        ctx.userdata.combat_state.get_participant(player_id).has_reaction_ability = False
        return ctx, player_id, enemy_id

    yield start
    for ctx, player_id, encounter_id, _species_id in created:
        if ctx.userdata.combat_state is not None:
            await db_mutations.delete_combat_state(ctx.userdata.combat_state.combat_id, conn=pool)
        await pool.execute("DELETE FROM players WHERE player_id = $1", player_id)
        await pool.execute("DELETE FROM encounter_templates WHERE id = $1", encounter_id)
    for species_id, original in originals.items():
        await pool.execute("UPDATE creatures SET data = $2::jsonb WHERE id = $1", species_id, json.dumps(original))


async def declare(ctx, pid, eid, name, kind="attack"):
    raw = {"type": kind, "action": name}
    if kind == "attack":
        raw["target_id"] = pid
    await combat_turn._declare_phase_impl(ctx, {pid: {"type": "defend"}, eid: raw})


async def phase(ctx):
    result = await combat_turn._resolve_phase_impl(ctx)
    assert isinstance(result, str), "combat ended unexpectedly"
    return json.loads(result)


def participant(state, pid):
    result = state.get_participant(pid)
    assert result is not None
    return result


async def player_row(pid):
    result = await db_queries.get_player(pid)
    assert result is not None
    return result


async def reload(ctx):
    saved = await db_mutations.load_combat_state(ctx.userdata.combat_state.combat_id)
    assert saved is not None
    assert saved.to_dict() == ctx.userdata.combat_state.to_dict()
    ctx.userdata.combat_state = saved
    return saved


def events(ctx):
    return [json.loads(c.args[0]) for c in ctx.userdata.room.local_participant.publish_data.call_args_list]


async def test_catalog_attack_math_commit_and_reload(runtime):
    row = await query_creature_by_id("hollow_mawling")
    action = {**row["attacks"][0], "attack_source": "catalog"}
    ctx, pid, eid = await runtime("hollow_mawling", [action], role="elite")
    await declare(ctx, pid, eid, action["name"])
    with (
        patch("check_resolution.dice_roll", return_value=_d20(13)),
        patch("check_resolution_attack.dice_roll", return_value=SimpleNamespace(total=9)),
    ):
        result = await _resolve_round(ctx)
    summary = next(p for p in result["packets"] if p["actor_id"] == eid)
    assert summary["attack_total"] == 19
    assert summary["damage"] == 11
    state = await reload(ctx)
    assert participant(state, pid).hp_current == 17
    player = await db_queries.get_player(pid)
    assert player is not None
    assert player["hp"]["current"] == 17
    assert [e for e in events(ctx) if e["type"] == E.DICE_ROLL][-1]["modifier"] == 6


async def test_catalog_lunge_recharge_and_held_reload(runtime):
    row = await query_creature_by_id("hollow_mawling")
    action = {
        **row["attacks"][2],
        "attack_source": "catalog",
        "advantage": True,
        "recharge": {"kind": "roll", "die": 6, "threshold": 5},
    }
    ctx, pid, eid = await runtime("hollow_mawling", [action])
    player = ctx.userdata.combat_state.get_participant(pid)
    player.has_reaction_ability = True
    player.reaction_ids = ["skirmisher_sidestep", "rogue_uncanny_dodge"]
    await declare(ctx, pid, eid, "Lunge")
    await combat_turn._resolve_phase_impl(ctx)
    pre = await phase(ctx)
    assert pre["next"]["waiting_on"]["stage"] == "pre_roll"
    await reload(ctx)
    with (
        patch("check_resolution.dice_roll", return_value=_d20(13)),
        patch("check_resolution_attack.dice_roll", return_value=SimpleNamespace(total=3)),
    ):
        post = await phase(ctx)
    assert post["next"]["waiting_on"]["stage"] == "post_roll"
    roster = next(p for p in post["participants"] if p["id"] == eid)
    assert "Lunge" not in roster["actions"]
    await reload(ctx)
    with patch("combat_recharge.roll", return_value=SimpleNamespace(total=4)):
        result = await phase(ctx)
    assert result["packets"][0]["condition_inflicted"] == "grappled"
    assert "Lunge" not in next(p for p in result["participants"] if p["id"] == eid)["actions"]
    await reload(ctx)
    await combat_turn._declare_phase_impl(ctx, {pid: {"type": "defend"}})
    with patch("combat_recharge.roll", return_value=SimpleNamespace(total=5)):
        result = await _resolve_round(ctx)
    assert "Lunge" in next(p for p in result["participants"] if p["id"] == eid)["actions"]
    assert len([e for e in events(ctx) if e["type"] == E.DICE_ROLL]) == 1


async def test_catalog_captain_actives_commit_and_resume(runtime):
    ctx, pid, eid = await runtime("bandit_captain", [RALLY, DIRTY, {**BITE, "damage": "1d1"}])
    captain = ctx.userdata.combat_state.get_participant(eid)
    captain.hp_current = 20
    await declare(ctx, pid, eid, "Rally", "ability")
    with patch("dice.roll", return_value=SimpleNamespace(total=5)):
        result = await _resolve_round(ctx)
    assert result["packets"][-1]["healed"] == {eid: 5}
    assert participant(await reload(ctx), eid).hp_current == 25
    await declare(ctx, pid, eid, "Dirty Fighting", "ability")
    await _resolve_round(ctx)
    assert participant(await reload(ctx), eid).pending_preparation is not None
    player = participant(ctx.userdata.combat_state, pid)
    player.has_reaction_ability = True
    player.reaction_ids = ["skirmisher_sidestep", "rogue_uncanny_dodge"]
    await declare(ctx, pid, eid, "Bite")
    await phase(ctx)
    pre = await phase(ctx)
    assert pre["next"]["waiting_on"]["stage"] == "pre_roll"
    await reload(ctx)
    with patch("check_resolution.dice_roll", return_value=_d20(13)):
        post = await phase(ctx)
    assert post["next"]["waiting_on"]["stage"] == "post_roll"
    assert participant(await reload(ctx), eid).pending_preparation is None
    with patch("check_resolution_attack.resolve_attack", side_effect=AssertionError("held attack rolled twice")):
        result = await phase(ctx)
    assert result["packets"][-1]["condition_inflicted"] == "blinded"
    assert participant(await reload(ctx), eid).pending_preparation is None


async def test_catalog_absorb_committed_state_events_and_hud(runtime):
    ctx, pid, eid = await runtime("hollow_mawling", [BITE])
    state = ctx.userdata.combat_state
    participant(state, eid).hp_current = 1
    await declare(ctx, pid, eid, "Bite")
    with patch("check_resolution.dice_roll", return_value=_d20(13)):
        result = await _resolve_round(ctx)
    assert result["packets"][-1]["self_healed"] == 20
    state = await reload(ctx)
    assert participant(state, eid).hp_current == 21
    hud = [e for e in events(ctx) if e["type"] == E.COMBAT_UI_UPDATE][-1]
    expected = build_combat_ui_update(state)
    assert hud["combatants"] == expected["combatants"]
    assert next(p for p in hud["combatants"] if p["id"] == eid)["hpCurrent"] == 21
    assert (await player_row(pid))["hp"]["current"] == 8


@pytest.mark.parametrize("action", [BITE, DIRTY, LUNGE])
async def test_catalog_failed_commit_preserves_hp_availability_and_preparation(runtime, action):
    ctx, pid, eid = await runtime("hollow_mawling", [action])
    participant(ctx.userdata.combat_state, eid).hp_current = 1
    await declare(ctx, pid, eid, action["name"], "ability" if action is DIRTY else "attack")
    await combat_turn._resolve_phase_impl(ctx)
    before = ctx.userdata.combat_state.to_dict()
    count = len(events(ctx))
    with (
        patch("db_mutations.save_combat_state", side_effect=RuntimeError("injected save failure")),
        patch("check_resolution.dice_roll", return_value=_d20(13)),
        patch("combat_recharge.roll", return_value=SimpleNamespace(total=4)),
    ):
        with pytest.raises(RuntimeError, match="injected save failure"):
            await combat_turn._resolve_phase_impl(ctx)
    assert ctx.userdata.combat_state.to_dict() == before
    assert len(events(ctx)) == count
    await reload(ctx)
    assert (await player_row(pid))["hp"]["current"] == 28
    with (
        patch("check_resolution.dice_roll", return_value=_d20(13)),
        patch("combat_recharge.roll", return_value=SimpleNamespace(total=4)),
    ):
        result = await phase(ctx)
    assert result["packets"][-1]["resolved"]
    await reload(ctx)
