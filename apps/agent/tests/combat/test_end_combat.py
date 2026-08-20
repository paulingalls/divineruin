"""Tests for end_combat: state clearing, agent handoff, XP calc by outcome, events, errors."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from _combat_end_fixtures import combat_end_mutations, combat_end_queries
from combat._helpers import (
    _damage_resolver,
    _fake_db_mod,
    _make_combat_state,
    _resolution_state,
)
from livekit.agents.llm import ToolError
from sample_fixtures import make_context, make_mock_room, published_payloads

import event_types as E
from combat_end import _end_combat_impl
from combat_events import EventSink


def _make_end_combat_mocks():
    """Create mock modules for end_combat DI params."""
    return combat_end_mutations()


class TestEndCombat:
    @pytest.mark.asyncio
    async def test_clears_state(self):
        mock_mutations = _make_end_combat_mocks()
        ctx = make_context()
        ctx.userdata.combat_state = _make_combat_state()

        raw = await _end_combat_impl(ctx, outcome="victory", mutations=mock_mutations, db_mod=_fake_db_mod())
        assert isinstance(raw, tuple), "end_combat success should return (DungeonMasterAgent, json_str)"
        _, json_str = raw
        result = json.loads(json_str)

        assert result["outcome"] == "victory"
        assert ctx.userdata.in_combat is False
        assert ctx.userdata.combat_state is None
        mock_mutations.delete_combat_state.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_city_agent(self):
        from exploration_agent import ExplorationAgent

        mock_mutations = _make_end_combat_mocks()
        ctx = make_context()
        ctx.userdata.combat_state = _make_combat_state()

        raw = await _end_combat_impl(ctx, outcome="victory", mutations=mock_mutations, db_mod=_fake_db_mod())
        agent_instance, _ = raw
        assert isinstance(agent_instance, ExplorationAgent)
        assert agent_instance._agent_type == "city"

    @pytest.mark.asyncio
    async def test_returned_agent_has_combat_summary_context(self):
        mock_mutations = _make_end_combat_mocks()
        ctx = make_context()
        ctx.userdata.combat_state = _make_combat_state()

        raw = await _end_combat_impl(ctx, outcome="victory", mutations=mock_mutations, db_mod=_fake_db_mod())
        assert isinstance(raw, tuple)
        agent_instance, _ = raw
        # The returned agent should have a chat_ctx with a combat summary
        items = list(agent_instance.chat_ctx.items)
        assert len(items) > 0

    @pytest.mark.asyncio
    async def test_calculates_xp_on_victory(self):
        mock_mutations = _make_end_combat_mocks()
        ctx = make_context()
        ctx.userdata.combat_state = _make_combat_state()

        _, json_str = await _end_combat_impl(ctx, outcome="victory", mutations=mock_mutations, db_mod=_fake_db_mod())
        result = json.loads(json_str)

        assert result["xp_total"] == 50
        assert "Goblin Scout" in result["defeated_enemies"]

    @pytest.mark.asyncio
    async def test_no_xp_on_defeat(self, monkeypatch):
        import db_queries
        import resurrection

        # This test asserts XP only, not the resurrection flow. Give the primary a valid row and
        # stub resurrect_on_defeat (M18 story-003 made a MISSING row on defeat fail-loud, so a None
        # here would now correctly raise — that path is covered in test_combat_end_party_wipe).
        monkeypatch.setattr(db_queries, "get_player", AsyncMock(return_value={"player_id": "player_1"}))
        monkeypatch.setattr(
            resurrection, "resurrect_on_defeat", AsyncMock(return_value={"anchor": "accord_guild_hall"})
        )
        mock_mutations = _make_end_combat_mocks()
        ctx = make_context()
        ctx.userdata.combat_state = _make_combat_state()

        _, json_str = await _end_combat_impl(ctx, outcome="defeat", mutations=mock_mutations, db_mod=_fake_db_mod())
        result = json.loads(json_str)

        assert result["xp_total"] == 0
        assert result["defeated_enemies"] == []

    @pytest.mark.asyncio
    async def test_no_xp_on_fled(self):
        mock_mutations = _make_end_combat_mocks()
        ctx = make_context()
        ctx.userdata.combat_state = _make_combat_state()

        _, json_str = await _end_combat_impl(ctx, outcome="fled", mutations=mock_mutations, db_mod=_fake_db_mod())
        result = json.loads(json_str)

        assert result["xp_total"] == 0

    @pytest.mark.asyncio
    async def test_publishes_events(self):
        mock_mutations = _make_end_combat_mocks()
        room = make_mock_room()
        ctx = make_context(room=room)
        ctx.userdata.combat_state = _make_combat_state()

        await _end_combat_impl(ctx, outcome="victory", mutations=mock_mutations, db_mod=_fake_db_mod())

        calls = published_payloads(room)
        types = [c["type"] for c in calls]
        assert E.COMBAT_ENDED in types
        assert E.PLAY_SOUND in types

    @pytest.mark.asyncio
    async def test_error_if_not_in_combat(self):
        ctx = make_context()

        with pytest.raises(ToolError, match="Not in combat"):
            await _end_combat_impl(ctx, outcome="victory")

    @pytest.mark.asyncio
    async def test_error_invalid_outcome(self):
        mock_mutations = _make_end_combat_mocks()
        ctx = make_context()
        ctx.userdata.combat_state = _make_combat_state()

        with pytest.raises(ToolError, match="Invalid outcome"):
            await _end_combat_impl(ctx, outcome="surrender", mutations=mock_mutations, db_mod=_fake_db_mod())


class TestPhaseLoopExit:
    """Combat now exits through the phase engine's wrap end-condition (story-003):
    resolve_phase fires end_combat when the engine reports victory/defeat, rather than
    the LLM choosing to call end_combat itself. These pin that exit handoff."""

    @pytest.mark.asyncio
    async def test_victory_wrap_hands_back_to_exploration_agent(self):
        from combat_turn import _resolve_phase_impl
        from exploration_agent import ExplorationAgent

        # enemy_hp=3 is one fixed-damage hit from victory; _damage_resolver(3) lands it.
        resolver = _damage_resolver(3)
        queries = combat_end_queries()
        break_mod = MagicMock()
        break_mod.break_concentration_on_damage = AsyncMock(return_value=None)

        ctx = make_context()
        ctx.userdata.combat_state = _resolution_state(player_hp=25, enemy_hp=3)

        raw = await _resolve_phase_impl(
            ctx,
            mutations=_make_end_combat_mocks(),
            queries=queries,
            resolver=resolver,
            concentration_break_mod=break_mod,
            db_mod=_fake_db_mod(),
        )

        assert isinstance(raw, tuple), "a winning wrap should return the (ExplorationAgent, json) handoff"
        agent_instance, json_str = raw
        assert isinstance(agent_instance, ExplorationAgent)
        assert json.loads(json_str)["outcome"] == "victory"
        assert ctx.userdata.combat_state is None


class TestEndCombatVeilWard:
    """The encounter ward dies with the combat row — say so, resolved (M24 story-008, AC3).

    scope_model.md §3: "on combat end the encounter ward dies, but if a location ward still covers
    the party, VEIL_WARD_CHANGED carries active: true." Nothing published here before this story, so
    a party fighting on a Sacred site watched its indicator keep whatever state the raise left it.

    The ordering trap: this producer runs INSIDE the end transaction, and session.combat_state is
    not cleared until _end_combat_finish, which is post-commit. A naive resolve_scope_ward here would
    still see the dying encounter ward. So the producer reads the LOCATION scope explicitly, exactly
    as the dismiss path does.
    """

    _SACRED = {"source": "sacred_site", "expires_at": None, "dismissible": False}

    def _warded_ctx(self, ward=None):
        ctx = make_context(room=make_mock_room())
        ctx.userdata.combat_state = _make_combat_state()
        ctx.userdata.combat_state.veil_ward = ward or {"source": "cleric", "rounds_remaining": None}
        return ctx

    def _ward_events(self, room):
        return [p for p in published_payloads(room) if p["type"] == E.VEIL_WARD_CHANGED]

    @pytest.mark.asyncio
    async def test_encounter_ward_death_darkens_the_hud_when_nothing_else_covers(self):
        ctx = self._warded_ctx()
        await _end_combat_impl(ctx, outcome="victory", mutations=_make_end_combat_mocks(), db_mod=_fake_db_mod())
        assert self._ward_events(ctx.userdata.room) == [
            {
                "type": E.VEIL_WARD_CHANGED,
                "active": False,
                "scope_kind": None,
                "scope_id": None,
                "source": None,
            }
        ]

    @pytest.mark.asyncio
    async def test_surviving_location_ward_keeps_the_hud_lit(self, monkeypatch):
        # §3's whole point: the fight's ward dies, the Sacred site does not, and the party's casts
        # are STILL halved. Publishing active=False here would darken the light while it lies.
        import db_mutations_veil_ward

        monkeypatch.setattr(db_mutations_veil_ward, "read_active_ward", AsyncMock(return_value=self._SACRED))
        ctx = self._warded_ctx()
        await _end_combat_impl(ctx, outcome="victory", mutations=_make_end_combat_mocks(), db_mod=_fake_db_mod())
        [event] = self._ward_events(ctx.userdata.room)
        assert event["active"] is True
        assert event["scope_kind"] == "location"
        assert event["source"] == "sacred_site"

    @pytest.mark.asyncio
    async def test_unwarded_fight_publishes_no_ward_event(self):
        # Ending an unwarded fight changes nothing about wardedness. Say nothing.
        ctx = make_context(room=make_mock_room())
        ctx.userdata.combat_state = _make_combat_state()
        await _end_combat_impl(ctx, outcome="victory", mutations=_make_end_combat_mocks(), db_mod=_fake_db_mod())
        assert self._ward_events(ctx.userdata.room) == []


class TestEndCombatPaysOnce:
    """M28 story-010: the combat-end rewards are a Resolve now — permanent progression written
    inside the end transaction. So the guard that stops a SECOND end (session.combat_state) has to
    be released with the commit that made the payout durable, not after the post-commit publishes.

    Before this story combat_state survived until _end_combat_finish, which ran after sink.flush().
    A flush failure left the guard armed with the party already paid, and the DM's next
    end_combat("victory") re-ran _end_combat_db against the same participants — a second full
    party-wide XP/loot/coin grant. The absent second payout is the criterion here; the "Not in
    combat" ToolError is only the mechanism that produces it."""

    class _ExplodingSink(EventSink):
        """An EventSink whose post-commit flush raises — the failure window this story closes."""

        async def flush(self) -> None:
            raise RuntimeError("flush boom")

    def _ctx_with_a_swung_weapon(self):
        ctx = make_context(room=make_mock_room())
        ctx.userdata.combat_state = _make_combat_state()
        for member in ctx.userdata.party.members:
            member.weapon_used = True
            member.weapon_crit_vs_heavy = True
        return ctx

    @pytest.mark.asyncio
    async def test_second_end_after_a_failed_flush_grants_nothing(self, monkeypatch):
        import combat_end

        monkeypatch.setattr(combat_end, "EventSink", self._ExplodingSink)
        mutations = _make_end_combat_mocks()
        ctx = self._ctx_with_a_swung_weapon()

        await _end_combat_impl(
            ctx, outcome="victory", mutations=mutations, queries=combat_end_queries(), db_mod=_fake_db_mod()
        )
        paid_once = mutations.update_player_xp.await_count
        assert paid_once > 0, "the first end must actually pay, else this test proves nothing"

        with pytest.raises(ToolError, match="Not in combat"):
            await _end_combat_impl(
                ctx, outcome="victory", mutations=mutations, queries=combat_end_queries(), db_mod=_fake_db_mod()
            )

        assert mutations.update_player_xp.await_count == paid_once, "the party was paid a second time"
        assert mutations.delete_combat_state.await_count == 1

    @pytest.mark.asyncio
    async def test_failed_flush_still_completes_teardown_and_hands_off(self, monkeypatch):
        # Half 2: end_combat is the ONLY exit from CombatAgent. A HUD mirror that fails to update
        # must not strand a session whose rewards are already banked.
        import combat_end

        monkeypatch.setattr(combat_end, "EventSink", self._ExplodingSink)
        ctx = self._ctx_with_a_swung_weapon()

        raw = await _end_combat_impl(
            ctx,
            outcome="victory",
            mutations=_make_end_combat_mocks(),
            queries=combat_end_queries(),
            db_mod=_fake_db_mod(),
        )

        assert isinstance(raw, tuple), "a failed publish must still return the (agent, json) handoff"
        assert json.loads(raw[1])["outcome"] == "victory"
        assert ctx.userdata.combat_state is None
        assert all(not m.weapon_used and not m.weapon_crit_vs_heavy for m in ctx.userdata.party.members)
