"""A held action pauses only when its exact window offers a reaction."""

import pytest
from combat._helpers import _ac_sensitive_resolver, _call, _ctx_at_resolution, _resolution_state, _resolve_deps

import event_types as E
from session_data import CombatParticipant


@pytest.mark.asyncio
@pytest.mark.parametrize("attack_total,expected_stage", [(18, "post_roll"), (1, None)])
async def test_uncanny_dodge_skips_pre_roll_and_only_pauses_on_a_hit(attack_total, expected_stage):
    ctx = _ctx_at_resolution(enemy_hp=20, reaction_ids=("rogue_uncanny_dodge",))
    deps = {**_resolve_deps(), "resolver": _ac_sensitive_resolver(attack_total, 3)}

    await _call(ctx, deps)
    ctx.userdata.event_bus.drain()
    result = await _call(ctx, deps)

    window = result["next"]["waiting_on"]
    assert window is None if expected_stage is None else window["stage"] == expected_stage
    if window is not None:
        assert window["reactions"] == [{"actor_id": "player_1", "id": "rogue_uncanny_dodge", "name": "Uncanny Dodge"}]
    else:
        assert result["beat"] == "declaration"
        assert ctx.userdata.combat_state.held_actions == []
        assert ctx.userdata.combat_state.get_participant("player_1").hp_current == 25
        assert len([packet for packet in result["packets"] if packet["actor_id"] == "goblin_scout_1"]) == 1
    events = [event.event_type for event in ctx.userdata.event_bus.drain()]
    assert events.count(E.DICE_ROLL) == 1
    assert events.index(E.DICE_ROLL) < events.index(E.COMBAT_UI_UPDATE)


@pytest.mark.asyncio
async def test_self_reaction_follows_the_target():
    state = _resolution_state(enemy_hp=20)
    state.participants.append(
        CombatParticipant(id="player_2", name="Bren", type="player", initiative=8, hp_current=20, hp_max=20, ac=14)
    )
    state.initiative_order.append("player_2")
    state.pending_declarations["goblin_scout_1"]["target_id"] = "player_2"
    ctx = _ctx_at_resolution(state=state, reaction_ids=("rogue_uncanny_dodge",))
    deps = _resolve_deps()

    await _call(ctx, deps)
    result = await _call(ctx, deps)
    assert result["next"]["waiting_on"] is None
    assert ctx.userdata.combat_state.get_participant("player_2").hp_current == 17

    state = _resolution_state(enemy_hp=20)
    state.participants.append(
        CombatParticipant(
            id="player_2",
            name="Bren",
            type="player",
            initiative=8,
            hp_current=20,
            hp_max=20,
            ac=14,
            has_reaction_ability=True,
            reaction_ids=["rogue_uncanny_dodge"],
        )
    )
    state.initiative_order.append("player_2")
    state.pending_declarations["goblin_scout_1"]["target_id"] = "player_2"
    ctx = _ctx_at_resolution(state=state)
    await _call(ctx, deps)
    window = (await _call(ctx, deps))["next"]["waiting_on"]
    assert window["stage"] == "post_roll"
    assert [row["actor_id"] for row in window["reactions"]] == ["player_2"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,reaction,offered",
    [
        ("attack", "marshal_countermand", False),
        ("command", "marshal_countermand", True),
        ("accusation", "spy_plausible_deniability", True),
    ],
)
async def test_social_subject_controls_the_pre_roll_pause(kind, reaction, offered):
    state = _resolution_state(enemy_hp=20)
    enemy = state.get_participant("goblin_scout_1")
    if kind != "attack":
        enemy.action_pool.append({"name": "Order", "kind": kind, "properties": []})
        state.pending_declarations[enemy.id]["action"] = "Order"
    ctx = _ctx_at_resolution(state=state, reaction_ids=(reaction,))
    deps = _resolve_deps()

    await _call(ctx, deps)
    result = await _call(ctx, deps)
    window = result["next"]["waiting_on"]
    assert (window is not None) is offered
    if window is not None:
        assert window["stage"] == "pre_roll"
        assert [row["id"] for row in window["reactions"]] == [reaction]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reaction,kind,target_other,hollow,pauses",
    [
        ("spy_plausible_deniability", "accusation", True, False, False),
        ("spy_plausible_deniability", "accusation", False, False, True),
        ("diplomat_objection", "command", False, True, False),
        ("diplomat_objection", "command", False, False, True),
    ],
)
async def test_social_identity_and_accused_subject(reaction, kind, target_other, hollow, pauses):
    state = _resolution_state(enemy_hp=20)
    enemy = state.get_participant("goblin_scout_1")
    enemy.action_pool.append({"name": "Order", "kind": kind, "properties": []})
    enemy.category = "hollow_rend" if hollow else ""
    state.pending_declarations[enemy.id]["action"] = "Order"
    if target_other:
        state.participants.append(
            CombatParticipant(id="player_2", name="Bren", type="player", initiative=8, hp_current=20, hp_max=20, ac=14)
        )
        state.initiative_order.append("player_2")
        state.pending_declarations[enemy.id]["target_id"] = "player_2"
    ctx = _ctx_at_resolution(state=state, reaction_ids=(reaction,))

    await _call(ctx, _resolve_deps())
    window = (await _call(ctx, _resolve_deps()))["next"]["waiting_on"]
    assert (window is not None) is pauses
    if window is not None:
        assert [row["id"] for row in window["reactions"]] == [reaction]


@pytest.mark.asyncio
async def test_ally_targeted_reaction_binds_to_another_player():
    state = _resolution_state(enemy_hp=20)
    state.participants.append(
        CombatParticipant(id="player_2", name="Bren", type="player", initiative=8, hp_current=20, hp_max=20, ac=14)
    )
    state.initiative_order.append("player_2")
    state.pending_declarations["goblin_scout_1"]["target_id"] = "player_2"
    ctx = _ctx_at_resolution(state=state, reaction_ids=("cleric_shield_of_faith",))

    await _call(ctx, _resolve_deps())
    window = (await _call(ctx, _resolve_deps()))["next"]["waiting_on"]
    assert window["stage"] == "pre_roll"
    assert [row["actor_id"] for row in window["reactions"]] == ["player_1"]


@pytest.mark.asyncio
@pytest.mark.parametrize("grapple,hit,pauses", [(True, True, True), (True, False, False), (False, True, False)])
async def test_condition_reaction_requires_a_landed_grapple(grapple, hit, pauses):
    state = _resolution_state(enemy_hp=20)
    if grapple:
        state.get_participant("goblin_scout_1").action_pool[0]["properties"] = ["grapple"]
    ctx = _ctx_at_resolution(state=state, reaction_ids=("rogue_slippery",))
    deps = {**_resolve_deps(), "resolver": _ac_sensitive_resolver(18 if hit else 1, 3)}

    await _call(ctx, deps)
    result = await _call(ctx, deps)
    window = result["next"]["waiting_on"]
    assert (window is not None) is pauses
    if window is not None:
        assert window["stage"] == "post_roll"
        assert [row["id"] for row in window["reactions"]] == ["rogue_slippery"]
