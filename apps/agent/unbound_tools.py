"""Member-scoped Unbound capabilities, invoked through existing verbs."""

import json

from livekit.agents.llm import ToolError
from livekit.agents.voice import RunContext

import db
import db_mutations_resonance
import db_queries
import hollow_echo
import resonance_events
from party_state import PartyMember
from session_data import SessionData

VEIL_CLARITY = "unbound_veil_clarity"
RAW_CHANNELING = "unbound_raw_channeling"
VEIL_MASTERY = "unbound_veil_mastery"


def is_unbound(patron: str | None) -> bool:
    return patron in (None, "none")


def patron_query(track: dict) -> dict:
    return {
        "state": "Unbound",
        "resonance": {"current": track["current"], "state": track["state"]},
        "capabilities": [
            {"id": VEIL_CLARITY, "name": "Veil Clarity", "rule": "Know your exact Resonance."},
            {
                "id": RAW_CHANNELING,
                "name": "Raw Channeling",
                "rule": f"Use activate(id='{RAW_CHANNELING}') to add exactly 3 Resonance, once per encounter.",
            },
            {
                "id": VEIL_MASTERY,
                "name": "Veil Mastery",
                "rule": "Automatic: the first Hollow Echo per member session becomes Nothing stirs. Granted unconditionally.",
            },
        ],
    }


def veil_mastery(
    echo: hollow_echo.HollowEchoResult, patron: str | None, caster: PartyMember
) -> tuple[hollow_echo.HollowEchoResult, bool]:
    if is_unbound(patron) and not caster.unbound_veil_mastery_used:
        return hollow_echo.nothing_stirs(echo), True
    return echo, False


async def _raw_channeling_impl(context: RunContext[SessionData]) -> str:
    context.disallow_interruptions()
    session = context.userdata
    async with session.combat_state_lock:
        player_id = session.acting_player_id
        member = session.member_state(player_id)
        if session.combat_state is None:
            raise ToolError("Raw Channeling requires an encounter.")
        if session.combat_state.get_participant(player_id) is None:
            raise ToolError("Raw Channeling requires participation in the encounter.")
        if member.unbound_raw_channeling_used:
            raise ToolError("Raw Channeling is already spent this encounter.")
        async with db.transaction() as conn:
            player = await db_queries.get_player(player_id, conn=conn, for_update=True)
            if player is None:
                raise ToolError(f"Unknown player: {player_id}")
            if not is_unbound((player.get("divine_favor") or {}).get("patron")):
                raise ToolError("Only the Unbound can use Raw Channeling.")
            track = await db_mutations_resonance.read_player_resonance(player_id, conn=conn)
            current = track["current"] + 3
            session.validate_acting_player(player_id)
            await db_mutations_resonance.update_player_resonance(player_id, current, conn=conn)
        member.resonance.current = current
        member.resonance.flickering_bonus = track["flickering_bonus"]
        member.unbound_raw_channeling_used = True
        await resonance_events.publish_resonance_changed(session, resonance_track=member.resonance, caster_id=player_id)
        return json.dumps({"resonance_added": 3, "state": member.resonance.state})
