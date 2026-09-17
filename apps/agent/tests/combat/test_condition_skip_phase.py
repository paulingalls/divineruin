import json
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest
from combat._helpers import _activate, _call, _ctx_at_resolution, _make_combat_state, _resolve_deps
from combat._reaction_helpers import _guarded_ally_state
from livekit.agents.llm import ToolError
from sample_fixtures import make_context

import check_resolution_attack
import combat_hold
import combat_phase
import combat_wrap
import reaction_gate
import reaction_spend
import reaction_windows
from combat_init import _start_combat_impl
from combat_prompts import COMBAT_PROMPT
from combat_support import _participant_summary
from combat_turn import _declare_phase_impl
from condition_restrictions import cannot_act
from encounter_roles import EncounterRole
from session_data import CombatParticipant, CombatState
from tests.combat.test_start_combat import SAMPLE_PLAYER, _make_start_combat_mocks


def _condition(name: str) -> dict:
    return {"type": name, "duration": 2, "source": "test", "stacks": 1}


def _blocked_roster() -> CombatState:
    state = _make_combat_state(enemy_hp=40)
    state.participants[0].conditions = [_condition("stunned")]
    state.participants[1].conditions = [_condition("incapacitated")]
    state.participants.extend(
        [
            CombatParticipant(
                id="companion_1",
                name="Bram",
                type="companion",
                initiative=13,
                hp_current=20,
                hp_max=20,
                ac=14,
                conditions=[_condition("paralyzed")],
                action_pool=[{"name": "Hammer", "damage": "1d8", "properties": []}],
            ),
            CombatParticipant(
                id="echo_1",
                name="Hollow Kael",
                type="temporary_hollowed",
                initiative=11,
                hp_current=12,
                hp_max=12,
                ac=12,
                conditions=[_condition("petrified")],
                action_pool=[{"name": "Claw", "damage": "1d6", "properties": []}],
            ),
            CombatParticipant(
                id="able_1",
                name="Able Scout",
                type="enemy",
                initiative=10,
                hp_current=20,
                hp_max=20,
                ac=12,
                action_pool=[{"name": "Spear", "damage": "1d6", "properties": []}],
            ),
        ]
    )
    return state


@pytest.mark.parametrize(
    ("actor_id", "action", "target_id", "name", "condition"),
    [
        ("player_1", "Longsword", "able_1", "Kael", "stunned"),
        ("companion_1", "Hammer", "able_1", "Bram", "paralyzed"),
        ("goblin_scout_1", "Scimitar", "player_1", "Goblin Scout", "incapacitated"),
        ("echo_1", "Claw", "player_1", "Hollow Kael", "petrified"),
    ],
)
@pytest.mark.asyncio
async def test_declaration_refuses_every_blocked_participant_band(actor_id, action, target_id, name, condition):
    ctx = make_context()
    ctx.userdata.combat_state = _blocked_roster()
    mutations = AsyncMock()

    with pytest.raises(ToolError) as refused:
        await _declare_phase_impl(
            ctx,
            {actor_id: {"type": "attack", "action": action, "target_id": target_id}},
            mutations=mutations,
        )

    message = str(refused.value).lower()
    assert all(token.lower() in message for token in (name, actor_id, condition, "omit", "helplessness"))
    mutations.save_combat_state.assert_not_awaited()


@pytest.mark.asyncio
async def test_declaration_accepts_payload_that_omits_blocked_actors():
    ctx = make_context()
    ctx.userdata.combat_state = _blocked_roster()
    mutations = AsyncMock()

    raw = await _declare_phase_impl(
        ctx,
        {"able_1": {"type": "attack", "action": "Spear", "target_id": "player_1"}},
        mutations=mutations,
    )

    assert json.loads(raw)["accepted_actors"] == ["able_1"]


def test_cannot_act_returns_blocking_conditions_in_bearer_order():
    assert cannot_act([_condition("stunned"), _condition("paralyzed")]) == ("stunned", "paralyzed")
    assert cannot_act([_condition("restrained")]) == ()


def test_next_envelope_and_roster_surface_who_cannot_act():
    state = _blocked_roster()
    expected = [
        {"actor_id": p.id, "name": p.name, "conditions": [p.conditions[0]["type"]]} for p in state.participants[:4]
    ]

    assert combat_wrap.next_envelope(state)["cannot_act"] == expected
    summaries = {p.id: _participant_summary(p) for p in state.participants}
    assert summaries["player_1"]["cannot_act"] == ["stunned"]
    assert summaries["able_1"]["cannot_act"] == []


@pytest.mark.asyncio
async def test_start_combat_handoff_carries_stored_player_block(mock_combat_agent_factory):
    mutations, queries, content = _make_start_combat_mocks()
    queries.get_player = AsyncMock(return_value={**deepcopy(SAMPLE_PLAYER), "conditions": [_condition("stunned")]})
    ctx = make_context()

    _, payload = await _start_combat_impl(
        ctx, "goblin_patrol", "Ambush!", mutations=mutations, queries=queries, content=content
    )

    roster = {p["id"]: p for p in json.loads(payload)["participants"]}
    assert roster["player_1"]["cannot_act"] == ["stunned"]
    assert roster["goblin_scout_1"]["cannot_act"] == []
    handoff = mock_combat_agent_factory.call_args.kwargs["chat_ctx"].items[0].text_content
    assert '"cannot_act": ["stunned"]' in handoff


