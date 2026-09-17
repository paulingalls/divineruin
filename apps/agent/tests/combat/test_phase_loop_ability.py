"""resolve_phase's ABILITY paths: initiative ordering, per-member Resonance, and the Focus gate.

Split out of test_phase_loop.py (M29 story-016), which took the Beat-3 hold sweep and the
500-line cap in the same change. Same DI bundle, same live phase loop — only the file boundary
moved.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from combat._helpers import _resolution_state, _resolve_deps, _resolve_round
from combat.test_phase_loop import _resonance_deps
from livekit.agents.llm import ToolError
from sample_fixtures import make_context


class TestResolvePhaseAbility:
    """story-007: an in-combat ABILITY declaration resolves via the shared cast resolver and appears
    as a resolved packet in initiative order alongside attacks. The cast itself is mocked here — the
    wiring/ordering is under test, not the spell internals (covered by test_spell_casting)."""

    def _ability_state(self):
        state = _resolution_state()
        # Player declares an ABILITY instead of an attack; the enemy still swings.
        state.pending_declarations["player_1"] = {"type": "ability", "action": "arcane_bolt"}
        return state

    def _cast_resolver(self, result):
        mod = MagicMock()
        mod._resolve_cast = AsyncMock(return_value=result)
        return mod

    @pytest.mark.asyncio
    async def test_player_ability_resolves_in_initiative_order(self):
        from spell_casting import _UNCHANGED, CastResult

        ctx = make_context()
        ctx.userdata.combat_state = self._ability_state()
        result = CastResult(
            packet={"effect": "A bolt of force.", "state": "flickering", "resonance_generated": 6},
            new_resonance=6,
            concentration_spell_id=_UNCHANGED,
            generated=6,
            events=[],
        )
        cast_resolver = self._cast_resolver(result)
        deps = _resolve_deps()
        res = _resonance_deps()  # the ability generates resonance -> the WRAP write path is exercised

        packets = (await _resolve_round(ctx, cast_resolver=cast_resolver, **deps, **res))["packets"]

        # Player (initiative 15) resolves before the enemy (initiative 12).
        assert packets[0]["actor_id"] == "player_1"
        assert packets[0]["resolved"] is True
        assert packets[0]["declaration_type"] == "ability"
        assert packets[0]["cast"]["effect"] == "A bolt of force."
        # The enemy's attack still resolves the same phase.
        assert packets[1]["actor_id"] == "goblin_scout_1"
        cast_resolver._resolve_cast.assert_awaited_once()


class TestResolvePhaseAbilityResonance:
    """story-007: an in-combat ability GENERATES resonance during resolution (beat 2); the WRAP
    decay (beat 4) then sheds from the post-generation total, so the phase nets
    standing + generated - 1. The generated value is persisted by the cast inside the tx (mocked
    here); the loop seeds the WRAP base with it and syncs/pushes once post-commit."""

    def _ability_state(self):
        state = _resolution_state()  # enemy hp 7 -> combat continues this phase
        state.pending_declarations["player_1"] = {"type": "ability", "action": "arcane_bolt"}
        return state

    def _cast_resolver(self, *, new_resonance, generated=5, concentration=None, events=None):
        from spell_casting import _UNCHANGED, CastResult

        result = CastResult(
            packet={"effect": "A bolt of force.", "state": "flickering"},
            new_resonance=new_resonance,
            concentration_spell_id=concentration if concentration is not None else _UNCHANGED,
            generated=generated,
            events=events or [],
        )
        mod = MagicMock()
        mod._resolve_cast = AsyncMock(return_value=result)
        return mod

    @pytest.mark.asyncio
    async def test_generation_then_wrap_decay_nets_correctly(self):
        ctx = make_context()
        ctx.userdata.resonance.current = 3  # standing
        ctx.userdata.combat_state = self._ability_state()
        # The cast wrote standing(3)+generated(5)=8 inside the tx (mocked as new_resonance=8).
        cast_resolver = self._cast_resolver(new_resonance=8)
        deps = _resolve_deps(damage=3)
        res = _resonance_deps()

        raw = await _resolve_round(ctx, cast_resolver=cast_resolver, **deps, **res)

        assert not isinstance(raw, tuple)
        # WRAP decays the post-generation total by 1: 8 -> 7 (NOT standing 3 -> 2).
        assert ctx.userdata.resonance.current == 7
        write = res["resonance_mutations"].update_player_resonance.await_args
        assert write.args == ("player_1", 7)
        # ONE push per commit in which the member's Resonance actually moved. The round now has
        # two commits and the value genuinely moves in both — the ally commit banks the cast's
        # generation (3 -> 8), the wrap commit sheds the phase decay (8 -> 7) — so the client sees
        # both real transitions rather than only the net. The ability still suppresses its own
        # RESONANCE_CHANGED, so these remain the only authoritative pushes.
        assert res["resonance_events_mod"].publish_resonance_changed.await_count == 2

    @pytest.mark.asyncio
    async def test_killing_phase_ability_resonance_pushes_hud(self):
        """Regression (story-007 finding 2): an ability that GENERATES resonance on the same phase
        that ends combat must still push the qualitative Resonance HUD state. The sync + push run
        BEFORE the end-of-combat handoff return, so the client never keeps a stale state."""
        ctx = make_context()
        ctx.userdata.resonance.current = 3
        # Enemy already fallen -> the wrap reports victory THIS phase (combat ends).
        state = _resolution_state()
        enemy = state.get_participant("goblin_scout_1")
        assert enemy is not None
        enemy.is_fallen = True
        enemy.hp_current = 0
        state.pending_declarations = {"player_1": {"type": "ability", "action": "arcane_bolt"}}
        ctx.userdata.combat_state = state
        cast_resolver = self._cast_resolver(new_resonance=8)
        deps = _resolve_deps(damage=3)
        res = _resonance_deps()

        raw = await _resolve_round(ctx, cast_resolver=cast_resolver, **deps, **res)

        assert isinstance(raw, tuple)  # combat ended -> handoff
        assert json.loads(raw[1])["outcome"] == "victory"
        # The generated resonance was synced AND its HUD push fired even though combat ended.
        assert ctx.userdata.resonance.current == 8
        res["resonance_events_mod"].publish_resonance_changed.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cantrip_ability_adds_nothing_but_phase_still_decays(self):
        ctx = make_context()
        ctx.userdata.resonance.current = 3
        ctx.userdata.combat_state = self._ability_state()
        # A cantrip generates 0 -> the cast wrote no resonance (new_resonance None).
        cast_resolver = self._cast_resolver(new_resonance=None, generated=0)
        deps = _resolve_deps(damage=3)
        res = _resonance_deps()

        await _resolve_round(ctx, cast_resolver=cast_resolver, **deps, **res)

        # No generation to seed the base, so the phase decays the standing value: 3 -> 2.
        assert ctx.userdata.resonance.current == 2
        write = res["resonance_mutations"].update_player_resonance.await_args
        assert write.args == ("player_1", 2)

    @pytest.mark.asyncio
    async def test_concentration_change_synced_post_commit(self):
        ctx = make_context()
        ctx.userdata.concentration.spell_id = None
        ctx.userdata.combat_state = self._ability_state()
        cast_resolver = self._cast_resolver(new_resonance=4, concentration="hold_flame")
        deps = _resolve_deps(damage=3)
        res = _resonance_deps()

        await _resolve_round(ctx, cast_resolver=cast_resolver, **deps, **res)

        # The cast persisted concentration via conn; the loop syncs the in-memory SSOT IN-LOOP
        # (so a same-phase, lower-initiative concentration break sees the just-cast spell).
        assert ctx.userdata.concentration.spell_id == "hold_flame"

    @pytest.mark.asyncio
    async def test_inphase_concentration_break_sees_just_cast_spell(self):
        """Regression (story-007 finding 1): a player concentrating on spell A casts a concentration
        ABILITY for spell B at HIGHER initiative; a lower-initiative enemy hits the player the SAME
        phase. break_concentration_on_damage runs in-loop and MUST read the just-cast spell B (not the
        stale A), or it would save against the wrong spell and clear B from the DB while the session
        forced memory back to B — a silent divergence. The in-loop concentration sync fixes this."""
        ctx = make_context()
        ctx.userdata.concentration.spell_id = "spell_a"  # the prior concentration the cast replaces
        ctx.userdata.combat_state = self._ability_state()
        cast_resolver = self._cast_resolver(new_resonance=4, concentration="spell_b")

        # Spy break: record what concentration spell it observes when the lower-initiative enemy hits.
        seen: list[str | None] = []

        async def _spy_break(session, damage, incapacitated, *, damaged_player_id, combat_state=None, conn=None):
            seen.append(session.concentration.spell_id)
            return None

        deps = _resolve_deps(damage=3)
        deps["concentration_break_mod"].break_concentration_on_damage = AsyncMock(side_effect=_spy_break)
        res = _resonance_deps()

        await _resolve_round(ctx, cast_resolver=cast_resolver, **deps, **res)

        # The break (enemy attack, initiative 12) ran AFTER the ability cast (initiative 15) and saw
        # the just-cast spell B in memory — not the stale spell A.
        assert seen == ["spell_b"]

    @pytest.mark.asyncio
    async def test_cast_deferred_events_flushed_post_commit(self):
        emitted: list[str] = []

        async def _echo():
            emitted.append("hollow_echo")

        ctx = make_context()
        ctx.userdata.resonance.current = 0
        ctx.userdata.combat_state = self._ability_state()
        cast_resolver = self._cast_resolver(new_resonance=4, events=[lambda: _echo()])
        deps = _resolve_deps(damage=3)
        res = _resonance_deps()

        await _resolve_round(ctx, cast_resolver=cast_resolver, **deps, **res)

        # The cast's own deferred client events (hollow echo, Vaelti warning) fire after commit.
        assert emitted == ["hollow_echo"]


class TestResolvePhaseAbilityFocusGate:
    """story-007 AC2: an in-combat ability with insufficient Focus fails loud (ToolError) with NO
    state writes, validated BEFORE the resolution loop so no other actor's HP write is rolled back."""

    def _ability_state(self):
        state = _resolution_state()
        state.pending_declarations["player_1"] = {"type": "ability", "action": "arcane_shield_spell"}
        return state

    @pytest.mark.asyncio
    async def test_insufficient_focus_raises_before_any_write(self):
        ctx = make_context()
        ctx.userdata.combat_state = self._ability_state()
        deps = _resolve_deps(damage=3)
        # The player can't afford the ability; the pre-validation runs the real cast gate and raises.
        deps["queries"].get_player = AsyncMock(return_value={"player_id": "player_1", "focus": {"current": 0}})
        res = _resonance_deps()
        cast_resolver = MagicMock()
        cast_resolver._gate_spell = MagicMock(side_effect=ToolError("Not enough Focus for Arcane Shield"))
        cast_resolver._resolve_cast = AsyncMock()

        with pytest.raises(ToolError, match="Focus"):
            await _resolve_round(ctx, cast_resolver=cast_resolver, **deps, **res)

        # AC2: nothing was written and the loop never ran — the ability is rejected pre-loop.
        cast_resolver._resolve_cast.assert_not_called()
        deps["mutations"].update_player_hp.assert_not_called()
        deps["mutations"].save_combat_state.assert_awaited_once()
        recovered = deps["mutations"].save_combat_state.await_args.args[1]
        assert recovered["beat"] == "declaration"
        assert recovered["pending_declarations"] == {}
        res["resonance_mutations"].update_player_resonance.assert_not_called()

    @pytest.mark.asyncio
    async def test_player_row_is_passed_through_to_the_cast(self):
        # The pre-validation fetches the player for_update ONCE and threads it to the cast, so the
        # cast does not re-fetch (single lock). The mock cast records the player it was handed.
        from spell_casting import _UNCHANGED, CastResult

        ctx = make_context()
        ctx.userdata.combat_state = self._ability_state()
        deps = _resolve_deps(damage=3)
        player_row = {"player_id": "player_1", "focus": {"current": 9}}
        deps["queries"].get_player = AsyncMock(return_value=player_row)
        res = _resonance_deps()
        cast_resolver = MagicMock()
        cast_resolver._gate_spell = MagicMock()  # affordable -> no raise
        cast_resolver._resolve_cast = AsyncMock(
            return_value=CastResult(
                packet={"effect": "ward"}, new_resonance=None, concentration_spell_id=_UNCHANGED, generated=0, events=[]
            )
        )

        await _resolve_round(ctx, cast_resolver=cast_resolver, **deps, **res)

        _args, kwargs = cast_resolver._resolve_cast.call_args
        assert kwargs["player"] is player_row
