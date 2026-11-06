"""Produced patron facts survive storage and reach the gameplay cast boundary."""

import json
from copy import deepcopy
from functools import partial
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from livekit.agents.llm.utils import prepare_function_arguments
from livekit.agents.voice import RunContext
from sample_fixtures import make_context
from syrath_valdris_fixtures import cast, hide, player_row
from syrath_valdris_fixtures import world as world

import db_mutations
import db_queries
import spell_casting
import spells


@pytest.mark.parametrize("spell_id,expected", [("arcane_fireball", 1), ("arcane_magic_missile", 0)])
async def test_hide_cast_and_reload(world, spell_id, expected):
    ids, conn, _, _ = world
    ctx = make_context(player_id=ids[0])
    result = await hide(world, ctx)
    assert result["outcome"] == "success"
    stored = await player_row(conn, ids[0])
    assert stored.get("flags", {}).get("concealed") is True
    assert result["concealment"]["player_id"] == ids[0]
    ctx = make_context(player_id=ids[0])
    packet = await cast(world, ctx, spell_id)
    assert packet["resonance_generated"] == expected
    assert packet["concealment"] == {"player_id": ids[0], "before": True, "concealed": False, "ended_by": "cast"}
    assert (await player_row(conn, ids[0]))["flags"]["concealed"] is False
    assert (await cast(world, ctx, spell_id))["resonance_generated"] == spells.get_spell(spell_id).resonance_by_source[
        "arcane"
    ]


@pytest.mark.parametrize("ending", ["never", "failure", "automatic", "unrelated", "refused", "inspired"])
async def test_concealment_transitions(world, ending):
    ids, conn, _, _ = world
    ctx = make_context(player_id=ids[0])
    if ending != "never":
        await hide(world, ctx)
    if ending == "failure":
        assert (await hide(world, ctx, roll=1))["outcome"] == "failure"
    elif ending == "automatic":
        assert (await hide(world, ctx, difficulty="legendary"))["outcome"] == "automatic_failure"
    elif ending == "unrelated":
        await hide(world, ctx, skill="athletics")
    elif ending == "refused":
        from livekit.agents.llm import ToolError

        await conn.execute("UPDATE players SET data=jsonb_set(data, '{focus,current}', '0') WHERE player_id=$1", ids[0])
        with pytest.raises(ToolError):
            await cast(world, ctx)
        assert (await player_row(conn, ids[0]))["flags"]["concealed"] is True
        await conn.execute(
            "UPDATE players SET data=jsonb_set(data, '{focus,current}', '50') WHERE player_id=$1", ids[0]
        )
    elif ending == "inspired":
        await conn.execute(
            'UPDATE players SET data=jsonb_set(data, \'{conditions}\', \'[{"type":"inspired","duration":2,"source":"ally"}]\') WHERE player_id=$1',
            ids[0],
        )
        await hide(world, ctx)
        assert (await player_row(conn, ids[0]))["conditions"] == []
    assert (await cast(world, ctx))["resonance_generated"] == (
        1 if ending in {"unrelated", "refused", "inspired"} else 3
    )


