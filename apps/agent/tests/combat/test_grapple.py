import copy
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from combat._helpers import _ctx_at_resolution, _make_combat_state, _resolve_deps, _resolve_round
from livekit.agents.llm import ToolError
from sample_fixtures import make_context

import combat_conditions_persist
import combat_prompts
import combat_turn
import conditions
from check_resolution_attack import AttackResult
from combat_init import _start_combat_impl, _validate_enemy_action_shapes
from combat_support import _participant_summary
from declaration_payloads import ManeuverDecl
from tests.combat.test_start_combat import _make_start_combat_mocks

_CATALOG = json.loads((Path(__file__).resolve().parents[4] / "content" / "encounter_templates.json").read_text())


def _encounter() -> dict:
    return copy.deepcopy(next(row for row in _CATALOG if row["id"] == "ruins_mawling_pair"))


def _mawlings() -> list[dict]:
    return _encounter()["enemies"]


def test_real_mawling_grapple_actions_author_escape_dc_13():
    grapples = [
        (enemy["id"], action)
        for enemy in _mawlings()
        for action in enemy["action_pool"]
        if "grapple" in action.get("properties", [])
    ]

    assert [(enemy_id, action["name"], action.get("escape_dc")) for enemy_id, action in grapples] == [
        ("mawling_1", "Seizing Grab", 13),
        ("mawling_2", "Seizing Grab", 13),
    ]
    _validate_enemy_action_shapes(_mawlings())


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_dc", [None, "13", True])
async def test_combat_start_validation_refuses_grapple_without_integer_escape_dc(bad_dc):
    encounter = _encounter()
    grab = next(
        action for action in encounter["enemies"][0]["action_pool"] if "grapple" in action.get("properties", [])
    )
    if bad_dc is None:
        grab.pop("escape_dc", None)
    else:
        grab["escape_dc"] = bad_dc
    mutations, queries, content = _make_start_combat_mocks()
    content.get_encounter_template.return_value = encounter

    with pytest.raises(ToolError, match="escape_dc"):
        await _start_combat_impl(
            make_context(), encounter["id"], "Mawlings close in.", mutations=mutations, queries=queries, content=content
        )


def _grab() -> dict:
    return next(action for action in _mawlings()[0]["action_pool"] if "grapple" in action.get("properties", []))


def _grapple_round_state():
    state = _make_combat_state(player_hp=25, enemy_hp=18)
    enemy = state.get_participant("goblin_scout_1")
    assert enemy is not None
    enemy.id = "mawling_1"
    enemy.name = "Mawling"
    enemy.action_pool = [_grab()]
    state.initiative_order = ["player_1", enemy.id]
    state.beat = "resolution"
    state.pending_declarations = {
        "player_1": {"type": "defend"},
        enemy.id: {"type": "attack", "action": "Seizing Grab", "target_id": "player_1"},
    }
    return state


def _miss_resolver():
    class Resolver:
        @staticmethod
        def resolve_attack(_attacker, _action, target_ac, target_hp, **_kwargs):
            return AttackResult(
                hit=False,
                roll=2,
                attack_modifier=2,
                attack_total=4,
                target_ac=target_ac,
                damage=0,
                damage_type="bludgeoning",
                critical_success=False,
                critical_failure=False,
                target_hp_remaining=target_hp,
                target_killed=False,
                narrative_hint="The grasp misses.",
            )

    return Resolver()


@pytest.mark.asyncio
async def test_seizing_grab_hit_lands_sourced_grapple_and_surfaces_it_to_dm():
    state = _grapple_round_state()
    ctx = _ctx_at_resolution(state=state)
    result = await _resolve_round(ctx, **_resolve_deps(damage=2))
    packet = next(packet for packet in result["packets"] if packet.get("action") == "Seizing Grab")
    assert packet["damage"] == 2
    assert packet["condition_inflicted"] == "grappled"
    final_state = ctx.userdata.combat_state
    assert final_state is not None
    player = final_state.get_participant("player_1")
    assert player is not None
    assert (
        next(condition for condition in player.conditions if condition["type"] == "grappled")["source"] == "mawling_1"
    )
    assert _participant_summary(player)["grappled_by"] == "mawling_1"
    assert result["next"]["grappled"] == [{"actor_id": "player_1", "name": player.name, "grappler_id": "mawling_1"}]


