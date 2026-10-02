import json
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from acceptance._capstone_helpers import _build_state, _d20, _resolve_round, _start_combat
from creature_combat_helpers import participant, selected
from sample_fixtures import make_context, make_mock_room

import combat_turn
import db
import db_mutations
from combat_action_availability import action_summary
from creature_combat_loader import load_creature_enemy
from declaration_payloads import AbilityDecl, AttackDecl, DefendDecl


@pytest.fixture
async def runtime(reset_db_pool):
    pool = await db.get_pool()
    created = []

    async def start(species, role="standard"):
        uid = uuid4().hex
        pid, eid, cid = f"p137_{uid}", f"enemy137_{uid}", f"combat137_{uid}"
        enemy = await load_creature_enemy(species, encounter_id="enc137", enemy_id=eid, role=role)
        state = _build_state(cid, pid, [participant(enemy)])
        state.participants[0].has_reaction_ability = False
        ctx = make_context(pid, room=make_mock_room())
        await _start_combat(pool, pid, state, ctx)
        created.append((cid, pid))
        return ctx, pid, eid, enemy

    yield start
    for cid, pid in created:
        await db_mutations.delete_combat_state(cid, conn=pool)
        await pool.execute("DELETE FROM players WHERE player_id = $1", pid)


def get_participant(state, key):
    value = state.get_participant(key)
    assert value is not None
    return value


async def reload(ctx):
    state = await db_mutations.load_combat_state(ctx.userdata.combat_state.combat_id)
    assert state is not None
    assert state.to_dict() == ctx.userdata.combat_state.to_dict()
    ctx.userdata.combat_state = state
    return state


async def declare(ctx, pid, eid, name):
    actor = ctx.userdata.combat_state.get_participant(eid)
    advertised = next(a for a in action_summary(actor)["executable_actions"] if a["name"] == name)
    if advertised["declaration_type"] == "ability":
        payload = AbilityDecl(kind="ability", actor_id=eid, action=name, targets=[], argument_type="")
    else:
        payload = AttackDecl(kind="attack", actor_id=eid, action=name, target_id=pid, rider="")
    response = json.loads(await combat_turn.declare_phase(ctx, [DefendDecl(kind="defend", actor_id=pid), payload]))
    assert eid in response["accepted_actors"]
    return response


async def resolve(ctx, face=13, damage=3):
    with (
        patch("check_resolution.dice_roll", return_value=_d20(face)),
        patch("check_resolution_attack.dice_roll", return_value=SimpleNamespace(total=damage)),
        patch("dice.roll", return_value=SimpleNamespace(total=5)),
        patch("combat_recharge.roll", return_value=SimpleNamespace(total=4)),
    ):
        return await _resolve_round(ctx)


ACTIONS = [(r["id"], a["name"]) for r in selected() for a in [*r["attacks"], *[a for a in r["actives"] if "kind" in a]]]


@pytest.mark.parametrize("species,name", ACTIONS)
async def test_catalog_actions_and_dm_metadata_through_tools(runtime, species, name):
    ctx, pid, eid, enemy = await runtime(species)
    actor = ctx.userdata.combat_state.get_participant(eid)
    actor.hp_current = max(1, actor.hp_max - 10)
    response = await declare(ctx, pid, eid, name)
    roster = next(p for p in response["participants"] if p["id"] == eid)
    for key in ("creature_id", "catalog_narration", "catalog_audio", "deferred_effects"):
        assert roster[key] == enemy[key]
    await reload(ctx)
    result = await resolve(ctx, face=19)
    packet = next(p for p in result["packets"] if p["actor_id"] == eid)
    action = next(a for a in enemy["action_pool"] if a["name"] == name)
    kind = action.get("kind", "attack")
    assert packet["resolved"] is True
    if kind == "healing":
        assert packet["healed"] == {eid: 5}
    elif kind == "prepare_attack":
        assert packet["prepared_attack"] is True
    elif kind in ("command", "accusation"):
        assert packet["kind"] == kind
    elif action["damage"] == "0":
        assert packet.get("condition_inflicted") == action["applies_condition"] or packet["save_success"] is True
    else:
        assert packet["hit"] is True and packet["damage"] == 3
        assert packet["attack_total"] == 19 + action["to_hit"]
    saved = await reload(ctx)
    roster = next(p for p in result["participants"] if p["id"] == eid)
    for key in ("creature_id", "catalog_narration", "catalog_audio", "deferred_effects"):
        assert roster[key] == getattr(saved.get_participant(eid), key) == enemy[key]


