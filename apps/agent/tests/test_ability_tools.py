import copy
import json
import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from combat._helpers import _make_combat_state
from livekit.agents.llm import ToolError
from sample_fixtures import make_context, make_db_mod
from voice_condition_fixtures import place_actors

import abilities
import reaction_spend
import reaction_windows
import spells
from ability_tools import _request_ability_activation_impl
from combat_phase import PhaseBeat, advance_combat_phase


def _player(stamina: int = 10, focus: int = 10, class_: str = "paladin") -> dict:
    return {
        "player_id": "player_1",
        "name": "Kael",
        "class": class_,
        "level": 5,
        "stamina": {"current": stamina, "max": 10},
        "focus": {"current": focus, "max": 10},
    }


async def _call(
    ability_id: str,
    *,
    stamina: int = 10,
    focus: int = 10,
    player: dict | None = None,
    owns_elective: bool = False,
    context=None,
    persistence=None,
):
    """Invoke the impl with mock db/queries/persistence. Returns (parsed_result, persistence_mock).

    The own-the-base gate (story-006) requires the player to own the ability. These
    cases activate CORE/reaction abilities, owned via class==archetype — so the
    player's class is derived from the ability id's archetype prefix
    (warrior_*/cleric_*/paladin_*). owns_elective is stubbed (unused on the core path)
    and only consulted for elective abilities.
    """
    ctx = context or make_context()
    mock_db, _conn = make_db_mod()
    _conn.execute = AsyncMock()
    queries = MagicMock()
    default_player = _player(stamina, focus, class_=ability_id.split("_")[0])
    row = default_player if player is None else player
    if ctx.userdata.combat_state is not None and abilities.get_ability(ability_id).ability_type == "reaction":
        participant = ctx.userdata.combat_state.get_participant(ctx.userdata.player_id)
        assert participant is not None
        participant.reaction_ids = [ability_id]
        participant.has_reaction_ability = True
    queries.get_players_for_update = AsyncMock(return_value={row["player_id"]: row})
    if persistence is None:
        persistence = MagicMock()
        persistence.update_player_resources = AsyncMock()
    persistence.get_active_variant = AsyncMock(return_value=None)
    persistence.owns_elective = AsyncMock(return_value=owns_elective)
    # Bound unconditionally: only a reaction reads the binding, and branching on ability_type here
    # would reach into the private catalog dict to ask a question the tool already asks.
    with ctx.userdata._bind_authenticated_actor(ctx.userdata.player_id, 1, lambda *_args: None):
        raw = await _request_ability_activation_impl(
            ctx, ability_id, db_mod=mock_db, queries_mod=queries, persistence_mod=persistence
        )
    return json.loads(raw), persistence


def _reaction_context(*, hit=True, window_open=True, target_id="player_1"):
    """A phase PAUSED on a real Beat-3 window, which is the whole permission (story-017).

    No declaration is staged: a reaction is an interrupt now, so `pending_declarations` stays
    empty and the open window built by the real producer is what the gate reads.
    """
    ctx = make_context()
    state = place_actors(_make_combat_state(), target_id)
    state.beat = PhaseBeat.NARRATION
    if window_open:
        # A real pause always has the held action the window belongs to at the head of the queue
        # — preflight_spend binds the spend to its `seq`, and refuses loud if the two disagree.
        state.held_actions = [
            {
                "seq": 0,
                "actor_id": "goblin_scout_1",
                "initiative": 12,
                "declaration": {"type": "attack", "action": "Scimitar", "target_id": target_id},
                "roll": None,
                "opened": ["pre_roll", "post_roll"],
            }
        ]
        state.open_window = reaction_windows.open_window_for(
            round_number=1,
            seq=0,
            stage="post_roll",
            actor_id="goblin_scout_1",
            target_id=target_id,
            action_kind="attack",
            triggers=reaction_windows.post_roll_triggers({}, hit=hit),
        )
    state.reactions_available = {"player_1": reaction_spend.unspent()}
    ctx.userdata.combat_state = state
    return ctx


