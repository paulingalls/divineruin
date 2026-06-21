"""Enhancer resolution through the combat packet path (M4.2, story-004).

Enhancers EXPAND what one declaration resolves into — never a second declaration.
These drive _resolve_one_packet (the per-packet resolver resolve_phase loops over):
extra_attack/shield_bash expand the ATTACK mechanically (extra HP-dealing swings),
the narrated riders attach a descriptive cue to the summary. A no-enhancer actor
resolves exactly one base action with no expansion (AC3).
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from combat._helpers import _fake_db_mod, _make_combat_state
from sample_fixtures import make_context

import combat_turn
from check_resolution_attack import AttackResult
from combat_phase import ResolutionPacket
from declarations import Declaration, DeclarationType
from session_data import CombatParticipant, CombatState

pytestmark = pytest.mark.asyncio

_WEAPON = {"name": "Longsword", "damage": "1d8", "damage_type": "slashing", "properties": []}


def _fixed_resolver(damage: int):
    """resolve_attack stand-in that always hits for a fixed amount, decrementing from the
    target's current HP each call — so an expanded sequence accumulates across swings."""

    def _resolve(_attacker_data, _action, target_ac, target_hp, attack_mod=0, damage_mult=1.0):
        remaining = max(0, target_hp - damage)
        return AttackResult(
            hit=True,
            roll=15,
            attack_modifier=3,
            attack_total=18,
            target_ac=target_ac,
            damage=damage,
            damage_type="slashing",
            critical_success=False,
            critical_failure=False,
            target_hp_remaining=remaining,
            target_killed=remaining <= 0,
            narrative_hint="The blade bites.",
        )

    r = MagicMock()
    r.resolve_attack = MagicMock(side_effect=_resolve)
    return r


def _mutations():
    m = MagicMock()
    m.save_combat_state = AsyncMock()
    m.update_player_hp = AsyncMock()
    return m


def _queries():
    q = MagicMock()
    q.get_player_inventory = AsyncMock(return_value=[])
    return q


def _break_mod():
    m = MagicMock()
    m.break_concentration_on_damage = AsyncMock(return_value=None)
    return m


def _player_attacking(*, enhancers: list[str], enemy_hp: int = 30):
    """A combat state where player_1 (with the given enhancers + a Longsword) faces a
    high-HP goblin, so an expanded sequence has room to land multiple swings."""
    cs = _make_combat_state(enemy_hp=enemy_hp)
    player = cs.get_participant("player_1")
    assert player is not None
    player.action_pool = [dict(_WEAPON)]
    player.enhancers = enhancers
    return cs


async def _resolve(cs, decl: Declaration, resolver, actor_id: str = "player_1") -> dict:
    ctx = make_context()
    packet = ResolutionPacket(actor_id=actor_id, declaration=decl, initiative=20)
    return await combat_turn._resolve_one_packet(
        ctx.userdata,
        cs,
        packet,
        mutations=_mutations(),
        queries=_queries(),
        resolver=resolver,
        concentration_break_mod=_break_mod(),
    )


def _attack(rider: str | None = None) -> Declaration:
    return Declaration(type=DeclarationType.ATTACK, action="Longsword", target_id="goblin_scout_1", rider=rider)


class TestMechanicalEnhancers:
    async def test_extra_attack_expands_to_two_attacks(self):
        # AC1: one Attack declaration resolves as 2 attacks — no second declaration.
        cs = _player_attacking(enhancers=["extra_attack"])
        enemy = cs.get_participant("goblin_scout_1")
        assert enemy is not None
        summary = await _resolve(cs, _attack(), _fixed_resolver(5))
        assert summary["resolved"] is True
        assert len(summary["attacks"]) == 2
        assert summary["damage"] == 10
        assert enemy.hp_current == 20  # 30 - 5 - 5

    async def test_shield_bash_adds_a_second_strike(self):
        cs = _player_attacking(enhancers=["shield_bash"])
        summary = await _resolve(cs, _attack(), _fixed_resolver(4))
        assert len(summary["attacks"]) == 2
        assert summary["attacks"][1]["action"] == "Shield Bash"

    async def test_extra_attack_kill_on_second_swing_aggregates_final_state(self):
        # The first swing leaves the goblin up (bloodied), the second drops it. The aggregated
        # summary must report the FINAL swing's target state — fallen=True, the post-kill
        # hp_status — not the still-up snapshot from the first swing, or the DM narrates a
        # fallen foe as alive.
        cs = _player_attacking(enhancers=["extra_attack"], enemy_hp=8)
        enemy = cs.get_participant("goblin_scout_1")
        assert enemy is not None
        summary = await _resolve(cs, _attack(), _fixed_resolver(5))
        assert len(summary["attacks"]) == 2
        assert summary["attacks"][0]["target_fallen"] is False  # first swing: 8 -> 3, still up
        assert summary["attacks"][1]["target_fallen"] is True  # second swing: 3 -> 0, falls
        assert summary["target_fallen"] is True
        assert summary["target_hp_status"] == summary["attacks"][1]["target_hp_status"]
        assert enemy.is_fallen is True

    async def test_extra_attack_stops_when_target_falls(self):
        # The second swing is skipped once the first drops the target (no hitting a corpse).
        cs = _player_attacking(enhancers=["extra_attack"], enemy_hp=5)
        enemy = cs.get_participant("goblin_scout_1")
        assert enemy is not None
        resolver = _fixed_resolver(5)
        summary = await _resolve(cs, _attack(), resolver)
        assert enemy.is_fallen is True
        assert resolver.resolve_attack.call_count == 1  # second swing skipped — no hitting a corpse
        assert "attacks" not in summary  # only one swing landed -> flat summary


