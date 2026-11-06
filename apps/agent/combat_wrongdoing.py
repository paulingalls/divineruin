"""Exact-identity wrongdoing from encounter attacks and party grievance marks."""

from livekit.agents.llm import ToolError

from condition_produce import resolve_effective_targets

GRIEVANCES = {"broken_promise", "injustice"}


def validate_ledger(ledger, participants):
    hostiles = {p["id"] for p in participants if p["type"] == "enemy"}
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


async def wrongdoing(session, player, *, target_id, target_ids, combat_state, conn, queries_mod):
    targets = (
        resolve_effective_targets(target_ids, target_id, self_value=None) if target_id is not None or target_ids else []
    )
    state = combat_state if combat_state is not None else session.combat_state
    evidence = None
    for target in targets:
        if state is not None:
            if state.get_participant(target) is None:
                raise ToolError(f"Unknown target: {target}")
            if state.first_hostility.get(target) == "hostile":
                evidence = {"target_id": target, "source": "aggression"}
        elif await queries_mod.get_player(target, conn=conn) is None:
            if await conn.fetchrow("SELECT id FROM npcs WHERE id=$1", target) is None:
                raise ToolError(f"Unknown target: {target}")
        # Exact runtime identity: creature templates never inherit an NPC's grievance.
        for pid in session.party.member_ids:
            row = player if pid == player["player_id"] else await queries_mod.get_player(pid, conn=conn)
            if row is None:
                raise ToolError(f"Player '{pid}' not found")
            kind = grievance(row, target)
            if kind:
                evidence = {"target_id": target, "player_id": pid, "source": "grievance", "kind": kind}
    return evidence