@pytest.mark.parametrize("grievance", ["broken_promise", "injustice"])
async def test_grievance_party_and_outsider(world, grievance):
    import session_tools

    ids, conn, database, queries = world
    npc = "guildmaster_torin"
    ctx = make_context(player_id=ids[0])
    ctx.mock_add_spec(RunContext)
    queries.get_npcs_at_location = partial(db_queries.get_npcs_at_location, conn=conn)
    original = session_tools._update_npc_disposition_impl
    await original(ctx, npc, -1, "Colder", "none", db_mod=database, queries=queries)
    await conn.execute(
        "UPDATE players SET data=jsonb_set(data, '{divine_favor}', '{\"patron\":\"valdris\"}') WHERE player_id=$1",
        ids[0],
    )
    assert (await cast(world, ctx, "arcane_haste", npc))["resonance_generated"] == 3

    async def invoke(*args, **kwargs):
        return await original(*args, **kwargs, db_mod=database, queries=queries)

    with patch.object(session_tools, "_update_npc_disposition_impl", invoke):
        args, kwargs = prepare_function_arguments(
            fnc=session_tools.update_npc_disposition,
            json_arguments=json.dumps({"npc_id": npc, "delta": 0, "reason": "Broke the pact", "grievance": grievance}),
            call_ctx=ctx,
        )
        packet = json.loads(await session_tools.update_npc_disposition(*args, **kwargs))
    row = await player_row(conn, ids[0])
    assert row.get("flags", {}).get(f"grievance:{npc}") == grievance
    assert packet["wrongdoing"] == {"target_id": npc, "player_id": ids[0], "source": "grievance", "kind": grievance}
    for pid in ids:
        await conn.execute(
            "UPDATE players SET data=jsonb_set(data, '{divine_favor}', '{\"patron\":\"valdris\"}') WHERE player_id=$1",
            pid,
        )
    for pid, party, expected in [(ids[0], [ids[0]], 1), (ids[1], ids[:2], 1), (ids[2], [ids[2]], 3)]:
        ctx = make_context(player_id=pid, party_member_ids=party)
        packet = await cast(world, ctx, "arcane_haste", npc)
        assert packet["resonance_generated"] == expected
        assert ("wrongdoing" in packet) == (expected == 1)
    await session_tools._update_npc_disposition_impl(
        make_context(player_id=ids[0]), npc, -1, "Still angry", "none", db_mod=database, queries=queries
    )
    assert (await cast(world, make_context(player_id=ids[0]), "arcane_haste", npc))["resonance_generated"] == 1
    ctx = make_context(player_id=ids[0])
    other_npc = await conn.fetchval("SELECT id FROM npcs WHERE id != $1 LIMIT 1", npc)
    assert other_npc
    assert (await cast(world, ctx, "arcane_haste", other_npc))["resonance_generated"] == 3
    assert "wrongdoing" in await cast(world, ctx, "arcane_bolt", npc)
    assert (await cast(world, ctx, target=npc))["resonance_generated"] == 3
    assert (await cast(world, ctx, "arcane_haste"))["resonance_generated"] == 3
    from dataclasses import replace

    missile = replace(spells.get_spell("arcane_magic_missile"), max_targets=3)
    assert (await cast(world, ctx, missile.id, spell=missile, target_ids=[npc]))["resonance_generated"] == 1


