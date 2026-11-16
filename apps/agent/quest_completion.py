"""Post-commit quest memory and metrics, shared by tools and combat."""

from quest_authority import PendingQuest
from session_data import SessionData


def finish_quest(session: SessionData, pending: PendingQuest) -> dict:
    response = pending.response
    quest_id = response["quest_id"]
    quest_name = response["quest_name"]
    new_stage_id = response["new_stage"]
    is_completion = response["completed"]
    rewards_applied = response["rewards_applied"]
    new_stage = response
    party_ids = pending.party_ids
    item_recipients = pending.item_recipients
    outcome = pending.xp
    for pid, level in pending.corruption.items():
        session.member_state(pid).corruption_level = level
    for note in pending.notes:
        session.record_event(note)
    for reward in rewards_applied:
        if reward["type"] == "xp":
            session.record_event(f"Awarded {reward['amount']} XP: quest '{quest_name}' stage completed")
        elif reward["type"] == "favor" and reward["amount"] > 0:
            session.record_event(f"Divine favor +{reward['amount']} ({reward['patron']}): quest '{quest_name}'")
    if is_completion:
        session.record_event(f"Quest '{quest_name}' completed")
        session.record_companion_memory(f"Quest '{quest_name}' completed")
    else:
        session.record_event(f"Quest '{quest_name}' advanced to stage {new_stage_id}")
        session.record_companion_memory(f"Quest '{quest_name}' progressed to: {new_stage.get('objective', '')}")
    if quest_id not in session.session_quests_progressed:
        session.session_quests_progressed.append(quest_id)
    for pid in party_ids:
        session.record_player_metric(pid, "quest_progress", quest_id)
    for pid, name in item_recipients:
        session.record_item_found(pid, name)
    if outcome is not None:
        session.session_xp_earned += outcome.summary_xp_granted
        for pid, share in outcome.granted_by_player.items():
            session.record_player_metric(pid, "xp_earned", share)

    return response
