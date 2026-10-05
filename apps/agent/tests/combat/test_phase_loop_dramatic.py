from unittest.mock import MagicMock

import pytest
from combat._helpers import _resolution_state, _resolve_deps, _resolve_round
from sample_fixtures import make_context
from voice_condition_fixtures import place_actors

from check_resolution_attack import AttackResult
from session_data import CombatParticipant


class TestResolvePhaseDramatic:
    """Use an intrinsically undramatic resolver so only phase-context promotion explains the emitted dramatic verdict."""

    @pytest.mark.asyncio
    async def test_opening_strike_is_dramatic_and_flips_the_flag(self):
        deps = _resolve_deps(damage=3)
        ctx = make_context()
        ctx.userdata.combat_state = _resolution_state(player_hp=25, enemy_hp=7)
        assert ctx.userdata.combat_state.first_attack_resolved is False

        result = await _resolve_round(ctx, **deps)

        player_packet = next(p for p in result["packets"] if p["actor_id"] == "player_1")
        assert player_packet["dramatic"] is True
        assert player_packet["context"] == "first_attack"
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
        place_actors(cs)
        cs.initiative_order = ["player_1", "goblin_scout_1", "goblin_scout_2"]
        player = cs.get_participant("player_1")
        assert player is not None
        player.enhancers = ["extra_attack"]  # two swings from one ATTACK declaration
        cs.pending_declarations = {
            "player_1": {"type": "attack", "action": "Longsword", "target_id": "goblin_scout_1"},
        }

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
