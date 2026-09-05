"""The guards inside a resolved reaction: whose blow it may touch, and what the rewritten roll says.

``test_reaction_resolution.py`` pins the two outcomes themselves — a halved blow, a blow turned
aside. This file pins the conditions those outcomes are gated on. Every check here exists because
DELETING the guard it names left the whole suite green (constraint 1): a guard nothing can red is
a guard that certifies rather than checks.

``combat_reaction_effect.halve`` REWRITES the held roll, so it owns four fields besides ``damage``
that describe the blow downstream: ``overkill`` (combat_support.py:105 turns it into INSTANT
DEATH), the killing-blow dramatic verdict the DM voices, ``bonus_damage``, and ``target_killed``
— which has no production reader today and is pinned only for coherence with the three that do.
Scaling ``damage`` alone leaves each of them describing the blow that was NOT dealt.
"""

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

    def _resolve(attacker_data, action, target_ac, target_hp, attack_mod=0, damage_mult=1.0):
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
    return _ctx_at_resolution(state=state)


@pytest.mark.asyncio
async def test_halving_a_lethal_blow_fells_the_player_instead_of_killing_them_outright():
    """Overkill is recomputed from the HALVED damage, not carried over from the roll.

    Instant death (combat_support.py:105) fires when ``overkill >= hp_max`` — no Fallen grace, no
    death saves, the character is gone. Kael is at 10 of 25 and takes 60: 50 past zero, well over
    his maximum. Uncanny Dodge makes it 30 — still enough to drop him, but only 20 past zero, so
    he FALLS. Carrying the roll's own 50 through the halving would end the campaign for a player
    whose reaction was supposed to save them.
    """
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
    """The killing-blow verdict is cleared when the halving leaves the target standing.

    ``context`` rides the packet and the DICE_ROLL for the DM to voice, and the resolver set it to
    ``killing_blow`` because at full damage this blow killed Kael. It did not, and a DM handed
    "killing_blow" for a player on 5 HP narrates a death that did not happen.

    Asserted as "not that label" rather than as an empty string: the apply half re-runs
    roll_attack's encounter-context overlay, which promotes an undramatic blow on the last enemy
    standing back to ``last_enemy``. That promotion is honest; only the stale kill claim is not.
    """
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
    """The arithmetic the two rounds above cannot both show at once, on one roll.

    ``bonus_damage`` is a COMPONENT of ``damage`` (check_resolution_attack.py:150 does
    ``damage += bonus_damage``) and the summary surfaces both, so a Temporary Hollowed attacker's
    necrotic die left unhalved reports a rider larger than the whole blow. Called directly because
    it is the arithmetic under test; the live path through it is AC1's test.
    """
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
    """A reaction only halves the blow aimed at the REACTOR.

    ``on_hit`` means "when YOU are hit"; taking an ally's damage is guardian_intercept's
    ``on_ally_hit``, a different and unwired mechanic. The open window offers both triggers to
    whoever is holding a reaction, so validate_reaction_activation accepts this spend — Bram is
    the one being hit, Kael reacts. Halving off it would invent the mechanic the catalog gives
    somebody else, and it would do so on a live path.
    """
    ctx = _ctx_at_resolution(state=_guarded_ally_state())
    deps = _resolve_deps(damage=6)
    packets: list[dict] = []

    await _pause_at(ctx, deps, actor_id="goblin_scout_1", stage=reaction_windows.POST_ROLL, packets=packets)
    await _activate(ctx, UNCANNY_DODGE, player_class="rogue")
    await _drain(ctx, deps, packets)

    assert _enemy_blow(packets)["damage"] == 6
    assert ctx.userdata.combat_state.get_participant("player_2").hp_current == 14
    assert _reaction_packet(packets)["mechanical_effect"] is None


@pytest.mark.asyncio
async def test_a_shield_reaction_spent_by_a_bystander_wears_nobodys_shield():
    """The shield hit comes off the TARGET's inventory, so a bystander's spend must accrue none.

    combat_support reads ``get_player_inventory(target.id)``: report a shield reaction for a
    reactor who is not the target and the wear lands on the ally's gear, billed to a reaction they
    never spent. Bram is the one hit here and both players are carrying a shield.
    """
    ctx = _ctx_at_resolution(state=_guarded_ally_state())
    deps = _shield_bearing_deps()
    packets: list[dict] = []

    with _patched_accrual() as accrue:
        await _pause_at(ctx, deps, actor_id="goblin_scout_1", stage=reaction_windows.POST_ROLL, packets=packets)
        await _activate(ctx, RETALIATING_SHIELD, player_class="guardian")
        await _drain(ctx, deps, packets)

    assert "shield" not in _enemy_blow(packets)["durability"]
    accrue.assert_not_awaited()
    assert _reaction_packet(packets)["mechanical_effect"] is None
