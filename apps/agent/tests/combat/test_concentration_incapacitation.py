"""Concentration ends when a hostile incapacitating condition lands."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from combat._helpers import _resolve_deps, _resolve_round
from sample_fixtures import make_context, make_db_mod

import concentration_break
import reaction_spend
from conditions import apply_condition
from session_data import CombatParticipant, CombatState


def _participant(participant_id: str, participant_type: str, initiative: int) -> CombatParticipant:
    return CombatParticipant(
        id=participant_id,
        name=participant_id,
        type=participant_type,
        initiative=initiative,
        hp_current=25,
        hp_max=25,
        ac=14,
    )


def _condition_state(condition: str, *, target_id="player_1", extra_players=(), companion=False) -> CombatState:
    allies = [_participant("player_1", "player", 20)]
    allies.extend(_participant(player_id, "player", 19 - index) for index, player_id in enumerate(extra_players))
    if companion:
        allies.append(_participant("companion_1", "companion", 10))
    enemy = _participant("enemy_1", "enemy", 1)
    enemy.action_pool = [
        {
            "name": "Condition Gaze",
            "damage": "0",
            "damage_type": "psychic",
            "properties": ["control"],
            "applies_condition": condition,
            "save": "wisdom",
            "dc": 12,
        }
    ]
    participants = [*allies, enemy]
    declarations = {ally.id: {"type": "defend"} for ally in allies}
    declarations[enemy.id] = {"type": "attack", "action": "Condition Gaze", "target_id": target_id}
    return CombatState(
        combat_id="combat_condition_concentration",
        participants=participants,
        initiative_order=[participant.id for participant in participants],
        location_id="accord_guild_hall",
        beat="resolution",
        pending_declarations=declarations,
    )


async def _run_round(
    condition: str,
    *,
    target_id="player_1",
    extra_players=(),
    companion=False,
    save_face=1,
    spells_by_player=None,
    blessed_ids=(),
):
    state = _condition_state(condition, target_id=target_id, extra_players=extra_players, companion=companion)
    for participant_id in blessed_ids:
        participant = state.get_participant(participant_id)
        assert participant is not None
        participant.conditions = apply_condition([], "blessed", source="divine_bless")
    ctx = make_context(party_member_ids=list(extra_players))
    state.reactions_available = {
        participant.id: reaction_spend.unspent() for participant in state.participants if participant.type == "player"
    }
    ctx.userdata.combat_state = state
    for player_id, spell_id in (spells_by_player or {}).items():
        if player_id != "player_1" and ctx.userdata.party.member(player_id) is None:
            raise AssertionError(f"missing party member {player_id}")
        ctx.userdata.member_state(player_id).concentration.spell_id = spell_id
    persist = AsyncMock()
    db_mod, phase_conn = make_db_mod()
    deps = {**_resolve_deps(), "concentration_break_mod": concentration_break, "db_mod": db_mod}
    with (
        patch("check_resolution.dice_roll", return_value=SimpleNamespace(total=save_face)),
        patch.object(concentration_break.db_mutations_concentration, "update_player_concentration", persist),
    ):
        result = await _resolve_round(ctx, **deps)
    assert not isinstance(result, tuple)
    packet = next(item for item in result["packets"] if item["actor_id"] == "enemy_1")
    return ctx.userdata, packet, persist, phase_conn


@pytest.mark.asyncio
@pytest.mark.parametrize("condition", ["stunned", "incapacitated", "paralyzed", "petrified"])
async def test_landed_cannot_act_condition_ends_concentration(condition):
    session, packet, persist, conn = await _run_round(condition, spells_by_player={"player_1": "divine_bless"})

    assert packet["condition_inflicted"] == condition
    assert packet["concentration_broken"] == "divine_bless"
    assert session.concentration.spell_id is None
    persist.assert_awaited_once_with("player_1", None, conn=conn)


@pytest.mark.asyncio
async def test_frightened_keeps_concentration():
    session, packet, persist, _ = await _run_round("frightened", spells_by_player={"player_1": "divine_bless"})

    assert packet["condition_inflicted"] == "frightened"
    assert "concentration_broken" not in packet
    assert session.concentration.spell_id == "divine_bless"
    persist.assert_not_awaited()


@pytest.mark.asyncio
async def test_resisted_cannot_act_condition_keeps_concentration():
    session, packet, persist, _ = await _run_round(
        "stunned", save_face=20, spells_by_player={"player_1": "divine_bless"}
    )

    assert packet["condition_resisted"] == "stunned"
    assert "concentration_broken" not in packet
    assert session.concentration.spell_id == "divine_bless"
    persist.assert_not_awaited()


@pytest.mark.asyncio
async def test_stunned_companion_does_not_enter_party_concentration():
    _, packet, persist, _ = await _run_round("stunned", target_id="companion_1", companion=True)

    assert packet["condition_inflicted"] == "stunned"
    assert "concentration_broken" not in packet
    persist.assert_not_awaited()


@pytest.mark.asyncio
async def test_non_concentrating_player_emits_no_break():
    _, packet, persist, _ = await _run_round("stunned")

    assert packet["condition_inflicted"] == "stunned"
    assert "concentration_broken" not in packet
    persist.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("second_caster", [False, True])
async def test_linked_bless_condition_tracks_remaining_casters(second_caster):
    spells = {"player_1": "divine_bless"}
    if second_caster:
        spells["player_2"] = "divine_bless"
    session, _, _, _ = await _run_round(
        "stunned",
        extra_players=("player_2",),
        spells_by_player=spells,
        blessed_ids=("player_2",),
    )
    ally = session.combat_state.get_participant("player_2")
    assert ally is not None

    assert any(c["type"] == "blessed" for c in ally.conditions) is second_caster


@pytest.mark.asyncio
async def test_stunned_non_primary_breaks_only_their_spell():
    session, packet, persist, conn = await _run_round(
        "stunned",
        target_id="player_2",
        extra_players=("player_2",),
        spells_by_player={"player_1": "arcane_fly", "player_2": "divine_bless"},
    )

    assert packet["concentration_broken"] == "divine_bless"
    assert session.member_state("player_1").concentration.spell_id == "arcane_fly"
    assert session.member_state("player_2").concentration.spell_id is None
    persist.assert_awaited_once_with("player_2", None, conn=conn)


@pytest.mark.asyncio
async def test_unknown_player_id_fails_loud():
    session = make_context().userdata
    session.combat_state = _condition_state("stunned")
    with pytest.raises(ValueError, match="missing_player"):
        await concentration_break.break_concentration_on_incapacitation(
            session,
            "missing_player",
            combat_state=session.combat_state,
            conn=object(),
        )