class TestNoEnhancer:
    async def test_no_enhancer_resolves_single_attack_no_expansion(self):
        # AC3: exactly one base action, no phantom "attacks"/"riders" expansion.
        cs = _player_attacking(enhancers=[])
        enemy = cs.get_participant("goblin_scout_1")
        assert enemy is not None
        summary = await _resolve(cs, _attack(), _fixed_resolver(5))
        assert summary["resolved"] is True
        assert "attacks" not in summary
        assert "riders" not in summary
        assert summary["damage"] == 5
        assert enemy.hp_current == 25


class TestNarratedRiders:
    async def test_cunning_action_attaches_chosen_rider_without_extra_attack(self):
        # AC2: the Attack resolution also includes the chosen dash/disengage/hide rider,
        # and the rider is narration-only — it adds no mechanical second attack.
        cs = _player_attacking(enhancers=["cunning_action"])
        summary = await _resolve(cs, _attack(rider="hide"), _fixed_resolver(5))
        assert summary["riders"] == ["cunning_action:hide"]
        assert "attacks" not in summary

    async def test_quick_change_rider_surfaces_on_a_social_interact(self):
        # Quick Change rides a social declaration; INTERACT has no mechanical resolution
        # yet, but the rider still surfaces for the DM to voice.
        cs = _player_attacking(enhancers=["quick_change"])
        decl = Declaration(type=DeclarationType.INTERACT, action="charm the guard")
        summary = await _resolve(cs, decl, _fixed_resolver(5))
        assert summary["resolved"] is False
        assert summary["riders"] == ["quick_change:identity_swap"]


# --- Capstone: each of the 6 enhancers expands its declaration through resolve_phase (AC4) ---


def _capstone_state(enhancers: list[str], declaration: dict) -> CombatState:
    """A RESOLUTION-beat state: player_1 (with the given enhancers + a Longsword) declares
    `declaration` against a high-HP goblin that takes no declaration, so the phase never ends
    (combat continues -> resolve_phase returns JSON, not an end handoff)."""
    player = CombatParticipant(
        id="player_1",
        name="Kael",
        type="player",
        initiative=20,
        hp_current=30,
        hp_max=30,
        ac=14,
        action_pool=[dict(_WEAPON)],
        enhancers=enhancers,
    )
    goblin = CombatParticipant(
        id="goblin_1",
        name="Goblin",
        type="enemy",
        initiative=10,
        hp_current=50,
        hp_max=50,
        ac=13,
        action_pool=[{"name": "Scimitar", "damage": "1d6", "damage_type": "slashing"}],
        xp_value=50,
    )
    return CombatState(
        combat_id="combat_caps_s004",
        participants=[player, goblin],
        initiative_order=["player_1", "goblin_1"],
        beat="resolution",
        pending_declarations={"player_1": declaration},
    )


_ATTACK_DECL = {"type": "attack", "action": "Longsword", "target_id": "goblin_1"}
_INTERACT_DECL = {"type": "interact", "action": "charm the guard"}

# (enhancer, raw declaration, predicate over the player's resolved packet)
_CAPSTONE_CASES = [
    ("extra_attack", _ATTACK_DECL, lambda p: len(p.get("attacks", [])) == 2),
    ("shield_bash", _ATTACK_DECL, lambda p: p.get("attacks", [{}])[-1].get("action") == "Shield Bash"),
    ("cunning_action", {**_ATTACK_DECL, "rider": "hide"}, lambda p: "cunning_action:hide" in p.get("riders", [])),
    ("hit_and_run", _ATTACK_DECL, lambda p: "hit_and_run:reposition_15ft" in p.get("riders", [])),
    ("command_lesser", _ATTACK_DECL, lambda p: "command_lesser:directs_lesser_hollow" in p.get("riders", [])),
    ("quick_change", _INTERACT_DECL, lambda p: "quick_change:identity_swap" in p.get("riders", [])),
]


@pytest.mark.parametrize("enhancer,declaration,expanded", _CAPSTONE_CASES, ids=[c[0] for c in _CAPSTONE_CASES])
async def test_resolve_phase_expands_each_enhancer(enhancer, declaration, expanded):
    ctx = make_context()
    ctx.userdata.combat_state = _capstone_state([enhancer], declaration)

    raw = await combat_turn._resolve_phase_impl(
        ctx,
        mutations=_mutations(),
        queries=_queries(),
        resolver=_fixed_resolver(3),
        concentration_break_mod=_break_mod(),
        db_mod=_fake_db_mod(),
    )

    assert isinstance(raw, str)  # enemy survives -> phase loops, returns JSON (not an end handoff)
    result = json.loads(raw)
    packet = next(p for p in result["packets"] if p["actor_id"] == "player_1")
    assert expanded(packet), f"{enhancer} did not expand its declaration: {packet}"