@pytest.mark.parametrize("opening", ["hostile", "ally", "miss", "save", "paused", "fresh", "untouched"])
async def test_first_hostility_survives_phase_reload(world, opening):
    from combat._helpers import _resolution_state, _resolve_deps, _resolve_round
    from voice_condition_fixtures import place_actors

    import combat_turn
    from combat_state import CombatState

    ids, conn, database, queries = world
    ctx = make_context(player_id=ids[0], party_member_ids=ids[:2])
    state = _resolution_state(player_id=ids[0], enemy_hp=50, combat_id=f"fight_{uuid4().hex}")
    guest = deepcopy(state.participants[0])
    guest.id = ids[1]
    guest.name = "Ally"
    state.participants.append(guest)
    quiet = deepcopy(state.participants[1])
    quiet.id = "quiet_hostile"
    state.participants.append(quiet)
    state.initiative_order.extend([guest.id, quiet.id])
    state.pending_declarations[quiet.id] = {"type": "defend"}
    if opening == "save":
        state.participants[1].action_pool[0].update(
            resolution="save",
            save="dexterity",
            dc=1,
            save_success_damage="none",
            reach=30,
            type="ranged",
            conditions_on_failure=[],
            conditions_on_success=[],
        )
    if opening == "paused":
        import reaction_spend

        guest.has_reaction_ability = True
        guest.reaction_ids = ["skirmisher_sidestep", "rogue_uncanny_dodge"]
        state.reactions_available[guest.id] = reaction_spend.unspent()
    state.pending_declarations[guest.id] = {"type": "defend"}
    state.pending_declarations["goblin_scout_1"]["target_id"] = guest.id
    if opening != "ally":
        state.pending_declarations[ids[0]] = {"type": "defend"}
    ctx.userdata.combat_state = place_actors(state)
    await conn.execute(
        "INSERT INTO combat_instances (combat_id, data) VALUES ($1, $2::jsonb)",
        state.combat_id,
        json.dumps(state.to_dict()),
    )
    deps = _resolve_deps(0 if opening == "miss" else 1)
    deps.update(db_mod=database, queries=queries)

    async def save(*args, **kwargs):
        kwargs["conn"] = conn
        return await db_mutations.save_combat_state(*args, **kwargs)

    deps["mutations"].save_combat_state = save
    if opening == "miss":
        old = deps["resolver"].resolve_attack.side_effect
        from dataclasses import replace

        deps["resolver"].resolve_attack.side_effect = lambda *a, **kw: replace(old(*a, **kw), hit=False)
    if opening == "paused":
        for _ in range(3):
            raw = await combat_turn._resolve_phase_impl(ctx, **deps)
            assert isinstance(raw, str)
            paused = json.loads(raw)
        assert paused["next"]["waiting_on"]["stage"] == "post_roll"
        assert paused["wrongdoing"][0]["target_id"] == "goblin_scout_1"
        loaded = await db_mutations.load_combat_state(state.combat_id, conn=conn)
        assert loaded is not None
        ctx.userdata.combat_state = loaded
        assert loaded.first_hostility == {"goblin_scout_1": "hostile"}
    await _resolve_round(ctx, **deps)
    saved = await conn.fetchval("SELECT data FROM combat_instances WHERE combat_id=$1", state.combat_id)
    ctx.userdata.combat_state = CombatState.from_dict(json.loads(saved))
    expected = "ally" if opening == "ally" else "hostile"
    assert ctx.userdata.combat_state.first_hostility == {"goblin_scout_1": expected}
    for pid in ids[:2]:
        await conn.execute(
            "UPDATE players SET data=jsonb_set(data, '{divine_favor}', '{\"patron\":\"valdris\"}') WHERE player_id=$1",
            pid,
        )
    if opening == "fresh":
        ctx.userdata.combat_state = CombatState(
            combat_id=f"fresh_{uuid4().hex}",
            participants=ctx.userdata.combat_state.participants,
            initiative_order=ctx.userdata.combat_state.initiative_order,
            spatial=ctx.userdata.combat_state.spatial,
        )
    target = "quiet_hostile" if opening == "untouched" else "goblin_scout_1"
    deps["character_spells_mod"] = MagicMock(get_known=AsyncMock(return_value=[{"spell_id": "arcane_haste"}]))
    deps["cast_resolver"] = MagicMock(
        _gate_spell=spell_casting._gate_spell,
        _resolve_cast=partial(
            spell_casting._resolve_cast,
            queries_mod=queries,
            character_spells_mod=deps["character_spells_mod"],
            ward_resolution_mod=MagicMock(resolve_scope_ward=AsyncMock(return_value=None)),
        ),
    )
    await combat_turn._declare_phase_impl(
        ctx,
        {
            ids[0]: {"type": "defend"},
            ids[1]: {"type": "ability", "action": "arcane_haste", "target_id": target},
            "goblin_scout_1": {"type": "defend"},
            "quiet_hostile": {"type": "defend"},
        },
        mutations=deps["mutations"],
    )
    response = await _resolve_round(ctx, **deps)
    packet = next(p["cast"] for p in response["packets"] if p["actor_id"] == ids[1])
    qualifies = opening not in {"ally", "fresh", "untouched"}
    assert packet["resonance_generated"] == (1 if qualifies else 3)
    assert ("wrongdoing" in packet) == qualifies


