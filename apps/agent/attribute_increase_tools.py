"""Authenticated spoken redirects of committed, unexpired attribute grants."""

import json

from livekit.agents.llm import ToolError

from attribute_increase_events import publish_snapshots
from attribute_increase_persistence import patch_player
from attribute_increases import ATTRIBUTES, PREFIX, receipt, recompute, records, validate_scores


async def select(session, choice_id: str, option: str, *, db_mod, queries_mod) -> str:
    actor = session.acting_player_id
    async with session.combat_state_lock:
        if session.in_combat:
            raise ToolError("You can redirect this increase after the fight.")
        async with db_mod.transaction() as conn:
            players = await queries_mod.get_players_for_update([actor], conn=conn)
            player = players.get(actor)
            if player is None:
                raise ToolError("No attribute increase is available for you.")
            saved = records(player)
            level = choice_id.removeprefix(PREFIX)
            record = saved.get(level)
            if record is None:
                raise ToolError("That attribute increase is not available for you.")
            if record["locked"]:
                raise ToolError("Your long rest fixed this attribute increase; it can no longer be redirected.")
            if option not in ATTRIBUTES:
                raise ToolError("Choose a full attribute name for this increase.")
            scores = dict(player["attributes"])
            validate_scores(scores)
            for key, delta in record["allocation"].items():
                scores[key] -= delta
            if scores[option] > 18:
                raise ToolError(f"{option.title()} cannot receive both points without exceeding 20.")
            scores[option] += 2
            allocation = {option: 2}
            session.validate_acting_player(actor)
            if record["allocation"] != allocation:
                record["allocation"] = allocation
                patch = {**recompute({**player, "attributes": scores}), "attribute_increases": saved}
                await patch_player(actor, patch, conn=conn)
                player = {**player, **patch}
            result = receipt(actor, player, level, record)
        await publish_snapshots(session, [actor])
    return json.dumps(result)