@pytest.mark.asyncio
async def test_newly_stunned_ally_packet_resolves_false_without_damage():
    state = _make_combat_state(enemy_hp=40)
    state.beat = "resolution"
    state.pending_declarations = {"player_1": {"type": "attack", "action": "Longsword", "target_id": "goblin_scout_1"}}
    player = state.get_participant("player_1")
    enemy = state.get_participant("goblin_scout_1")
    assert player is not None and enemy is not None
    player.conditions = [_condition("stunned")]
    ctx = _ctx_at_resolution(state=state)
    before = enemy.hp_current

    deps = {**_resolve_deps(damage=3), "resolver": check_resolution_attack}
    payload = await _call(ctx, deps)

    assert payload["packets"] == [
        {"actor_id": "player_1", "resolved": False, "reason": "Kael is stunned and loses the phase"}
    ]
    enemy = ctx.userdata.combat_state.get_participant("goblin_scout_1")
    assert enemy is not None and enemy.hp_current == before


@pytest.mark.asyncio
async def test_stunned_held_enemy_opens_no_window_and_resolves_false():
    state = _guarded_ally_state(target_id="player_1")
    state.reactions_available = {"player_1": reaction_spend.unspent()}
    ctx = _ctx_at_resolution(state=state)
    deps: dict = _resolve_deps(damage=3)
    deps["resolver"] = check_resolution_attack
    await _call(ctx, deps)
    held = ctx.userdata.combat_state.get_participant("goblin_scout_1")
    player = ctx.userdata.combat_state.get_participant("player_1")
    assert held is not None and player is not None
    held.conditions = [_condition("stunned")]
    before = player.hp_current

    payload = await _call(ctx, deps)

    assert payload["next"]["waiting_on"] is None
    assert payload["packets"] == [
        {
            "actor_id": "goblin_scout_1",
            "resolved": False,
            "reason": "Goblin 1 is stunned and loses the phase",
        }
    ]
    player = ctx.userdata.combat_state.get_participant("player_1")
    assert player is not None and player.hp_current == before


def _stunned_reaction_state() -> CombatState:
    state = _guarded_ally_state(target_id="player_1")
    player = state.get_participant("player_1")
    assert player is not None
    player.conditions = [_condition("stunned")]
    player.has_reaction_ability = True
    player.reaction_ids = ["skirmisher_sidestep"]
    state.reactions_available = {"player_1": reaction_spend.unspent()}
    state.open_window = reaction_windows.open_window_for(
        round_number=1,
        seq=0,
        stage="pre_roll",
        actor_id="goblin_scout_1",
        target_id="player_1",
        action_kind="attack",
        triggers=reaction_windows.pre_roll_triggers({}),
    )
    state.held_actions = [{"seq": 0, "actor_id": "goblin_scout_1"}]
    return state


def test_stunned_player_is_not_offered_and_cannot_hold_the_beat():
    state = _stunned_reaction_state()
    with pytest.raises(ValueError, match=r"Kael.*stunned.*cannot react"):
        reaction_gate.validate_reaction_activation(state, "player_1", "skirmisher_sidestep")
    assert reaction_gate.offered_reactions(state) == []
    assert combat_hold.pause_allowed(state) is False


@pytest.mark.asyncio
async def test_live_activation_refuses_a_stunned_reactor_before_spending():
    ctx = make_context()
    ctx.userdata.combat_state = _stunned_reaction_state()

    with pytest.raises(ToolError, match=r"Kael.*stunned.*cannot react"):
        await _activate(ctx, "skirmisher_sidestep", player_class="skirmisher")


def test_prompt_tells_the_dm_to_omit_blocked_declarations():
    prompt = COMBAT_PROMPT.lower()
    assert all(token in prompt for token in ("cannot_act", "declares nothing", "helplessness"))


def _stunned_boss_state() -> CombatState:
    return CombatState(
        combat_id="boss",
        beat="wrap",
        initiative_order=["player_1", "boss_1"],
        participants=[
            CombatParticipant(
                id="player_1", name="Kael", type="player", initiative=15, hp_current=20, hp_max=20, ac=14
            ),
            CombatParticipant(
                id="boss_1",
                name="Ash Tyrant",
                type="enemy",
                initiative=10,
                hp_current=40,
                hp_max=40,
                ac=16,
                role=EncounterRole.BOSS,
                legendary_actions=0,
                conditions=[_condition("stunned")],
            ),
        ],
    )


def test_stunned_boss_is_not_refreshed_surfaced_or_allowed_to_spend():
    state = _stunned_boss_state()
    looped, advance = combat_phase.advance_combat_phase(state)
    boss = looped.get_participant("boss_1")
    assert boss is not None and boss.legendary_actions == 0
    assert advance.legendary_available == []
    stale = deepcopy(state)
    boss = stale.get_participant("boss_1")
    assert boss is not None
    boss.legendary_actions = 1
    assert combat_phase._boss_legendaries(stale) == []
    with pytest.raises(ValueError, match=r"Ash Tyrant.*stunned"):
        combat_phase.consume_legendary_action(stale, "boss_1")
