"""Fault injection at the option-effect write inside the real quest transaction."""

from unittest.mock import patch

from acceptance.quest_decision_walk import assert_choice, command, decision_walk, snapshot

import db_mutations


def test_option_write_failure_rolls_back_everything(harness):
    async def check():
        arc = await decision_walk(harness, "defend_millhaven", 1)
        before, events = await snapshot(arc), list(arc.events)
        original = db_mutations.set_player_flag
        reached = False

        async def fail_after_write(*args, **kwargs):
            nonlocal reached
            await original(*args, **kwargs)
            if args[1] == "millhaven_evacuation":
                reached = True
                raise RuntimeError("injected option write failure")

        with patch.object(db_mutations, "set_player_flag", side_effect=fail_after_write):
            receipt = await command(arc, 2, "watchtower")
        assert reached and receipt.is_error
        assert await snapshot(arc) == before and arc.events == events
        await assert_choice(arc, "watchtower")

    harness.run_sync(check())
