"""Exact-identity wrongdoing from encounter attacks and party grievance marks."""

from livekit.agents.llm import ToolError

GRIEVANCES = {"broken_promise", "injustice"}


def validate_ledger(ledger, participants):
    # Mirrors CombatParticipant.is_ally: a player risen as a temporary_hollowed echo is a hostile key.
    hostiles = {p["id"] for p in participants if p["type"] not in ("player", "companion")}
    if not isinstance(ledger, dict) or any(
        key not in hostiles or side not in ("ally", "hostile") for key, side in ledger.items()
    ):
        raise ValueError("Malformed first_hostility encounter ledger")
    return dict(ledger)


def record_attack(state, attacker, target):
    if state is None or attacker.is_ally == target.is_ally:
        return
    hostile = target if attacker.is_ally else attacker
    state.first_hostility.setdefault(hostile.id, "ally" if attacker.is_ally else "hostile")


def aggression_facts(state):
    return [
        {"target_id": target, "source": "aggression", "attacked_party_first": True}
        for target, side in state.first_hostility.items()
        if side == "hostile"
    ]


def grievance_key(npc_id):
    return f"grievance:{npc_id}"


def grievance(player, target_id):
    flags = player.get("flags", {})
    if not isinstance(flags, dict):
        raise ToolError("Malformed stored player flags")
    key = grievance_key(target_id)
    if key not in flags:
        return None
    value = flags[key]
    if value not in GRIEVANCES:
        raise ToolError(f"Malformed stored grievance for {target_id}")
    return value


async def wrongdoing(session, player, *, target_id, combat_state, conn, queries_mod):
    """Evidence that the single explicit target wronged the party, or None."""
    state = combat_state if combat_state is not None else session.combat_state
    evidence = None
    if state is not None:
        if state.get_participant(target_id) is None:
            raise ToolError(f"Unknown target: {target_id}")
        if state.first_hostility.get(target_id) == "hostile":
            evidence = {"target_id": target_id, "source": "aggression"}
    # Out of combat any target id is tolerated: only update_npc_disposition writes grievances,
    # and it refuses unknown NPCs, so objects, corpses, companions and DM-narrated ids find no
    # grievance and the cast generates standard Resonance.
    # Exact runtime identity: creature templates never inherit an NPC's grievance.
    for pid in session.party.member_ids:
        row = player if pid == player["player_id"] else await queries_mod.get_player(pid, conn=conn)
        if row is None:
            raise ToolError(f"Player '{pid}' not found")
        kind = grievance(row, target_id)
        if kind:
            evidence = {"target_id": target_id, "player_id": pid, "source": "grievance", "kind": kind}
    return evidence
