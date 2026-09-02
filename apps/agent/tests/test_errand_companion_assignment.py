"""The errand path runs the companion the player's archetype assigns.

Nothing writes players.data["companion"], so every errand used to resolve, narrate and
score against `{}` — Kael's name, Kael's voice and no affinity write at all, for all
eighteen archetypes. These pin the derivation (errand_resolution.companion_errand_data)
and both consumers of it: the async worker and the resolve tool.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from claim_stack_helpers import patch_claim_stack
from livekit.agents.llm import ToolError
from sample_fixtures import make_context, make_db_mod
from worker_suite._samples import SAMPLE_ACTIVITY, SAMPLE_PLAYER

from activity_templates import build_narration_prompt, get_companion_context
from async_worker import _resolve_single_activity
from companion_profiles import get_companion_profile
from dialogue_parser import Segment
from errand_resolution import companion_errand_data, resolve_errand_outcome
from errand_tools import _resolve_companion_errand_impl

pytestmark = pytest.mark.usefixtures("stub_companion_errand_affinity_io")

# One archetype per companion, spanning all four assignments (companions.json complements).
ASSIGNMENTS = [
    ("mage", "companion_kael", "Kael"),
    ("warrior", "companion_lira", "Lira"),
    ("cleric", "companion_tam", "Tam"),
    ("spy", "companion_sable", "Sable"),
]

_ERRAND_PARAMS = {"errand_type": "scout", "destination": "millhaven", "dc": 12}


class TestCompanionErrandData:
    @pytest.mark.parametrize("archetype,companion_id,name", ASSIGNMENTS)
    def test_each_archetype_gets_its_own_companion(self, archetype, companion_id, name):
        data = companion_errand_data({"class": archetype})

        assert data["id"] == companion_id
        assert data["name"] == name
        # The attributes ARE the errand check: a shared default would make every companion
        # roll the same scout/social/acquire bonus.
        assert data["attributes"] == get_companion_profile(companion_id).base_attributes

    def test_classless_player_fails_loud(self):
        with pytest.raises(ValueError, match="no class"):
            companion_errand_data({"name": "Aldric"})

    def test_unassignable_archetype_fails_loud(self):
        with pytest.raises(ValueError, match="necromancer"):
            companion_errand_data({"class": "necromancer"})


class TestWorkerPath:
    @pytest.mark.asyncio
    async def test_worker_scores_affinity_against_the_assigned_companion(self):
        """The nudge used to be skipped outright (its `if companion_id` guard never held), so
        no errand has ever moved companion_relationships.affinity."""
        errand = {**SAMPLE_ACTIVITY, "activity_type": "companion_errand", "parameters": _ERRAND_PARAMS}
        _conn, txn_p, get_p, claim_p, revert_p = patch_claim_stack(errand)

        with (
            txn_p,
            get_p,
            claim_p,
            revert_p,
            patch("async_worker.db_queries.get_player", new_callable=AsyncMock, return_value=SAMPLE_PLAYER),
            patch(
                "errand_resolution.db_content_queries.get_location",
                new_callable=AsyncMock,
                return_value={"danger_level": 0},
            ),
            patch(
                "async_worker.generate_activity_narration",
                new_callable=AsyncMock,
                return_value=([Segment("DM_NARRATOR", "neutral", "x")], "x", "x"),
            ),
            patch("async_worker.synthesize_segments", new_callable=AsyncMock, return_value="a.mp3"),
            patch("async_worker.db_mutations.update_activity", new_callable=AsyncMock) as update,
            patch("async_worker.mark_resolved", new_callable=AsyncMock),
            patch("async_worker.generate_notification_hook", new_callable=AsyncMock, return_value="x"),
            patch("async_worker.send_push_notification", new_callable=AsyncMock),
            patch(
                "companion_relationship_queries.apply_errand_affinity",
                new_callable=AsyncMock,
                return_value=0,
            ) as affinity,
        ):
            await _resolve_single_activity(errand)

        # SAMPLE_PLAYER is a warrior; Lira is the warrior's companion.
        affinity.assert_awaited_once()
        nudge = affinity.await_args
        assert nudge is not None and nudge.args[:2] == ("player_1", "companion_lira")
        cached = update.call_args_list[0][0][1]["outcome"]["narrative_context"]
        assert cached["companion_id"] == "companion_lira"
        assert cached["companion_name"] == "Lira"


class TestToolPath:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("archetype,companion_id,name", ASSIGNMENTS)
    async def test_resolve_narrates_and_scores_the_assigned_companion(self, archetype, companion_id, name):
        activity_mod = MagicMock()
        activity_mod.get_activity = AsyncMock(
            return_value={
                "id": "activity_err123",
                "player_id": "player_1",
                "activity_type": "companion_errand",
                "status": "in_progress",
                "resolve_at": None,
                "outcome": None,
                "parameters": _ERRAND_PARAMS,
            }
        )
        queries_mod = MagicMock()
        queries_mod.get_player = AsyncMock(return_value={"player_id": "player_1", "class": archetype})
        mutations_mod = MagicMock()
        mutations_mod.update_activity = AsyncMock()

        with (
            patch(
                "errand_resolution.db_content_queries.get_location",
                new_callable=AsyncMock,
                return_value={"danger_level": 0},
            ),
            patch(
                "companion_relationship_queries.apply_errand_affinity",
                new_callable=AsyncMock,
                return_value=0,
            ) as affinity,
        ):
            outcome = json.loads(
                await _resolve_companion_errand_impl(
                    make_context(),
                    "activity_err123",
                    db_mod=make_db_mod()[0],
                    activity_mod=activity_mod,
                    queries_mod=queries_mod,
                    mutations_mod=mutations_mod,
                    # The REAL resolver: a stub here would only prove the tool passes a dict along.
                    resolve_fn=resolve_errand_outcome,
                )
            )

        assert outcome["narrative_context"]["companion_id"] == companion_id
        assert outcome["narrative_context"]["companion_name"] == name
        nudge = affinity.await_args
        assert nudge is not None and nudge.args[:2] == ("player_1", companion_id)

    @pytest.mark.asyncio
    async def test_unassignable_archetype_surfaces_as_a_toolerror(self):
        activity_mod = MagicMock()
        activity_mod.get_activity = AsyncMock(
            return_value={
                "id": "activity_err123",
                "player_id": "player_1",
                "activity_type": "companion_errand",
                "status": "in_progress",
                "resolve_at": None,
                "outcome": None,
                "parameters": _ERRAND_PARAMS,
            }
        )
        queries_mod = MagicMock()
        queries_mod.get_player = AsyncMock(return_value={"player_id": "player_1", "class": "necromancer"})
        mutations_mod = MagicMock()
        mutations_mod.update_activity = AsyncMock()

        with pytest.raises(ToolError, match="necromancer"):
            await _resolve_companion_errand_impl(
                make_context(),
                "activity_err123",
                db_mod=make_db_mod()[0],
                activity_mod=activity_mod,
                queries_mod=queries_mod,
                mutations_mod=mutations_mod,
                resolve_fn=resolve_errand_outcome,
            )
        mutations_mod.update_activity.assert_not_awaited()


class TestNarrationVoice:
    @pytest.mark.parametrize("archetype,companion_id,name", ASSIGNMENTS)
    def test_narration_prompt_voices_the_assigned_companion(self, archetype, companion_id, name):
        outcome = {
            "narrative_context": {
                "companion_id": companion_id,
                "companion_name": name,
                "errand_type": "scout",
                "destination": "millhaven",
                "tier": "success",
            },
            "information_gained": ["The road is clear."],
            "decision_options": [{"id": "thank", "label": "Thank them"}],
        }

        prompt, voice_ids = build_narration_prompt("companion_errand", outcome)

        assert name in prompt
        if get_companion_profile(companion_id).non_verbal:
            # A registered voice id is exactly why this needs saying: handed to the narration
            # tool's character enum, TTS would speak a companion whose design is silence.
            assert voice_ids == []
            assert "COMPANION_SABLE" not in prompt
            assert "non-verbal" in prompt
        else:
            assert voice_ids == [get_companion_context(companion_id)["voice_id"]]
        for other_id, other_name in ((c, n) for _a, c, n in ASSIGNMENTS if c != companion_id):
            assert other_name not in prompt
            assert other_id.upper() not in prompt

    def test_unknown_companion_never_falls_back_to_kael(self):
        with pytest.raises(ValueError, match="companion_ghost"):
            get_companion_context("companion_ghost")