class TestVariableCost:
    async def test_pool_cost_ability_is_not_treated_as_free(self):
        result, persistence = await _call("paladin_lay_on_hands")
        assert result["variable_cost"] is not None
        assert "pool" in result["variable_cost"].lower()
        assert result["deducted"] == {"stamina": 0, "focus": 0}
        persistence.update_player_resources.assert_not_called()

    async def test_variable_cost_is_null_for_a_fixed_cost_ability(self):
        result, _ = await _call("warrior_devastating_strike")
        assert result["variable_cost"] is None


class TestActivation:
    @pytest.mark.parametrize(
        ("ability_id", "declaration_id"),
        [
            ("bard_inspire", "bard_inspire"),
            ("cleric_heal_wounds", "divine_heal_wounds"),
            ("warrior_unstoppable_charge", "warrior_unstoppable_charge"),
        ],
    )
    async def test_non_reaction_in_combat_refuses_before_any_write(self, ability_id, declaration_id):
        ctx = make_context()
        ctx.userdata.combat_state = _make_combat_state()
        row = _player(class_=ability_id.split("_")[0])
        mock_db, _conn = make_db_mod()
        transaction = mock_db.transaction
        mock_db.transaction = MagicMock(side_effect=transaction)
        queries = MagicMock()
        queries.get_players_for_update = AsyncMock(return_value={"player_1": row})
        persistence = MagicMock(update_player_resources=AsyncMock())
        persistence.get_active_variant = AsyncMock(return_value=None)
        persistence.owns_elective = AsyncMock(return_value=True)
        condition_mutations = MagicMock(save_many_player_conditions=AsyncMock())

        with pytest.raises(ToolError, match=rf"declare {declaration_id} in the combat phase"):
            await _request_ability_activation_impl(
                ctx,
                ability_id,
                db_mod=mock_db,
                queries_mod=queries,
                persistence_mod=persistence,
                conditions_mutations_mod=condition_mutations,
            )

        assert row["stamina"] == {"current": 10, "max": 10}
        assert row["focus"] == {"current": 10, "max": 10}
        mock_db.transaction.assert_not_called()
        persistence.update_player_resources.assert_not_awaited()
        condition_mutations.save_many_player_conditions.assert_not_awaited()

    async def test_spell_backed_cantrip_refusal_names_its_spell_id(self):
        ctx = make_context()
        ctx.userdata.combat_state = _make_combat_state()

        with pytest.raises(ToolError, match="declare arcane_bolt in the combat phase"):
            await _call("mage_arcane_bolt", context=ctx)

    async def test_every_in_combat_refusal_that_names_declare_phase_is_one_declare_phase_takes(self):
        """Activation and declaration must agree on which authored abilities are usable."""
        catalog = [ability for ability in abilities._abilities.values() if ability.ability_type != "reaction"]
        assert len(catalog) >= 100, f"catalog walk went thin ({len(catalog)}) — abilities did not load"
        compared = 0

        for ability in catalog:
            ctx = make_context()
            ctx.userdata.combat_state = _make_combat_state()
            with pytest.raises(ToolError) as refusal:
                await _request_ability_activation_impl(ctx, ability.id)
            message = str(refusal.value)
            match = re.search(r"declare (\S+) in the combat phase", message)
            if match is None:
                continue
            compared += 1
            if ability.spell_id is not None:
                spells.get_spell(match.group(1))
            state = _make_combat_state()
            from voice_condition_fixtures import place_actors

            place_actors(state)
            state.beat = PhaseBeat.DECLARATION
            declaration = {"player_1": {"type": "ability", "action": match.group(1), "target_id": "goblin_scout_1"}}
            advance_combat_phase(state, declaration)  # ValueError here = the two gates disagree

        assert compared >= 15, f"declare-phase comparison set went thin ({compared})"

    async def test_stamina_core_ability_deducts_and_returns_cue(self):
        result, persistence = await _call("warrior_devastating_strike", stamina=10)
        assert result["deducted"] == {"stamina": 3, "focus": 0}
        assert result["narration_cue"]  # non-empty cue for the DM to voice
        persistence.update_player_resources.assert_awaited_once()
        _args, kwargs = persistence.update_player_resources.call_args
        assert kwargs["stamina"] == 7  # 10 - 3
        assert kwargs["focus"] is None  # focus uncosted -> not written (partial-pool safe)

    async def test_reaction_deducts_under_lock_and_adopts_in_memory_spend(self):
        ctx = _reaction_context()
        persistence = MagicMock()

        async def assert_locked(*args, **kwargs):
            assert ctx.userdata.combat_state_lock.locked()

        persistence.update_player_resources = AsyncMock(side_effect=assert_locked)
        save_combat_state = AsyncMock()
        with patch("db_mutations.save_combat_state", save_combat_state):
            result, persistence = await _call(
                "warrior_brace_for_impact", stamina=5, context=ctx, persistence=persistence
            )

        assert result["deducted"]["stamina"] == 2
        assert result["narration_cue"]
        persistence.update_player_resources.assert_awaited_once()
        window = ctx.userdata.combat_state.open_window
        assert ctx.userdata.combat_state.reactions_available["player_1"] == {
            "spent": True,
            "ability_id": "warrior_brace_for_impact",
            "window_id": window["id"],
            "stage": "post_roll",
            "held_seq": 0,
        }
        save_combat_state.assert_awaited_once()

    async def test_second_reaction_is_refused_before_resource_write(self):
        ctx = _reaction_context()
        await _call("warrior_brace_for_impact", context=ctx)
        persistence = MagicMock()
        persistence.update_player_resources = AsyncMock()

        with pytest.raises(ToolError, match="already spent"):
            await _call("warrior_brace_for_impact", context=ctx, persistence=persistence)

        persistence.update_player_resources.assert_not_called()

    async def test_mismatched_reaction_window_is_refused_before_resource_write(self):
        ctx = _reaction_context()
        persistence = MagicMock()
        persistence.update_player_resources = AsyncMock()

        with pytest.raises(ToolError, match=r"on_enemy_move.*on_hit"):
            await _call("warrior_opportunity_strike", context=ctx, persistence=persistence)

        persistence.update_player_resources.assert_not_called()
        assert not reaction_spend.is_spent(ctx.userdata.combat_state.reactions_available["player_1"])

    async def test_self_targeted_reaction_refuses_an_ally_s_window_without_spending(self):
        ctx = _reaction_context(target_id="player_2")
        persistence = MagicMock()
        persistence.update_player_resources = AsyncMock()

        with pytest.raises(ToolError) as refused:
            await _call("rogue_uncanny_dodge", context=ctx, persistence=persistence)

        assert "player_2" in str(refused.value)
        assert "player_1" in str(refused.value)
        persistence.update_player_resources.assert_not_called()
        assert not reaction_spend.is_spent(ctx.userdata.combat_state.reactions_available["player_1"])

    async def test_ally_targeted_reaction_accepts_an_ally_s_window(self):
        ctx = _reaction_context(target_id="player_2")

        result, persistence = await _call("guardian_intercept", context=ctx)

        assert result["deducted"]["stamina"] == 3
        persistence.update_player_resources.assert_awaited_once()
        assert ctx.userdata.combat_state.reactions_available["player_1"] == {
            "spent": True,
            "ability_id": "guardian_intercept",
            "window_id": ctx.userdata.combat_state.open_window["id"],
            "stage": "post_roll",
            "held_seq": 0,
        }

    async def test_reaction_with_no_open_window_is_refused_before_resource_write(self):
        ctx = _reaction_context(window_open=False)
        persistence = MagicMock()
        persistence.update_player_resources = AsyncMock()

        with pytest.raises(ToolError, match="no reaction window is open"):
            await _call("warrior_brace_for_impact", context=ctx, persistence=persistence)

        persistence.update_player_resources.assert_not_called()

    async def test_reaction_refused_by_cost_does_not_burn_the_round_s_reaction(self):
        """A refused activation must not charge the player."""
        ctx = _reaction_context()
        persistence = MagicMock()
        persistence.update_player_resources = AsyncMock()

        with pytest.raises(ToolError, match="Not enough Stamina"):
            await _call("warrior_brace_for_impact", stamina=0, context=ctx, persistence=persistence)

        assert not reaction_spend.is_spent(ctx.userdata.combat_state.reactions_available["player_1"])
        persistence.update_player_resources.assert_not_called()

    async def test_reaction_spend_lands_on_the_state_the_session_holds_after_payment(self):
        """Use post-payment state across the await, so rebinds cannot restore spent resources."""
        ctx = _reaction_context()
        persistence = MagicMock()

        async def _swap_state(*_args, **_kwargs):
            ctx.userdata.combat_state = copy.deepcopy(ctx.userdata.combat_state)

        persistence.update_player_resources = AsyncMock(side_effect=_swap_state)

        await _call("rogue_uncanny_dodge", context=ctx, persistence=persistence)

        persistence.update_player_resources.assert_awaited_once()
        assert reaction_spend.is_spent(ctx.userdata.combat_state.reactions_available["player_1"])

    async def test_reaction_outside_combat_activates_ungated(self):
        """Spy and diplomat reactions must remain usable outside combat."""
        persistence = MagicMock()
        persistence.update_player_resources = AsyncMock()
        player = _player(class_="warrior")
        player["level"] = 6

        result, _ = await _call("warrior_opportunity_strike", player=player, persistence=persistence)

        assert result["narration_cue"]
        persistence.update_player_resources.assert_awaited()


