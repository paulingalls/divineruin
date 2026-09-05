"""resolve_phase's dramatic-dice surface: the encounter-context promotions the phase loop supplies.

Split out of test_phase_loop.py (M29 story-016) for the 500-line cap. The band split moved two of
these signals between bands — `first_attack_resolved` and `enemies_remaining` are read fresh per
packet, and the ally band now resolves first — which test_beat3_hold.TestBandOrdering pins.
"""

from unittest.mock import MagicMock

import pytest
from combat._helpers import _resolution_state, _resolve_deps, _resolve_round
from sample_fixtures import make_context

from check_resolution_attack import AttackResult
from session_data import CombatParticipant


class TestResolvePhaseDramatic:
    """story-004: the phase loop surfaces the M4.5 dramatic verdict on each packet summary,
    layering the encounter-context signals (first_attack, last_enemy) the per-attack resolver
    can't see. _damage_resolver returns a non-dramatic intrinsic verdict, so a dramatic packet
    here is purely the emission-site promotion."""

    @pytest.mark.asyncio
    async def test_opening_strike_is_dramatic_and_flips_the_flag(self):
        deps = _resolve_deps(damage=3)
        ctx = make_context()
        ctx.userdata.combat_state = _resolution_state(player_hp=25, enemy_hp=7)
        assert ctx.userdata.combat_state.first_attack_resolved is False

        result = await _resolve_round(ctx, **deps)

        # The player's opening strike (first attack of the combat) earns the dice; first_attack
        # outranks last_enemy in the catalog, so that's the surfaced label.
        player_packet = next(p for p in result["packets"] if p["actor_id"] == "player_1")
        assert player_packet["dramatic"] is True
        assert player_packet["context"] == "first_attack"
        # The combat-scoped flag flipped, so a later attack no longer earns the first-attack dice.
        assert ctx.userdata.combat_state.first_attack_resolved is True

    @pytest.mark.asyncio
    async def test_every_packet_summary_carries_the_dramatic_keys(self):
        deps = _resolve_deps(damage=3)
        ctx = make_context()
        ctx.userdata.combat_state = _resolution_state(player_hp=25, enemy_hp=7)

        result = await _resolve_round(ctx, **deps)

        for p in result["packets"]:
            assert "dramatic" in p and isinstance(p["dramatic"], bool)
            assert "context" in p

    @pytest.mark.asyncio
    async def test_multi_swing_later_kill_reports_the_dramatic_swings_context(self):
        # Regression: an extra_attack expands to two swings; the FIRST is routine
        # (not dramatic) and the SECOND lands the killing blow (intrinsic dramatic,
        # context="killing_blow"). The aggregated summary must report dramatic=True
        # AND the killing swing's context — not the first swing's "" — or the DM
        # narrates a dramatic moment with no reason label (code-review finding 1).
        cs = _resolution_state(player_hp=25, enemy_hp=8)
        # Two enemies standing so neither swing earns the last_enemy promotion, and a
        # prior attack already resolved so neither earns first_attack — the only
        # dramatic source is the second swing's intrinsic killing blow.
        cs.first_attack_resolved = True
        cs.participants.append(
            CombatParticipant(
                id="goblin_scout_2",
                name="Goblin Scout",
                type="enemy",
                initiative=10,
                hp_current=8,
                hp_max=8,
                ac=13,
                action_pool=[{"name": "Scimitar", "damage": "1d6", "damage_type": "slashing", "properties": ["light"]}],
                xp_value=50,
            )
        )
        cs.initiative_order = ["player_1", "goblin_scout_1", "goblin_scout_2"]
        player = cs.get_participant("player_1")
        assert player is not None
        player.enhancers = ["extra_attack"]  # two swings from one ATTACK declaration
        cs.pending_declarations = {
            "player_1": {"type": "attack", "action": "Longsword", "target_id": "goblin_scout_1"},
        }

        # Stateful resolver: first swing deals 5 (8 -> 3, survives, routine); second swing
        # deals 5 again (3 -> 0, the intrinsic killing blow fires dramatic="killing_blow").
        swings = iter(
            [
                AttackResult(
                    hit=True,
                    roll=12,
                    attack_modifier=3,
                    attack_total=15,
                    target_ac=13,
                    damage=5,
                    damage_type="slashing",
                    critical_success=False,
                    critical_failure=False,
                    target_hp_remaining=3,
                    target_killed=False,
                    narrative_hint="A solid hit.",
                ),
                AttackResult(
                    hit=True,
                    roll=14,
                    attack_modifier=3,
                    attack_total=17,
                    target_ac=13,
                    damage=5,
                    damage_type="slashing",
                    critical_success=False,
                    critical_failure=False,
                    target_hp_remaining=0,
                    target_killed=True,
                    narrative_hint="The finishing blow.",
                    dramatic=True,
                    context="killing_blow",
                ),
            ]
        )
        resolver = MagicMock()
        resolver.resolve_attack = MagicMock(side_effect=lambda *a, **k: next(swings))

        deps = _resolve_deps()
        deps["resolver"] = resolver
        ctx = make_context()
        ctx.userdata.combat_state = cs

        result = await _resolve_round(ctx, **deps)

        player_packet = next(p for p in result["packets"] if p["actor_id"] == "player_1")
        assert len(player_packet["attacks"]) == 2
        assert player_packet["dramatic"] is True
        assert player_packet["context"] == "killing_blow"