@pytest.mark.parametrize(
    "action,hit,spell_id",
    [
        ("defend", True, None),
        ("attack", True, None),
        ("attack", False, None),
        ("cast", True, "arcane_fireball"),
        ("cast", True, "arcane_magic_missile"),
    ],
)
async def test_guest_action_concealment(world, action, hit, spell_id):
    from combat._helpers import _resolution_state, _resolve_deps, _resolve_round
    from voice_condition_fixtures import place_actors

    import combat_turn

    ids, conn, database, queries = world
    ctx = make_context(player_id=ids[0], party_member_ids=ids[:2])
    with ctx.userdata._bind_authenticated_actor(ids[1], 4, lambda *_: None):
        await hide(world, ctx)
    state = _resolution_state(player_id=ids[0], enemy_hp=50)
    guest = deepcopy(state.participants[0])
    guest.id = ids[1]
    state.participants.append(guest)
    state.initiative_order.append(guest.id)
    state.pending_declarations = {}
    state.beat = "declaration"
    ctx.userdata.combat_state = place_actors(state)
    deps = _resolve_deps(1)
    deps.update(db_mod=database, queries=queries)
    if not hit:
        from dataclasses import replace

        old = deps["resolver"].resolve_attack.side_effect
        deps["resolver"].resolve_attack.side_effect = lambda *a, **kw: replace(old(*a, **kw), hit=False, damage=0)
    declaration = {"type": "defend"}
    if action == "attack":
        declaration = {"type": "attack", "action": "Longsword", "target_id": "goblin_scout_1"}
    if action == "cast":
        declaration = {"type": "ability", "action": spell_id, "target_id": "goblin_scout_1"}
        deps["character_spells_mod"] = MagicMock(get_known=AsyncMock(return_value=[{"spell_id": spell_id}]))
        deps["cast_resolver"] = MagicMock(
            _gate_spell=spell_casting._gate_spell,
            _resolve_cast=partial(
                spell_casting._resolve_cast,
                queries_mod=queries,
                character_spells_mod=deps["character_spells_mod"],
                ward_resolution_mod=MagicMock(resolve_scope_ward=AsyncMock(return_value=None)),
            ),
        )
    await combat_turn._declare_phase_impl(
        ctx,
        {
            ids[0]: {"type": "defend"},
            "goblin_scout_1": {"type": "defend"},
            ids[1]: declaration,
        },
        mutations=deps["mutations"],
    )
    response = await _resolve_round(ctx, **deps)
    stored = await player_row(conn, ids[1])
    assert stored["flags"]["concealed"] is (action == "defend")
    assert "concealed" not in (await player_row(conn, ids[0])).get("flags", {})
    if action == "attack":
        packet = next(p for p in response["packets"] if p["actor_id"] == ids[1])
        assert packet["concealment"]["ended_by"] == "attack"
    if action == "cast":
        packet = next(p["cast"] for p in response["packets"] if p["actor_id"] == ids[1])
        assert packet["resonance_generated"] == (1 if spell_id == "arcane_fireball" else 0)
        assert packet["concealment"]["player_id"] == ids[1]
    # Use a fresh session, with no combat mirror carrying the hidden state.
    assert (await cast(world, make_context(player_id=ids[1])))["resonance_generated"] == (
        1 if action == "defend" else 3
    )


async def test_unknown_targets_refuse_before_writes(world):
    from livekit.agents.llm import ToolError

    import session_tools

    ids, conn, database, queries = world
    ctx = make_context(player_id=ids[0])
    await hide(world, ctx)
    await conn.execute(
        "UPDATE players SET data=jsonb_set(data, '{divine_favor}', '{\"patron\":\"valdris\"}') WHERE player_id=$1",
        ids[0],
    )
    before = await conn.fetchval("SELECT data FROM players WHERE player_id=$1", ids[0])
    with pytest.raises(ToolError, match="Unknown target"):
        await cast(world, ctx, "arcane_haste", "missing_target")
    with pytest.raises(ToolError, match="not found"):
        await session_tools._update_npc_disposition_impl(
            ctx, "missing_target", 0, "injustice", "injustice", db_mod=database, queries=queries
        )
    assert await conn.fetchval("SELECT data FROM players WHERE player_id=$1", ids[0]) == before


def test_ledger_reloads_after_player_rises_as_echo():
    from dataclasses import replace

    from combat._helpers import _make_combat_state
    from voice_condition_fixtures import place_actors

    import combat_wrongdoing
    from combat_state import CombatState

    state = _make_combat_state()
    player = state.participants[0]
    echo = replace(player, id="player_2", type="temporary_hollowed")
    state.participants.append(echo)
    state = place_actors(state)
    combat_wrongdoing.record_attack(state, player, echo)
    assert CombatState.from_dict(state.to_dict()).first_hostility == {"player_2": "ally"}