class TestRejection:
    async def test_insufficient_focus_rejects_without_deducting(self):
        with pytest.raises(ToolError):
            await _call("cleric_heal_wounds", focus=1)

    async def test_insufficient_focus_does_not_deduct(self):
        ctx = make_context()
        mock_db, _conn = make_db_mod()
        queries = MagicMock()
        # Cleric owns the core heal (class==archetype) — so the rejection is the
        # insufficient-focus path, not the own-the-base gate. story-008: caster row via the batch.
        queries.get_players_for_update = AsyncMock(return_value={"player_1": _player(focus=1, class_="cleric")})
        persistence = MagicMock()
        persistence.update_player_resources = AsyncMock()
        persistence.get_active_variant = AsyncMock(return_value=None)
        persistence.owns_elective = AsyncMock(return_value=False)
        with pytest.raises(ToolError):
            await _request_ability_activation_impl(
                ctx, "cleric_heal_wounds", db_mod=mock_db, queries_mod=queries, persistence_mod=persistence
            )
        persistence.update_player_resources.assert_not_called()

    async def test_unknown_ability_rejects(self):
        with pytest.raises(ToolError):
            await _call("no_such_ability_xyz")


class TestOwnershipGate:
    async def test_core_ability_rejected_when_class_mismatch(self):
        ctx = make_context()
        mock_db, _conn = make_db_mod()
        queries = MagicMock()
        queries.get_players_for_update = AsyncMock(return_value={"player_1": _player(class_="paladin")})
        persistence = MagicMock()
        persistence.update_player_resources = AsyncMock()
        persistence.get_active_variant = AsyncMock(return_value=None)
        persistence.owns_elective = AsyncMock(return_value=False)
        with pytest.raises(ToolError, match="haven't learned"):
            await _request_ability_activation_impl(
                ctx, "warrior_devastating_strike", db_mod=mock_db, queries_mod=queries, persistence_mod=persistence
            )
        persistence.update_player_resources.assert_not_called()

    async def test_elective_rejected_when_not_owned(self):
        result_raises = False
        try:
            await _call("warrior_cleaving_blow", owns_elective=False)
        except ToolError as e:
            result_raises = "haven't learned" in str(e)
        assert result_raises, "expected ToolError for an unowned elective"

    async def test_elective_allowed_when_owned(self):
        result, persistence = await _call("warrior_cleaving_blow", owns_elective=True)
        assert result["deducted"]["stamina"] == 4  # base Cleaving Blow cost
        persistence.update_player_resources.assert_awaited_once()

    async def test_core_ability_rejected_below_level_without_deducting(self):
        player = _player(class_="bard")
        player["level"] = 1
        persistence = MagicMock()
        persistence.update_player_resources = AsyncMock()

        with pytest.raises(ToolError, match="haven't learned Mass Inspire"):
            await _call("bard_mass_inspire", player=player, persistence=persistence)

        persistence.update_player_resources.assert_not_awaited()