@pytest.mark.asyncio
async def test_seizing_grab_blocked_by_item_names_the_immunity_source():
    state = _grapple_round_state()
    player = state.get_participant("player_1")
    assert player is not None
    player.condition_immunities = {"grappled": "Anchor Ring"}
    ctx = _ctx_at_resolution(state=state)

    result = await _resolve_round(ctx, **_resolve_deps(damage=2))

    packet = next(packet for packet in result["packets"] if packet.get("action") == "Seizing Grab")
    assert packet["condition_immune"] == "grappled"
    assert packet["condition_immunity_source"] == "Anchor Ring"
    assert not conditions.has_condition(player.conditions, "grappled")


@pytest.mark.asyncio
async def test_a_later_seizing_grab_keeps_the_prior_source_and_reports_grapple_held():
    state = _grapple_round_state()
    enemy = state.get_participant("mawling_1")
    player = state.get_participant("player_1")
    assert enemy is not None and player is not None
    enemy.id = "mawling_2"
    state.initiative_order[-1] = enemy.id
    state.pending_declarations[enemy.id] = state.pending_declarations.pop("mawling_1")
    player.conditions = conditions.apply_condition([], "grappled", source="mawling_1")
    ctx = _ctx_at_resolution(state=state)
    result = await _resolve_round(ctx, **_resolve_deps(damage=2))
    player = ctx.userdata.combat_state.get_participant("player_1")
    grapples = [condition for condition in player.conditions if condition["type"] == "grappled"]
    assert [condition["source"] for condition in grapples] == ["mawling_1"]
    packet = next(packet for packet in result["packets"] if packet.get("action") == "Seizing Grab")
    assert packet["grapple_held"] is True
    assert "condition_inflicted" not in packet


@pytest.mark.asyncio
async def test_seizing_grab_that_drops_its_target_lands_no_grapple():
    state = _grapple_round_state()
    ctx = _ctx_at_resolution(state=state)
    result = await _resolve_round(ctx, **_resolve_deps(damage=25))
    packet = next(packet for packet in result["packets"] if packet.get("action") == "Seizing Grab")
    player = ctx.userdata.combat_state.get_participant("player_1")
    assert packet["target_fallen"] is True
    assert not conditions.has_condition(player.conditions, "grappled")
    assert not ({"condition_inflicted", "grapple_held"} & packet.keys())


@pytest.mark.asyncio
async def test_seizing_grab_miss_lands_nothing():
    state = _grapple_round_state()
    ctx = _ctx_at_resolution(state=state)
    deps = {**_resolve_deps(), "resolver": _miss_resolver()}
    result = await _resolve_round(ctx, **deps)

    packet = next(packet for packet in result["packets"] if packet.get("action") == "Seizing Grab")
    assert packet["hit"] is False
    assert "condition_inflicted" not in packet
    assert "grapple_held" not in packet
    player = ctx.userdata.combat_state.get_participant("player_1")
    assert player is not None
    assert not conditions.has_condition(player.conditions, "grappled")


@pytest.mark.asyncio
@pytest.mark.parametrize("condition_type", ["grappled", "restrained"])
async def test_speed_zero_condition_refuses_retreat_but_allows_attack(condition_type):
    state = _make_combat_state()
    state.beat = "declaration"
    player = state.get_participant("player_1")
    assert player is not None
    player.conditions = conditions.apply_condition([], condition_type, source="mawling_1")
    ctx = _ctx_at_resolution(state=state)
    mutations = AsyncMock()

    with pytest.raises(ToolError, match=condition_type):
        await combat_turn._declare_phase_impl(
            ctx,
            {player.id: {"type": "retreat"}},
            mutations=mutations,
        )

    result = await combat_turn._declare_phase_impl(
        ctx,
        {player.id: {"type": "attack", "action": "Longsword", "target_id": "goblin_scout_1"}},
        mutations=mutations,
    )
    assert json.loads(result)["accepted_actors"] == [player.id]


