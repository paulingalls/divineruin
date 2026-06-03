"""Archetype milestone helper for the DM agent (M2.3 / M4).

apply_milestone_grant writes an auto_grant milestone's combat flag into
players.data.flags. The shared Resolve helper that award_xp / _award_xp_core call
on the L10/15/20 leveling chokepoint (grants persist as players.data markers,
never character_abilities rows — decision 4c0677dae1be). The L5 specialization
fork resolves via the generic `select` verb (choice_tools.py); resolve_milestone
was removed in M4 (story-004 deregistered the tool, story-006 deleted the impl).
"""

import db_mutations
import milestones


async def apply_milestone_grant(
    milestone: milestones.Milestone, player_id: str, *, conn, flags_mod=db_mutations
) -> bool:
    """Write an auto_grant milestone's combat flag into players.data.flags.

    No-op (returns False) for a null grant or a narrative-only grant (flag is None).
    Called by award_xp's auto-grant loop (_award_xp_core), so the grant write lives
    in exactly one place.
    """
    grant = milestone.grant
    if grant is not None and grant.flag:
        await flags_mod.set_player_flag(player_id, grant.flag, True, conn=conn)
        return True
    return False
