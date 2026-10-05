"""Halving must also rewrite overkill, dramatic verdict, bonus damage and target_killed so downstream reports describe the landed blow."""

from unittest.mock import MagicMock

import pytest
from combat._helpers import _activate, _ctx_at_resolution, _resolve_deps
from combat._reaction_helpers import (
    _drain,
    _enemy_blow,
    _guarded_ally_state,
    _patched_accrual,
    _pause_at,
    _reaction_packet,
    _shield_bearing_deps,
)

import combat_reaction_effect
import reaction_spend
import reaction_windows
from check_resolution_attack import AttackResult
from combat_support import deserialize_roll, serialize_roll
from session_data import CombatParticipant

UNCANNY_DODGE = "rogue_uncanny_dodge"
RETALIATING_SHIELD = "guardian_retaliating_shield"


def _killing_resolver(damage: int):
    """A resolve_attack mock that reports a killing blow the way the real resolver does.

    ``_damage_resolver`` leaves ``overkill`` at 0 and never sets the dramatic verdict, so under it
    a blow that drops the target still carries none of the fields the halving has to rewrite —
    check_resolution_attack.py:167-194 sets all three together on a kill. No other resolver in the
    suite can show what halving does to a blow that was about to kill someone.
    """

    def _resolve(attacker_data, action, target_ac, target_hp, attack_mod=0, damage_mult=1.0, target_conditions=()):
        dealt = max(0, int(damage * damage_mult))
        remaining = max(0, target_hp - dealt)
        killed = remaining == 0
        return AttackResult(
            hit=True,
            roll=15,
            attack_modifier=3,
            attack_total=18,
            target_ac=target_ac,
            damage=dealt,
            damage_type="slashing",
            target_hp_remaining=remaining,
            target_killed=killed,
            overkill=max(0, dealt - target_hp),
            dramatic=killed,
            context="killing_blow" if killed else "",
            narrative_hint="A clean strike.",
        )

    r = MagicMock()
    r.resolve_attack = MagicMock(side_effect=_resolve)
    return r


def _self_targeted_round(*, player_hp: int):
    """A round whose one held blow falls on player_1, who is also the reactor."""
    state = _guarded_ally_state(target_id="player_1")
    kael = state.get_participant("player_1")
    assert kael is not None
    kael.hp_current = player_hp
    return _ctx_at_resolution(state=state, reaction_ids=(UNCANNY_DODGE,))


@pytest.mark.asyncio
async def test_halving_a_lethal_blow_fells_the_player_instead_of_killing_them_outright():
    """Recompute overkill after halving so a survivable fallen result cannot retain an instant-death verdict."""
    ctx = _self_targeted_round(player_hp=10)
    deps = {**_resolve_deps(), "resolver": _killing_resolver(60)}
    packets: list[dict] = []

    await _pause_at(ctx, deps, actor_id="goblin_scout_1", stage=reaction_windows.POST_ROLL, packets=packets)
    await _activate(ctx, UNCANNY_DODGE, player_class="rogue")
    await _drain(ctx, deps, packets)

    kael = ctx.userdata.combat_state.get_participant("player_1")
    assert (kael.is_fallen, kael.is_dead) == (True, False)
    assert _enemy_blow(packets)["damage"] == 30


@pytest.mark.asyncio
async def test_a_killing_blow_the_halving_survives_is_no_longer_narrated_as_one():
    """Allow honest encounter-context promotion; forbid only the stale killing-blow label."""
    ctx = _self_targeted_round(player_hp=15)
    deps = {**_resolve_deps(), "resolver": _killing_resolver(20)}
    packets: list[dict] = []

    await _pause_at(ctx, deps, actor_id="goblin_scout_1", stage=reaction_windows.POST_ROLL, packets=packets)
    await _activate(ctx, UNCANNY_DODGE, player_class="rogue")
    await _drain(ctx, deps, packets)

    blow = _enemy_blow(packets)
    assert blow["context"] != "killing_blow"
    kael = ctx.userdata.combat_state.get_participant("player_1")
    assert (kael.hp_current, kael.is_fallen) == (5, False)


def test_halve_rewrites_every_field_the_blow_is_reported_through():
    """bonus_damage is part of damage; leaving it whole could report a rider larger than the halved total."""
    rolled = AttackResult(
        hit=True,
        roll=15,
        attack_modifier=3,
        attack_total=18,
        target_ac=14,
        damage=20,
        damage_type="slashing",
        target_hp_remaining=0,
        target_killed=True,
        overkill=5,
        bonus_damage=6,
        bonus_damage_type="necrotic",
        narrative_hint="A clean strike.",
    )
    head = {"roll": serialize_roll(rolled, 14)}
    target = CombatParticipant(
        id="player_1", name="Kael", type="player", initiative=15, hp_current=15, hp_max=25, ac=14
    )

    combat_reaction_effect.halve(head, target)

    halved, effective_ac = deserialize_roll(head["roll"])
    assert effective_ac == 14
    assert (halved.damage, halved.bonus_damage) == (10, 3)
    assert (halved.target_hp_remaining, halved.target_killed, halved.overkill) == (5, False, 0)


@pytest.mark.asyncio
async def test_uncanny_dodge_spent_by_a_bystander_leaves_the_allys_damage_whole():
    """Install the refused bystander spend directly to prove the effect guard protects against bad records from another path."""
    ctx = _ctx_at_resolution(state=_guarded_ally_state(), reaction_ids=("guardian_intercept",))
    deps = _resolve_deps(damage=6)
    packets: list[dict] = []

    await _pause_at(ctx, deps, actor_id="goblin_scout_1", stage=reaction_windows.POST_ROLL, packets=packets)
    cs = ctx.userdata.combat_state
    cs.reactions_available["player_1"] = reaction_spend.spend(
        UNCANNY_DODGE, cs.open_window, held_seq=cs.held_actions[0]["seq"]
    )
    await _drain(ctx, deps, packets)

    assert _enemy_blow(packets)["damage"] == 6
    assert ctx.userdata.combat_state.get_participant("player_2").hp_current == 14
    assert _reaction_packet(packets)["mechanical_effect"] is None


@pytest.mark.asyncio
async def test_a_shield_reaction_spent_by_a_bystander_wears_nobodys_shield():
    """Install a bystander spend directly; target-inventory wear must not bill an ally for another player's reaction."""
    ctx = _ctx_at_resolution(state=_guarded_ally_state(), reaction_ids=("guardian_intercept",))
    deps = _shield_bearing_deps()
    packets: list[dict] = []

    with _patched_accrual() as accrue:
        await _pause_at(ctx, deps, actor_id="goblin_scout_1", stage=reaction_windows.POST_ROLL, packets=packets)
        cs = ctx.userdata.combat_state
        cs.reactions_available["player_1"] = reaction_spend.spend(
            RETALIATING_SHIELD, cs.open_window, held_seq=cs.held_actions[0]["seq"]
        )
        await _drain(ctx, deps, packets)

    assert "shield" not in _enemy_blow(packets)["durability"]
    accrue.assert_not_awaited()
    assert _reaction_packet(packets)["mechanical_effect"] is None
