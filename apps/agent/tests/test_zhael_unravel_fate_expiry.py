"""Rewind the lifetime clock across a concentration expiry."""

from unittest.mock import patch

import pytest
from _zhael_fate_fixtures import defend, game_tools
from _zhael_unravel_fixtures import activate, durable
from _zhael_unravel_fixtures import unravel as unravel
from acceptance._capstone_helpers import _d20
from combat._round_checkpoint_helpers import Fight


async def test_expiry_round_rewind_restores_clock_and_owned_conditions(unravel: Fight) -> None:
    import character_spells
    from caster_state import ConcentrationState
    from check_tools import check
    from conditions import apply_condition, has_condition

    fight = unravel
    recipient, caster = fight.ids
    bless = "divine_bless"
    await character_spells.record_learned(caster, bless, "discovery", conn=fight.pool)
    await fight.start()
    await fight.declare(
        {"kind": "ability", "actor_id": caster, "action": bless, "targets": [recipient], "argument_type": ""},
        *(defend(p.id) for p in fight.session.combat_state.participants if p.id != caster),
    )
    await fight.finish_round(2)
    for round_number in range(3, 11):
        await fight.declare()
        await fight.finish_round(round_number)
    opening = await fight.row()
    original = opening["round_checkpoints"][-1]["players"][caster]["data"]["concentration"]
    assert original == {"spell_id": bless, "combat_id": opening["combat_id"], "started_round": 1, "elapsed_seconds": 0}

    target = fight.session.combat_state.get_participant(recipient)
    target.conditions = apply_condition(target.conditions, "frightened", source="mawling_1", duration=3)
    await fight.declare()
    await fight.call("resolve_phase")
    with patch("check_resolution.dice_roll", return_value=_d20(19)):
        held = (await fight.call("resolve_phase"))["fate_offer"]
    paused = await fight.reload()
    assert paused["round_number"] == 11 and paused["wrap_continuation"] is not None
    assert has_condition(fight.session.combat_state.get_participant(recipient).conditions, "blessed")
    assert (await durable(fight))["players"][caster]["data"]["concentration"] == original
    await fight.call("activate", id="zhael_fates_thread", offer_id=held["offer_id"], keep="original")
    await fight.finish_round(11)
    assert (await durable(fight))["players"][caster]["data"]["concentration"]["spell_id"] is None
    assert not has_condition(fight.session.combat_state.get_participant(recipient).conditions, "blessed")

    assert (await activate(fight))["round"] == 10
    assert fight.session.member_state(caster).concentration == ConcentrationState.from_record(original)
    assert (await durable(fight))["players"][caster]["data"]["concentration"] == original
    assert has_condition(fight.session.combat_state.get_participant(recipient).conditions, "blessed")
    with (
        patch("check_resolution.dice_roll", return_value=_d20(10)),
        patch("condition_bonus.dice_roll", return_value=_d20(3)),
    ):
        rolled = await fight.invoke(
            game_tools(fight.session, check),
            "check",
            actor=recipient,
            roll={"kind": "save", "save_type": "wisdom", "dc": 24, "effect_on_fail": "resist"},
        )
    if offer := rolled.get("fate_offer"):
        rolled = await fight.call("activate", id="zhael_fates_thread", offer_id=offer["offer_id"], keep="original")
    assert rolled["total"] == 14

    await fight.declare()
    await fight.call("resolve_phase")
    with patch("combat_round_checkpoint.capture", side_effect=RuntimeError("expiry checkpoint failed")):
        with pytest.raises(RuntimeError, match="expiry checkpoint failed"):
            await fight.call("resolve_phase")
    assert fight.session.member_state(caster).concentration == ConcentrationState.from_record(original)
    assert (await durable(fight))["players"][caster]["data"]["concentration"] == original
    assert has_condition(fight.session.combat_state.get_participant(recipient).conditions, "blessed")
    await fight.finish_round(11)
    assert (await durable(fight))["players"][caster]["data"]["concentration"]["spell_id"] is None
