"""_handle_hp_zero and the ABILITY packet path.

Split out of test_resolve_packet.py (M29 story-016) for the 500-line cap: that file grew the
roll/apply split, and these two classes exercise paths the split does not touch.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from sample_fixtures import make_context

import conditions
from combat_support import _handle_hp_zero
from session_data import CombatParticipant, CompanionState
from tool_support import SOUND_HOLLOW_RISE, SOUND_PLAYER_FALLEN


def _hollowed(stage: int) -> list[dict]:
    conds: list[dict] = []
    for _ in range(stage):
        conds = conditions.apply_condition(conds, "hollowed")
    return conds


class TestResolveAbilityPacket:
    """story-007: an in-combat ABILITY declaration resolves through the shared cast logic.

    Player-gated (only the player has a Focus pool + resonance track); the CastResult is stashed on
    the AbilityCastOutcome so the phase loop can commit resonance/concentration/events post-commit."""

    def _player(self) -> CombatParticipant:
        return CombatParticipant(
            id="player_1", name="Lyra", type="player", initiative=15, hp_current=20, hp_max=20, ac=14
        )

    def _cast_resolver(self, result):
        mod = MagicMock()
        mod._resolve_cast = AsyncMock(return_value=result)
        return mod

    async def test_player_ability_resolves_and_stashes_castresult(self):
        from combat_ability import AbilityCastOutcome, _resolve_ability_packet
        from declarations import Declaration, DeclarationType
        from spell_casting import _UNCHANGED, CastResult

        session = make_context().userdata
        attacker = self._player()
        decl = Declaration(type=DeclarationType.ABILITY, action="arcane_bolt")
        result = CastResult(
            packet={"effect": "zap", "state": "stable"},
            new_resonance=6,
            concentration_spell_id=_UNCHANGED,
            generated=6,
            events=[],
        )
        cast_resolver = self._cast_resolver(result)
        outcome = AbilityCastOutcome()

        summary = await _resolve_ability_packet(
            session,
            attacker,
            decl,
            state=None,
            cast_resolver=cast_resolver,
            conn=object(),
            player=None,
            cast_outcome=outcome,
        )

        assert summary["resolved"] is True
        assert summary["actor_id"] == "player_1"
        assert summary["declaration_type"] == "ability"
        assert summary["action"] == "arcane_bolt"
        assert summary["cast"] == {"effect": "zap", "state": "stable"}
        # the CastResult is handed to the loop keyed by the caster's id (in-memory sync is post-commit)
        assert outcome.results["player_1"] is result
        # routed through the shared cast core with the cast's own RESONANCE_CHANGED suppressed —
        # in combat the phase WRAP push is the single authoritative HUD update.
        _args, kwargs = cast_resolver._resolve_cast.call_args
        assert kwargs["suppress_resonance_changed"] is True

    async def test_non_player_ability_is_wasted(self):
        from combat_ability import AbilityCastOutcome, _resolve_ability_packet
        from declarations import Declaration, DeclarationType

        session = make_context().userdata
        enemy = CombatParticipant(
            id="goblin_1", name="Goblin", type="enemy", initiative=10, hp_current=7, hp_max=7, ac=13
        )
        decl = Declaration(type=DeclarationType.ABILITY, action="goblin_hex")
        cast_resolver = MagicMock()
        cast_resolver._resolve_cast = AsyncMock()
        outcome = AbilityCastOutcome()

        summary = await _resolve_ability_packet(
            session,
            enemy,
            decl,
            state=None,
            cast_resolver=cast_resolver,
            conn=object(),
            player=None,
            cast_outcome=outcome,
        )

        assert summary["resolved"] is False
        cast_resolver._resolve_cast.assert_not_called()
        assert outcome.results == {}

    async def test_missing_action_is_wasted(self):
        from combat_ability import AbilityCastOutcome, _resolve_ability_packet
        from declarations import Declaration, DeclarationType

        session = make_context().userdata
        attacker = self._player()
        decl = Declaration(type=DeclarationType.ABILITY, action=None)
        cast_resolver = MagicMock()
        cast_resolver._resolve_cast = AsyncMock()
        outcome = AbilityCastOutcome()

        summary = await _resolve_ability_packet(
            session,
            attacker,
            decl,
            state=None,
            cast_resolver=cast_resolver,
            conn=object(),
            player=None,
            cast_outcome=outcome,
        )

        assert summary["resolved"] is False
        cast_resolver._resolve_cast.assert_not_called()
        assert outcome.results == {}


class TestHandleHpZero:
    """story-007: _handle_hp_zero resolves a target dropped to 0 HP — the fall / instant-death /
    Stage-2+ Hollowed-rise / companion-KO branch extracted from _resolve_attack_packet. It mutates
    the target + sounds in place and returns (hp_status, rose_hollowed)."""

    def _target(
        self,
        *,
        id: str = "player_1",
        name: str = "Lyra",
        type: str = "player",
        hp_current: int = 0,
        hp_max: int = 20,
        is_fallen: bool = False,
        conditions: list[dict] | None = None,
    ) -> CombatParticipant:
        p = CombatParticipant(id=id, name=name, type=type, initiative=15, hp_current=hp_current, hp_max=hp_max, ac=14)
        p.is_fallen = is_fallen
        if conditions is not None:
            p.conditions = conditions
        return p

    def _attack(self, overkill: int):
        # _handle_hp_zero reads only attack_result.overkill.
        return SimpleNamespace(overkill=overkill)

    def test_player_at_zero_falls(self):
        session = make_context().userdata  # no companion
        target = self._target(hp_current=0, hp_max=20)
        sounds: list[str] = []
        hp_status, rose = _handle_hp_zero(
            session, target, self._attack(0), was_fallen=False, hp_status="defeated", sounds=sounds
        )
        assert target.is_fallen is True
        assert target.is_dead is False
        assert rose is False
        assert SOUND_PLAYER_FALLEN in sounds
        # non-rise path passes the caller's pre-computed hp_status straight through
        assert hp_status == "defeated"

    def test_instant_death_when_overkill_ge_hp_max(self):
        session = make_context().userdata
        target = self._target(hp_current=-25, hp_max=20)
        _handle_hp_zero(session, target, self._attack(25), was_fallen=False, hp_status="defeated", sounds=[])
        assert target.is_fallen is True
        assert target.is_dead is True

    def test_already_fallen_does_not_flag_dead(self):
        # The instant-death verdict is scoped to the live -> 0 transition; a hit on an already-downed
        # target (was_fallen=True) is the separate "damage while Fallen" mechanic, never instant death.
        session = make_context().userdata
        target = self._target(hp_current=-25, hp_max=20, is_fallen=True)
        _handle_hp_zero(session, target, self._attack(25), was_fallen=True, hp_status="defeated", sounds=[])
        assert target.is_dead is False

    def test_stage2_hollowed_rises_instead_of_falling(self):
        session = make_context().userdata
        target = self._target(hp_current=0, hp_max=20, conditions=_hollowed(2))
        sounds: list[str] = []
        hp_status, rose = _handle_hp_zero(
            session, target, self._attack(0), was_fallen=False, hp_status="defeated", sounds=sounds
        )
        assert target.type == "temporary_hollowed"
        assert target.hp_current == 10  # max(1, hp_max // 2)
        assert any(c["type"] == "temporary_hollowed" for c in target.conditions)
        assert target.is_fallen is False
        assert rose is True
        assert SOUND_HOLLOW_RISE in sounds
        # rise restores HP, so hp_status is recomputed (no longer the caller's "defeated" sentinel)
        assert hp_status != "defeated"

    def test_companion_ko_marks_unconscious_and_records_memory(self):
        session = make_context().userdata
        session.companion = CompanionState(id="companion_kael", name="Kael")
        session.companion.is_conscious = True
        target = self._target(id="companion_kael", name="Kael", type="companion", hp_current=0, hp_max=15)
        _handle_hp_zero(session, target, self._attack(0), was_fallen=False, hp_status="defeated", sounds=[])
        assert target.is_fallen is True
        assert session.companion.is_conscious is False
        assert any("knocked unconscious" in m for m in session.companion.session_memories)
