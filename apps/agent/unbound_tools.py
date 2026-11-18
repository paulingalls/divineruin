"""Member-scoped Unbound capabilities, invoked through existing verbs."""

import json

from livekit.agents.llm import ToolError
from livekit.agents.voice import RunContext

import db
import db_mutations_resonance
import db_queries
import hollow_echo
import patron_deeds
import resonance_events
from party_state import PartyMember
from patron_ability_tools import spent_state
from session_data import SessionData
from unbound_autonomy import SAVES, load_unbound, read_autonomy

VEIL_CLARITY = "unbound_veil_clarity"
RAW_CHANNELING = "unbound_raw_channeling"
VEIL_MASTERY = "unbound_veil_mastery"
DIVINE_IMMUNITY = "unbound_divine_immunity"
SAVE_IDS = {f"unbound_self_reliant_{save}": save for save in SAVES}
MILESTONE_IDS = frozenset((*SAVE_IDS, DIVINE_IMMUNITY))


def is_unbound(patron: str | None) -> bool:
    return patron in (None, "none")


def patron_query(track: dict, player: dict) -> dict:
    autonomy = read_autonomy(player.get("unbound_autonomy"))
    tiers = load_unbound()[1]
    attained = tiers.index(autonomy["tier"])
    choice = autonomy.get("save_proficiency")
    proficiencies = {s.lower() for s in player.get("saving_throw_proficiencies", [])}
    milestones = []
    for token, save in SAVE_IDS.items():
        if choice:
            rule = f"One-time choice consumed: {choice}."
        elif save in proficiencies:
            rule = f"Already proficient in {save}; choose another save."
        else:
            rule = f"Use activate(id='{token}') to choose {save} proficiency once."
        milestones.append(
            dict(
                id=token,
                name=f"Self-Reliant: {save.title()}",
                tier=tiers[0],
                reached=True,
                rule=rule,
                proficient=save in proficiencies,
                chosen=choice == save,
            )
        )
    spent = spent_state(player, DIVINE_IMMUNITY)["spent"]
    rule = (
        f"Requires {tiers[1]}."
        if attained < 1
        else "Spent; a long rest restores Divine Immunity."
        if spent
        else f"Use activate(id='{DIVINE_IMMUNITY}') to ignore one chosen divine ability; recharges on a long rest."
    )
    milestones.append(
        dict(id=DIVINE_IMMUNITY, name="Divine Immunity", tier=tiers[1], reached=attained >= 1, rule=rule, spent=spent)
    )
    mastery_rule = (
        f"Requires {tiers[2]}. Automatic there: the first Hollow Echo per member session becomes Nothing stirs."
    )
    milestones.append(
        dict(id=VEIL_MASTERY, name="Veil Mastery", tier=tiers[2], reached=attained == 2, rule=mastery_rule)
    )
    return {
        "state": "Unbound",
        "autonomy": dict(level=autonomy["level"], tier=autonomy["tier"], milestones=milestones),
        "abilities": [],
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
                "rule": mastery_rule,
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
            await patron_deeds.record_deed(player_id, "channeled_raw", conn=conn)
        member.resonance.current = current
        member.resonance.flickering_bonus = track["flickering_bonus"]
        member.unbound_raw_channeling_used = True
        await resonance_events.publish_resonance_changed(session, resonance_track=member.resonance, caster_id=player_id)
        return json.dumps({"resonance_added": 3, "state": member.resonance.state})