async def test_captain_healing_and_prepared_hit(runtime):
    ctx, pid, eid, _ = await runtime("bandit_captain")
    state = ctx.userdata.combat_state
    captain = state.get_participant(eid)
    captain.hp_current = captain.hp_max - 2
    for suffix, species, fallen, dead in [
        ("live", "bandit", False, False),
        ("fallen", "bandit", True, False),
        ("dead", "bandit", False, True),
        ("other", "cultist", False, False),
    ]:
        enemy = await load_creature_enemy(species, encounter_id="enc137", enemy_id=suffix, role="standard")
        p = participant(enemy)
        p.hp_current = 1
        p.is_fallen, p.is_dead = fallen, dead
        state.participants.append(p)
        state.initiative_order.append(p.id)
    await declare(ctx, pid, eid, "Rally")
    result = await resolve(ctx)
    assert next(p for p in result["packets"] if p["actor_id"] == eid)["healed"] == {eid: 2, "live": 5}
    await reload(ctx)
    await declare(ctx, pid, eid, "Dirty Fighting")
    await resolve(ctx)
    state = await reload(ctx)
    assert get_participant(state, eid).pending_preparation == {
        "on_hit": {"applies_condition": "blinded", "duration": 1}
    }
    await declare(ctx, pid, eid, "Longsword")
    with patch(
        "check_resolution_attack._roll_d20_check", wraps=__import__("check_resolution_attack")._roll_d20_check
    ) as consumer:
        result = await resolve(ctx)
    assert consumer.call_args.kwargs["advantage"] is True
    packet = next(p for p in result["packets"] if p["actor_id"] == eid)
    assert packet["condition_inflicted"] == "blinded"
    assert get_participant(await reload(ctx), eid).pending_preparation is None


async def test_lunge_grapple_advantage_and_recharge(runtime):
    ctx, pid, eid, _ = await runtime("hollow_mawling")
    await declare(ctx, pid, eid, "Lunge")
    with patch(
        "check_resolution_attack._roll_d20_check", wraps=__import__("check_resolution_attack")._roll_d20_check
    ) as consumer:
        result = await resolve(ctx)
    assert consumer.call_args.kwargs["advantage"] is True
    packet = next(p for p in result["packets"] if p["actor_id"] == eid)
    assert packet["condition_inflicted"] == "grappled"
    state = await reload(ctx)
    assert __import__("combat_grapple").escape_dc(state.get_participant(eid)) == 13
    assert next(c for c in get_participant(state, pid).conditions if c["type"] == "grappled")["source"] == eid
    assert "Lunge" not in action_summary(state.get_participant(eid))["actions"]
    await combat_turn.declare_phase(ctx, [DefendDecl(kind="defend", actor_id=pid)])
    with patch("combat_recharge.roll", return_value=SimpleNamespace(total=5)):
        await _resolve_round(ctx)
    assert "Lunge" in action_summary((await reload(ctx)).get_participant(eid))["actions"]


async def test_absorb_heals_actual_damage(runtime):
    ctx, pid, eid, _ = await runtime("hollow_warden")
    actor = ctx.userdata.combat_state.get_participant(eid)
    actor.hp_current = 1
    other_ctx, other_pid, _, _ = await runtime("bandit")
    state = ctx.userdata.combat_state
    state.participants.append(get_participant(other_ctx.userdata.combat_state, other_pid))
    state.initiative_order.append(other_pid)
    get_participant(state, pid).hp_current = 2
    await declare(ctx, pid, eid, "Absorb")
    result = await resolve(ctx)
    packet = next(p for p in result["packets"] if p["actor_id"] == eid)
    assert packet["damage"] == 3 and packet["self_healed"] == 2
    assert get_participant(await reload(ctx), eid).hp_current == 3


