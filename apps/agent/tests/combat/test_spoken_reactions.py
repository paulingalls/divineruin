"""Actual reaction offers, activation and benefits require fictional delivery."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from combat._helpers import _ctx_at_resolution
from combat._reaction_helpers import _guarded_ally_state, reaction_state, silence
from livekit.agents.llm import ToolError
from sample_fixtures import make_db_mod
from voice_condition_fixtures import participant, spatial_record

import abilities
import ability_tools
import reaction_gate
import reaction_spend
from conditions import apply_condition

SPOKEN = ("bard_countercharm", "diplomat_countercharm", "marshal_interceding_order")


@pytest.mark.parametrize("ability_id", SPOKEN)
@pytest.mark.parametrize(
    "actor_id,restriction",
    [
        ("player_1", "silence"),
        ("player_2", "silence"),
        ("player_2", "deafened"),
    ],
)
def test_offers_and_validator_refuse_impossible_delivery(ability_id, actor_id, restriction):
    state = reaction_state(ability_id)
    assert state.open_window is not None
    if restriction == "silence":
        silence(state, actor_id)
    else:
        participant(state, actor_id).conditions = apply_condition([], "deafened", source="test")
    with pytest.raises(ValueError, match=r"speak|hear|silenced"):
        reaction_gate.validate_reaction_activation(state, "player_1", ability_id)
    assert reaction_gate.offered_reactions(state) == []
    assert not reaction_spend.is_spent(state.reactions_available["player_1"])


@pytest.mark.parametrize("ability_id", SPOKEN)
def test_deafened_source_and_unrelated_recipient_do_not_block_offer(ability_id):
    state = reaction_state(ability_id)
    assert state.open_window is not None
    participant(state, "player_1").conditions = apply_condition([], "deafened", source="test")
    participant(state, "goblin_scout_1").conditions = apply_condition([], "deafened", source="test")
    assert reaction_gate.offered_reactions(state) == [
        {
            "actor_id": "player_1",
            "id": ability_id,
            "name": abilities.get_ability(ability_id).name,
        }
    ]


@pytest.mark.parametrize("ability_id", SPOKEN)
@pytest.mark.parametrize("entry", ["public", "unlocked"])
@pytest.mark.asyncio
async def test_activation_guards_before_debit_and_binds_window_recipient(ability_id, entry):
    state = reaction_state(ability_id)
    assert state.open_window is not None
    silence(state, "player_2")
    ctx = _ctx_at_resolution(state=state, reaction_ids=(ability_id,))
    db_mod, _ = make_db_mod()
    queries = MagicMock(
        get_players_for_update=AsyncMock(
            return_value={
                "player_1": {
                    "class": ability_id.split("_")[0],
                    "level": 20,
                    "stamina": {"current": 100},
                    "focus": {"current": 100},
                    "conditions": [],
                }
            }
        )
    )
    persistence = MagicMock(owns_elective=AsyncMock(return_value=True), update_player_resources=AsyncMock())
    function = (
        ability_tools._request_ability_activation_impl
        if entry == "public"
        else ability_tools._request_ability_activation_unlocked
    )
    with ctx.userdata._bind_authenticated_actor("player_1", 1, lambda *_: None):
        with pytest.raises(ToolError, match=r"hear|silenced"):
            await function(
                ctx, ability_id, target_id="player_1", db_mod=db_mod, queries_mod=queries, persistence_mod=persistence
            )
    persistence.update_player_resources.assert_not_awaited()
    assert not reaction_spend.is_spent(state.reactions_available["player_1"])


@pytest.mark.parametrize("corruption", ["spatial", "target", "stage", "trigger", "kind", "actor"])
def test_offer_reader_propagates_corrupt_required_state(corruption):
    state = reaction_state("bard_countercharm")
    assert state.open_window is not None
    if corruption == "spatial":
        state.spatial = None
    elif corruption == "target":
        state.open_window["target_id"] = "absent"
    elif corruption == "stage":
        state.open_window["stage"] = "broken"
    elif corruption == "trigger":
        state.open_window["triggers"].append("unknown")
    elif corruption == "kind":
        state.open_window["action_kind"] = "unknown"
    else:
        state.open_window["actor_id"] = "absent"
    with pytest.raises(ValueError):
        reaction_gate.offered_reactions(state)


@pytest.mark.parametrize(
    "ability_id,reader",
    [
        ("bard_countercharm", "save"),
        ("diplomat_countercharm", "save"),
        ("marshal_interceding_order", "ac"),
    ],
)
@pytest.mark.parametrize("restriction", ["deafened", "silence"])
def test_spent_benefit_eligibility_uses_live_recipient_after_reload(ability_id, reader, restriction):
    import combat_reaction_effect
    from session_data import CombatState

    state = reaction_state(ability_id)
    assert state.open_window is not None
    state.reactions_available["player_1"] = reaction_spend.spend(ability_id, state.open_window, held_seq=0)

    def benefit(current):
        if reader == "save":
            return combat_reaction_effect.save_advantage(current, current.held_actions[0], "charmed")
        return combat_reaction_effect.ac_bonus(current, current.held_actions[0])

    assert benefit(state)
    if restriction == "deafened":
        participant(state, "player_2").conditions = apply_condition([], "deafened", source="test")
    else:
        silence(state, "player_2")
    state = CombatState.from_dict(state.to_dict())
    assert state.open_window is not None
    assert not benefit(state)
    assert reaction_spend.is_spent(state.reactions_available["player_1"])
    if reader == "ac":
        packets = combat_reaction_effect.close(state, state.held_actions[0], state.open_window, attack_action={})
        assert packets[0]["mechanical_effect"] is None
    participant(state, "player_2").conditions = []
    spatial_record(state)["zones"] = {}
    assert benefit(state)


@pytest.mark.parametrize("ability_id", SPOKEN)
@pytest.mark.asyncio
async def test_public_activation_checks_delivery_independently_of_transaction_body(ability_id, monkeypatch):
    state = reaction_state(ability_id)
    assert state.open_window is not None
    silence(state, "player_1")
    ctx = _ctx_at_resolution(state=state, reaction_ids=(ability_id,))
    body = AsyncMock(return_value="{}")
    monkeypatch.setattr(ability_tools, "_request_ability_activation_unlocked", body)
    with ctx.userdata._bind_authenticated_actor("player_1", 1, lambda *_: None):
        with pytest.raises(ToolError, match="silenced"):
            await ability_tools._request_ability_activation_impl(ctx, ability_id)
    body.assert_not_awaited()
    assert not reaction_spend.is_spent(state.reactions_available["player_1"])


def test_unknown_delivery_id_is_loud_at_actual_offer_reader(monkeypatch):
    import ability_voice_rules

    state = reaction_state("bard_countercharm")
    assert state.open_window is not None
    monkeypatch.delitem(ability_voice_rules.POLICIES, "bard_countercharm")
    with pytest.raises(ValueError, match="Unclassified"):
        reaction_gate.offered_reactions(state)


@pytest.mark.parametrize("ability_id", ["marshal_countermand", "spy_plausible_deniability", "diplomat_objection"])
@pytest.mark.parametrize("recipient_deaf", [True, False])
def test_contested_reaction_listener_is_the_acting_enemy(ability_id, recipient_deaf):
    state = reaction_state(ability_id)
    assert state.open_window is not None
    state.open_window["triggers"] = ["on_enemy_action"]
    state.open_window["action_kind"] = {
        "marshal_countermand": "command",
        "spy_plausible_deniability": "accusation",
        "diplomat_objection": "attack",
    }[ability_id]
    state.open_window["target_id"] = "player_1"
    deaf_id = "goblin_scout_1" if recipient_deaf else "player_2"
    participant(state, deaf_id).conditions = apply_condition([], "deafened", source="test")
    offers = reaction_gate.offered_reactions(state)
    assert bool(offers) is not recipient_deaf


@pytest.mark.parametrize("ability_id", ["bard_countercharm", "diplomat_countercharm"])
@pytest.mark.asyncio
async def test_actual_countercharm_save_loses_benefit_when_listener_becomes_deafened(ability_id):
    import random
    from unittest.mock import patch

    from combat._helpers import _activate, _resolve_deps
    from combat._reaction_helpers import _drain, _pause_at, _reaction_packet

    from dice import roll as roll_dice
    from session_data import CombatState

    state = _guarded_ally_state()
    enemy = participant(state, "goblin_scout_1")
    enemy.action_pool = [
        {
            "name": "Shriek",
            "damage": "0",
            "damage_type": "none",
            "properties": [],
            "applies_condition": "frightened",
            "save": "wisdom",
            "dc": 13,
        }
    ]
    state.pending_declarations[enemy.id]["action"] = "Shriek"
    ctx = _ctx_at_resolution(state=state, reaction_ids=(ability_id,))
    deps = _resolve_deps()
    packets = []
    rng = random.Random(1)
    with patch(
        "check_resolution.dice_roll", side_effect=lambda notation, **kw: roll_dice(notation, rng=kw.get("rng") or rng)
    ):
        await _pause_at(ctx, deps, actor_id=enemy.id, stage="pre_roll", packets=packets)
        await _activate(ctx, ability_id, player_class=ability_id.split("_")[0])
        state = ctx.userdata.combat_state
        participant(state, "player_2").conditions = apply_condition([], "deafened", source="test")
        ctx.userdata.combat_state = CombatState.from_dict(state.to_dict())
        await _drain(ctx, deps, packets)
    summary = next(packet for packet in packets if packet.get("condition_inflicted") == "frightened")
    assert "save_advantage" not in summary
    assert _reaction_packet(packets)["mechanical_effect"] is None


@pytest.mark.parametrize("restriction", ["source_silence", "recipient_silence", "recipient_deafened"])
@pytest.mark.asyncio
async def test_delivery_is_rechecked_after_awaited_player_lock(restriction):
    state = reaction_state("marshal_interceding_order")
    ctx = _ctx_at_resolution(state=state, reaction_ids=("marshal_interceding_order",))
    db_mod, _ = make_db_mod()

    async def lock(_ids, **_kwargs):
        if restriction == "source_silence":
            silence(state, "player_1")
        elif restriction == "recipient_silence":
            silence(state, "player_2")
        else:
            participant(state, "player_2").conditions = apply_condition([], "deafened", source="test")
        return {"player_1": {"class": "marshal", "level": 20, "stamina": {"current": 100}, "focus": {"current": 100}}}

    queries = MagicMock(get_players_for_update=AsyncMock(side_effect=lock))
    persistence = MagicMock(update_player_resources=AsyncMock())
    with ctx.userdata._bind_authenticated_actor("player_1", 1, lambda *_: None):
        with pytest.raises(ToolError, match=r"silenced|hear"):
            await ability_tools._request_ability_activation_impl(
                ctx, "marshal_interceding_order", db_mod=db_mod, queries_mod=queries, persistence_mod=persistence
            )
    persistence.update_player_resources.assert_not_awaited()
    assert not reaction_spend.is_spent(state.reactions_available["player_1"])
