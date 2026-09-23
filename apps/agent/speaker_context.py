"""Small background-refreshed speaker snapshot for uncached turn messages."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sanitize import sanitize_for_prompt
from warm_prompts import quest_objective

if TYPE_CHECKING:
    from session_data import SessionData


@dataclass(frozen=True)
class SpeakerSummary:
    player_id: str
    name: str
    hp: str
    quest: str
    activity: str

    def render(self, hp: str | None = None) -> str:
        return (
            f"[Speaker: {self.name} (player {self.player_id}); HP {self.hp if hp is None else hp}; "
            f"quest step: {self.quest}; activity: {self.activity}]"
        )


def build_speaker_context(
    speaker_id: str, player: dict, quests: list[dict], activities: list[dict], training: list[dict]
) -> SpeakerSummary:
    name = sanitize_for_prompt(player["name"], max_len=100)
    hp = player["hp"]
    quest = next(
        (
            f"{q['quest_name']}: {quest_objective(q)}"
            for q in sorted(quests, key=lambda q: q.get("quest_id", ""))
            if quest_objective(q)
        ),
        "none",
    )
    activity = "none"
    if activities:
        activity = activities[0].get("activity_type", "activity")
    elif training:
        activity = training[0].get("data", {}).get("program_name") or training[0]["activity_type"]
    return SpeakerSummary(
        speaker_id,
        name,
        f"{hp['current']}/{hp['max']}",
        sanitize_for_prompt(quest, max_len=160),
        sanitize_for_prompt(activity, max_len=80),
    )


def speaker_line(sd: SessionData, *, combat: bool = False) -> str:
    speaker_id = sd.acting_player_id
    summary = sd.speaker_summaries.get(speaker_id)
    if summary is None:
        return f"[Speaker: player {speaker_id}]"
    if combat and sd.combat_state is not None:
        participant = sd.combat_state.get_participant(speaker_id)
        if participant is not None:
            return summary.render(hp=f"{participant.hp_current}/{participant.hp_max}")
    return summary.render()
