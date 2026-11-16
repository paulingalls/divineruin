"""Warm refresh and authored scene hints on the arc command session."""

import json
from collections import Counter
from pathlib import Path
from unittest.mock import AsyncMock, patch

from acceptance.greyvale_arc_walk_harness import QUEST, ArcWalk

import db_content_queries
import db_session_queries
import event_types as E
from background_process import BackgroundProcess
from bg_speech import SpeechPriority
from combat_agent import CombatAgent
from companion_profiles import get_companion_profile
from event_bus import GameEvent
from exploration_agent import ExplorationAgent
from scene_tools import get_active_scene_for_context
from session_data import CompanionState

CONTENT = Path(__file__).resolve().parents[4] / "content" / "quests.json"


def quest_corpus():
    quests = json.loads(CONTENT.read_text())
    assert quests and all(q["stages"] for q in quests)
    assert {s["completion_conditions"]["type"] for q in quests for s in q["stages"]} == {
        "location_reached",
        "knowledge_acquired",
        "combat_completed",
        "item_discovered",
        "npc_interaction",
        "decision_made",
    }
    return quests


class WarmArc(ArcWalk):
    bg: BackgroundProcess


async def start_warm(harness):
    # Entry owns voice and background startup; this harness owns its one background explicitly.
    harness.stack.enter_context(patch.object(ExplorationAgent, "_enter", new=AsyncMock()))
    arc = WarmArc()
    await arc.start(harness, "enter_mode", stage=None, agent=ExplorationAgent())
    arc.sd.companion = CompanionState(id="companion_kael", name="Kael")
    arc.bg = BackgroundProcess(arc.session, arc.sd)

    async def cleanup():
        if arc.sd.combat_state:
            await arc.pool.execute("DELETE FROM combat_instances WHERE combat_id=$1", arc.sd.combat_state.combat_id)
        await arc.pool.execute("DELETE FROM players WHERE player_id=$1", arc.player)

    harness.stack.callback(lambda: harness.run_sync(cleanup()))
    return arc


async def refresh(arc, quest, stage):
    await arc.pool.execute("DELETE FROM player_quests WHERE player_id=$1", arc.player)
    await arc.quest_row(quest, stage)
    await arc.bg._process_events([GameEvent(E.QUEST_UPDATED, {})], timed_out=False)
    return next(line for line in arc.session.current_agent.instructions.splitlines() if "  advance_quest:" in line)


async def scene_hint(arc, stage):
    await refresh(arc, QUEST, stage)
    quest = arc.bg._quest_cache[0]
    scene = get_active_scene_for_context(arc.bg._scene_cache, arc.bg._quest_cache, None)
    expected = next(e["scene_id"] for e in quest["scene_graph"] if stage in e["stage_refs"])
    assert scene is not None and scene["id"] == expected
    beat = scene["beats"][0]
    arc.sd.last_player_speech_time = arc.sd.last_agent_speech_end = 100
    arc.bg._speech_queue.clear()
    with patch("background_process.time.time", return_value=101 + beat["hint_delay_seconds"]):
        arc.bg._check_scene_beat_hints()
    (cue,) = arc.bg._speech_queue
    assert cue.priority == SpeechPriority.IMPORTANT
    assert beat["companion_hints"][0] in cue.instructions
    assert f"[{get_companion_profile(arc.sd.companion.id).voice_id}," in cue.instructions
    payload = await db_session_queries.get_session_init_payload(arc.player)
    (active,) = payload["quests"]
    assert active["hints"] == [hint for b in scene["beats"] for hint in b.get("companion_hints", [])]
    assert active["hints"]


def assert_finish(line, quest, index):
    stage = quest["stages"][index]
    cc = stage["completion_conditions"]
    kind = cc["type"]
    assert stage["objective"] in line
    fields = {
        "location_reached": [cc.get("location")],
        "knowledge_acquired": cc.get("required_info", []) + cc.get("sources", []),
        "combat_completed": [cc.get("encounter"), cc.get("outcome")],
        "item_discovered": [*cc.get("items", []), cc.get("location")],
        "npc_interaction": [cc.get("npc"), cc.get("topic")],
        "decision_made": [cc.get("decision"), *cc.get("options", [])],
    }[kind]
    assert fields and all(value and value in line for value in fields), line
    if kind not in {"location_reached", "combat_completed"}:
        assert f'update_quest(quest_id="{quest["id"]}", new_stage_id={index + 1})' in line
    if kind == "knowledge_acquired":
        assert "once the player has learned" in line
    if kind in {"location_reached", "combat_completed"}:
        assert "update_quest" not in line
    if kind == "location_reached":
        assert "arrival" in line
    if kind == "combat_completed":
        assert f'enter_mode(mode="combat", encounter_id="{cc["encounter"]}")' in line
        assert "when the fight begins" in line


async def enter_surfaced_combat(arc, line):
    encounter = line.split('encounter_id="', 1)[1].split('"', 1)[0]
    arc.sd.location_id = "greyvale_wilderness_north"
    await arc.pool.execute(
        "UPDATE players SET data=jsonb_set(data, '{location_id}', to_jsonb($2::text)) WHERE player_id=$1",
        arc.player,
        arc.sd.location_id,
    )
    assert await refresh(arc, QUEST, 2) == line
    arc.model.commands.append(("enter_mode", {"mode": "combat", "encounter_id": encounter}))
    with arc.sd._bind_authenticated_actor(arc.player, 1, lambda *_: None):
        await arc.session.run(user_input="The fight begins. Execute the command.")
    receipt = list(arc.model.receipts.values())[-1]
    assert receipt.name == "enter_mode" and not receipt.is_error, receipt.output
    assert isinstance(arc.session.current_agent, CombatAgent)
    state = arc.sd.combat_state
    assert state is not None and state.encounter_id == encounter
    saved = json.loads(await arc.pool.fetchval("SELECT data FROM combat_instances WHERE combat_id=$1", state.combat_id))
    assert saved["encounter_id"] == encounter
    template = await db_content_queries.get_encounter_template(encounter)
    assert template is not None
    assert Counter(p.creature_id for p in state.participants if p.type == "enemy") == Counter(
        enemy["creature_id"] for enemy in template["enemies"]
    )