@pytest.mark.asyncio
async def test_grappled_is_not_persisted_after_combat(monkeypatch):
    state = _make_combat_state()
    player = state.get_participant("player_1")
    assert player is not None
    player.conditions = conditions.apply_condition([], "grappled", source="mawling_1")
    read = AsyncMock(return_value=[])
    write = AsyncMock()
    monkeypatch.setattr(combat_conditions_persist.db_mutations_conditions, "read_player_conditions", read)
    monkeypatch.setattr(combat_conditions_persist.db_mutations_conditions, "save_player_conditions", write)

    await combat_conditions_persist.reconcile_member_conditions(player, conn="conn")

    write.assert_not_awaited()


def test_grapple_vocabulary_reaches_schema_and_combat_prompt():
    description = ManeuverDecl.model_json_schema()["properties"]["target_id"]["description"]
    assert "target your grappler to break free" in description
    prompt = combat_prompts.COMBAT_PROMPT
    assert "breaks free by declaring maneuver on their grappler" in prompt
    assert "cannot retreat" in prompt
    assert all(
        token in prompt for token in ("grappled", "escape", "grapple_escaped", "grapple_held", "released_from_grapple")
    )


def _escape_round_state(*, dc=13, target_id="mawling_1"):
    state = _grapple_round_state()
    player = state.get_participant("player_1")
    grappler = state.get_participant("mawling_1")
    assert player is not None and grappler is not None
    player.attributes = {"strength": 8, "dexterity": 16}
    player.conditions = conditions.apply_condition([], "grappled", source=grappler.id)
    grappler.action_pool[0]["escape_dc"] = dc
    state.pending_declarations = {
        player.id: {"type": "maneuver", "target_id": target_id},
        grappler.id: {"type": "defend"},
    }
    return state


@pytest.mark.asyncio
@pytest.mark.parametrize(("face", "outcome", "still_grappled"), [(10, "escaped", False), (9, "failed", True)])
async def test_escape_uses_better_of_strength_or_dex_and_meeting_dc_succeeds(face, outcome, still_grappled):
    state = _escape_round_state()
    ctx = _ctx_at_resolution(state=state)

    with patch("random.randint", return_value=face):
        result = await _resolve_round(ctx, **_resolve_deps())

    packet = next(packet for packet in result["packets"] if packet["actor_id"] == "player_1")
    assert (packet["escape"], packet["escape_total"], packet["escape_dc"]) == (outcome, face + 3, 13)
    player = ctx.userdata.combat_state.get_participant("player_1")
    assert player is not None
    assert conditions.has_condition(player.conditions, "grappled") is still_grappled


@pytest.mark.asyncio
async def test_escape_reads_the_grapplers_authored_dc():
    state = _escape_round_state(dc=18)
    ctx = _ctx_at_resolution(state=state)

    with patch("random.randint", return_value=14):
        result = await _resolve_round(ctx, **_resolve_deps())

    packet = next(packet for packet in result["packets"] if packet["actor_id"] == "player_1")
    assert (packet["escape"], packet["escape_total"], packet["escape_dc"]) == ("failed", 17, 18)


@pytest.mark.asyncio
async def test_grappled_actor_maneuvering_on_someone_else_still_shoves():
    state = _escape_round_state(target_id="other_enemy")
    grappler = state.get_participant("mawling_1")
    assert grappler is not None
    other = copy.deepcopy(grappler)
    other.id = "other_enemy"
    other.name = "Other Enemy"
    state.participants.append(other)
    ctx = _ctx_at_resolution(state=state)

    with patch("random.randint", side_effect=[20, 1]):
        result = await _resolve_round(ctx, **_resolve_deps())

    packet = next(packet for packet in result["packets"] if packet["actor_id"] == "player_1")
    assert packet["shove"] == "knocked_prone"
    assert "escape" not in packet


@pytest.mark.asyncio
async def test_escape_fails_loud_when_the_grappler_has_no_authored_grapple_action():
    state = _escape_round_state()
    grappler = state.get_participant("mawling_1")
    assert grappler is not None
    grappler.action_pool = []
    ctx = _ctx_at_resolution(state=state)

    with pytest.raises(ValueError, match="escape_dc"):
        await _resolve_round(ctx, **_resolve_deps())
