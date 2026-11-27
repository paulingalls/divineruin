from unittest.mock import patch

import pytest
from _zhael_unravel_fixtures import GIFT, assert_refused, durable, favor, opening, patch_player
from _zhael_unravel_fixtures import unravel as unravel
from combat._round_checkpoint_helpers import Fight

from exploration_agent import ExplorationAgent


@pytest.mark.parametrize(
    ("case", "reason"),
    [
        ("round_one", "no restorable checkpoint"),
        ("no_combat", "requires an active fight"),
        ("ended", "requires an active fight"),
        ("terminal", "requires an active fight"),
        ("stale", "fight opening changed"),
        ("wrong_combat", "fight opening changed"),
        ("declarations", "untouched declaration beat"),
        ("open_window", "reaction window"),
        ("held_actions", "held work"),
        ("ally_continuation", "held work"),
        ("wrap_continuation", "held work"),
        ("legendary_continuation", "held work"),
        ("inner_fire_continuation", "held work"),
        ("wrong_patron", "requires a follower of zhael"),
        ("lower_tier", "Exalted"),
        ("spent", "new session"),
    ],
)
async def test_refuses_without_changing_the_fight(unravel: Fight, case: str, reason: str) -> None:
    fight = unravel
    if case == "no_combat":
        await fight.start()
        fight.session.combat_state = None
        await assert_refused(fight, reason)
        return
    await opening(fight, 0 if case == "round_one" else 2)
    state = fight.session.combat_state
    assert state is not None
    if case == "ended":
        with patch("combat_end._build_handoff_agent", return_value=ExplorationAgent()):
            await fight.call("end_combat", outcome="fled")
        assert (await durable(fight))["combat"] is None
        fight.session.combat_state = state
    elif case == "terminal":
        state.deescalated = True
        await fight.write_row(state.to_dict())
    elif case == "stale":
        state.round_number -= 1
    elif case == "wrong_combat":
        row = await fight.row()
        row["combat_id"] += "_other"
        fight.combats.insert(0, row["combat_id"])
        for checkpoint in row["round_checkpoints"]:
            checkpoint["combat_id"] = checkpoint["combat"]["combat_id"] = row["combat_id"]
        await fight.write_row(row)
    elif case == "declarations":
        await fight.declare()
    elif case in {
        "open_window",
        "held_actions",
        "ally_continuation",
        "wrap_continuation",
        "legendary_continuation",
        "inner_fire_continuation",
    }:
        setattr(state, case, [{"held": True}] if case == "held_actions" else {"held": True})
    elif case == "wrong_patron":
        await favor(fight, fight.ids[0], "kaelen")
    elif case == "lower_tier":
        await favor(fight, fight.ids[0], level=30)
    elif case == "spent":
        await patch_player(fight, fight.ids[0], patron_gifts={GIFT: {"spent": True}})
    await assert_refused(fight, reason)


@pytest.mark.parametrize(
    ("patron", "ability"),
    [("valdris", "valdris_mark_of_justice"), ("syrath", "syrath_veilstep"), (None, "unbound_raw_channeling")],
)
async def test_effect_settled_at_opening_blocks_rewind(unravel: Fight, patron: str | None, ability: str) -> None:
    fight = unravel
    await opening(fight)
    guest = fight.ids[1]
    if patron is not None:
        await favor(fight, guest, patron, 70)
    arguments: dict[str, object] = {"target_id": "mawling_1"} if patron == "valdris" else {}
    if patron == "syrath":
        origin = fight.session.combat_state.spatial["positions"][guest]
        arguments["destination"] = {**origin, "y": origin["y"] + 5}
    await fight.call("activate", id=ability, actor=guest, **arguments)
    await assert_refused(fight, "untouched declaration beat")


async def test_rewind_accepts_no_entity_or_condition_selectors(unravel: Fight) -> None:
    fight = unravel
    await opening(fight)
    for selector in (
        {"target_id": fight.ids[1]},
        {"target_ids": [fight.ids[1]]},
        {"condition": "poisoned"},
    ):
        await assert_refused(fight, "Omit entity and condition selectors", selectors=selector)
