"""Read-only spell lookup tool for the DM agent (M3.3 story-004).

``get_spell_info`` returns the full catalog data for a spell so the DM can describe its cost,
source, tier, mechanics, or narration before casting. Split out of ``spell_casting`` (which owns
the mutating cast path) so the read-only lookup is its own concern — it spends nothing and opens
no transaction.
"""

import json
from dataclasses import asdict

from livekit.agents.llm import ToolError, function_tool
from livekit.agents.voice import RunContext

import spells
from session_data import SessionData
from tool_support import _validate_id


@function_tool()
async def get_spell_info(
    context: RunContext[SessionData],
    spell_id: str,
) -> str:
    """Look up the full details of a spell by its id (e.g. 'arcane_bolt').
    Call when the player or DM needs a spell's cost, source, tier, mechanics, or
    narration before casting. Read-only — does not cast or spend anything. Returns
    the spell's full catalog data as JSON; raises if the spell id is unknown."""
    return await _get_spell_info_impl(context, spell_id)


async def _get_spell_info_impl(
    context: RunContext[SessionData],
    spell_id: str,
    *,
    spells_mod=spells,
) -> str:
    _validate_id(spell_id, "spell_id")
    try:
        spell = spells_mod.get_spell(spell_id)
    except ValueError as e:
        raise ToolError(str(e)) from e
    return json.dumps(asdict(spell))