async def test_loader_missing_malformed_and_empty_catalog(reset_db_pool):
    pool = await db.get_pool()

    async def load(key):
        return await load_creature_enemy(key, encounter_id="enc137", enemy_id="enemy137", role="standard")

    with pytest.raises(ValueError, match=r"missing137.*enc137.*enemy137"):
        await load("missing137")
    original = await pool.fetchval("SELECT data FROM creatures WHERE id = 'bandit'")
    try:
        bad = json.loads(original)
        variants = []
        bad["attacks"][0]["properties"] = ["grapple"]
        variants.append(bad)
        variants.append({**json.loads(original), "hp": "wrong"})
        variants.append({**json.loads(original), "id": "mismatched137"})
        for bad in variants:
            await pool.execute("UPDATE creatures SET data=$1::jsonb WHERE id='bandit'", json.dumps(bad))
            with pytest.raises(ValueError, match=r"bandit.*enc137.*enemy137"):
                await load("bandit")
    finally:
        await pool.execute("UPDATE creatures SET data=$1::jsonb WHERE id='bandit'", original)
    rows = await pool.fetch("SELECT id, data FROM creatures")
    assert rows
    try:
        await pool.execute("DELETE FROM creatures")
        with pytest.raises(ValueError, match=r"bandit.*enc137.*enemy137"):
            await load("bandit")
    finally:
        for r in rows:
            await pool.execute("INSERT INTO creatures(id,data) VALUES($1,$2::jsonb)", r["id"], r["data"])


async def test_authored_to_hit_and_saves_reach_resolvers(runtime):
    import check_resolution_save
    from rules_engine import proficiency_bonus

    pool = await db.get_pool()
    original = await pool.fetchval("SELECT data FROM creatures WHERE id = 'hollow_knight'")
    try:
        authored = json.loads(original)
        authored["attacks"][0]["to_hit"] = 17
        await pool.execute("UPDATE creatures SET data=$1::jsonb WHERE id='hollow_knight'", json.dumps(authored))
        ctx, pid, eid, _ = await runtime("hollow_knight", role="elite")
    finally:
        await pool.execute("UPDATE creatures SET data=$1::jsonb WHERE id='hollow_knight'", original)
    await declare(ctx, pid, eid, "Corrupted Blade")
    result = await resolve(ctx)
    packet = next(p for p in result["packets"] if p["actor_id"] == eid)
    assert packet["attack_total"] == 31
    assert packet["damage"] == 3
    state = await reload(ctx)
    actor = state.get_participant(eid)
    assert actor is not None
    with patch("check_resolution.dice_roll", return_value=_d20(10)):
        proficient = check_resolution_save.roll_participant_save(actor, "WIS", 12, "frightened")
        actor.saving_throw_proficiencies = []
        untrained = check_resolution_save.roll_participant_save(actor, "WIS", 12, "frightened")
    assert proficient.total - untrained.total == proficiency_bonus(actor.level)
    assert proficient.success is True and untrained.success is False


@pytest.mark.parametrize(
    "species,name",
    [
        ("bandit", "Dirty Fighting"),
        ("ashmark_soldier", "Shield Bash"),
        ("cult_leader", "Hold Person"),
        ("hollow_knight", "Shield Slam"),
    ],
)
async def test_conditions_reach_real_resolvers(runtime, species, name):
    ctx, pid, eid, enemy = await runtime(species)
    await declare(ctx, pid, eid, name)
    face = 13 if species == "hollow_knight" else 2
    with patch(
        "check_resolution_save.roll_participant_save", wraps=__import__("check_resolution_save").roll_participant_save
    ) as consumer:
        result = await resolve(ctx, face=face)
    assert consumer.called
    packet = next(p for p in result["packets"] if p["actor_id"] == eid)
    action = next(a for a in enemy["action_pool"] if a["name"] == name)
    assert packet["condition_inflicted"] == action["applies_condition"]
    assert packet["save_dc"] == action["dc"]


async def test_command_focus_bonus_reaches_attack(runtime):
    ctx, pid, eid, _ = await runtime("ashmark_sergeant")
    state = ctx.userdata.combat_state
    ally = await load_creature_enemy("ashmark_soldier", encounter_id="enc137", enemy_id="soldier137", role="standard")
    state.participants.append(participant(ally))
    state.initiative_order.append("soldier137")
    await combat_turn.declare_phase(
        ctx,
        [
            DefendDecl(kind="defend", actor_id=pid),
            AttackDecl(kind="attack", actor_id=eid, action="Rally", target_id=pid, rider=""),
            AttackDecl(kind="attack", actor_id="soldier137", action="Longsword", target_id=pid, rider=""),
        ],
    )
    result = await resolve(ctx)
    packet = next(p for p in result["packets"] if p["actor_id"] == "soldier137")
    assert packet["attack_total"] == 21
