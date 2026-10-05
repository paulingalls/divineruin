import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from livekit.agents.llm import ToolError

import event_types as E
from check_tools import _check_dice_impl, _check_impl, _check_save_impl, _check_skill_impl
from tools._helpers import SAMPLE_PLAYER, _make_context, _make_mock_room, _save_mocks, _skill_mocks


def _corrupt_conditions_queries():
    """queries whose player carries a corrupt stored conditions row (unknown type)."""
    queries = MagicMock()
    queries.get_player = AsyncMock(return_value={**SAMPLE_PLAYER, "conditions": [{"type": "bogus"}]})
    queries.get_single_skill_advancement = AsyncMock(
        return_value={"tier": "untrained", "use_counter": 0, "narrative_moment_ready": False},
    )
    return queries


class TestCheckSkill:
    @pytest.mark.asyncio
    async def test_returns_result(self):
        queries, mutations = _skill_mocks()
        result = json.loads(
            await _check_skill_impl(
                _make_context(), "athletics", "moderate", "climbing a wall", queries=queries, mutations=mutations
            )
        )
        assert result["skill"] == "athletics"
        assert result["dc"] == 12  # moderate = 12
        assert result["outcome"] in ("success", "failure")
        assert "narrative_hint" in result

    @pytest.mark.asyncio
    async def test_unknown_skill(self):
        queries, _ = _skill_mocks()
        with pytest.raises(ToolError):
            await _check_skill_impl(_make_context(), "flying", "moderate", "trying to fly", queries=queries)

    @pytest.mark.asyncio
    async def test_invalid_difficulty(self):
        queries, _ = _skill_mocks()
        with pytest.raises(ToolError):
            await _check_skill_impl(_make_context(), "athletics", "impossible", "climbing", queries=queries)

    @pytest.mark.asyncio
    async def test_missing_player(self):
        queries = MagicMock()
        queries.get_player = AsyncMock(return_value=None)
        with pytest.raises(ToolError):
            await _check_skill_impl(_make_context(), "athletics", "moderate", "climbing", queries=queries)

    @pytest.mark.asyncio
    async def test_corrupt_conditions_fail_loud_as_toolerror(self):
        queries = _corrupt_conditions_queries()
        with pytest.raises(ToolError, match="corrupt stored conditions"):
            await _check_skill_impl(_make_context(), "athletics", "moderate", "climbing", queries=queries)

    @pytest.mark.asyncio
    async def test_publishes_event(self):
        queries, mutations = _skill_mocks()
        room = _make_mock_room()
        await _check_skill_impl(
            _make_context(room=room), "stealth", "hard", "sneaking past guard", queries=queries, mutations=mutations
        )
        room.local_participant.publish_data.assert_called()
        call_data = json.loads(room.local_participant.publish_data.call_args_list[0][0][0])
        assert call_data["type"] == E.DICE_ROLL
        assert call_data["roll_type"] == "skill_check"

    @pytest.mark.asyncio
    async def test_records_skill_use(self):
        queries, mutations = _skill_mocks()
        await _check_skill_impl(
            _make_context(), "athletics", "moderate", "climbing", queries=queries, mutations=mutations
        )
        mutations.update_skill_advancement.assert_awaited_once()
        call_args = mutations.update_skill_advancement.call_args[0]
        assert call_args[0] == "player_1"
        assert call_args[1] == "athletics"


class TestCheckSave:
    @pytest.mark.asyncio
    async def test_returns_result(self):
        queries = _save_mocks()
        result = json.loads(await _check_save_impl(_make_context(), "dexterity", 15, "knocked prone", queries=queries))
        assert result["save_type"] == "dexterity"
        assert result["dc"] == 15
        assert result["outcome"] in ("success", "failure")

    @pytest.mark.asyncio
    async def test_missing_player(self):
        queries = MagicMock()
        queries.get_player = AsyncMock(return_value=None)
        with pytest.raises(ToolError):
            await _check_save_impl(_make_context(), "dexterity", 15, "prone", queries=queries)

    @pytest.mark.asyncio
    async def test_invalid_save_type(self):
        queries = _save_mocks()
        with pytest.raises(ToolError):
            await _check_save_impl(_make_context(), "luck", 15, "cursed", queries=queries)

    @pytest.mark.asyncio
    async def test_corrupt_conditions_fail_loud_as_toolerror(self):
        # M4.4 story-008 (concern 988e3e4f55ea): a corrupt out-of-combat conditions row must surface
        # as a DM-narratable ToolError, not the raw KeyError get_condition_effects would raise.
        queries = _corrupt_conditions_queries()
        with pytest.raises(ToolError, match="corrupt stored conditions"):
            await _check_save_impl(_make_context(), "dexterity", 15, "prone", queries=queries)

    @pytest.mark.asyncio
    async def test_dc_out_of_range(self):
        queries = _save_mocks()
        with pytest.raises(ToolError, match="DC"):
            await _check_save_impl(_make_context(), "dexterity", 0, "prone", queries=queries)

    @pytest.mark.asyncio
    async def test_publishes_event(self):
        queries = _save_mocks()
        room = _make_mock_room()
        await _check_save_impl(_make_context(room=room), "wisdom", 12, "frightened", queries=queries)
        room.local_participant.publish_data.assert_called_once()
        call_data = json.loads(room.local_participant.publish_data.call_args[0][0])
        assert call_data["type"] == E.DICE_ROLL
        assert call_data["roll_type"] == "saving_throw"


class TestCheckDice:
    @pytest.mark.asyncio
    async def test_valid_notation(self):
        result = json.loads(await _check_dice_impl(_make_context(), "2d6"))
        assert "rolls" in result
        assert "total" in result
        assert len(result["rolls"]) == 2

    @pytest.mark.asyncio
    async def test_invalid_notation(self):
        with pytest.raises(ToolError):
            await _check_dice_impl(_make_context(), "banana")

    @pytest.mark.asyncio
    async def test_publishes_event(self):
        room = _make_mock_room()
        await _check_dice_impl(_make_context(room=room), "d20")
        room.local_participant.publish_data.assert_called_once()
        call_data = json.loads(room.local_participant.publish_data.call_args[0][0])
        assert call_data["roll_type"] == "narrative"


class TestCheckDispatch:
    @pytest.mark.asyncio
    async def test_unknown_mode_raises(self):
        with pytest.raises(ToolError, match="mode"):
            await _check_impl(_make_context(), "telepathy")

    @pytest.mark.asyncio
    async def test_skill_mode_routes_to_skill_impl(self):
        queries, mutations = _skill_mocks()
        result = json.loads(
            await _check_impl(
                _make_context(),
                "skill",
                skill="athletics",
                difficulty="moderate",
                context_description="climbing",
                queries=queries,
                skill_mutations=mutations,
            )
        )
        assert result["skill"] == "athletics"
        assert result["dc"] == 12


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "skill,disadvantage",
    [("perception", True), ("insight", True), ("investigation", True), ("arcana", False), ("athletics", False)],
)
@pytest.mark.parametrize("scene", ["active", "elsewhere", "destroyed"])
async def test_choir_scene_real_checks_use_disadvantage(skill, disadvantage, scene):
    from unittest.mock import patch

    from acceptance._capstone_helpers import _d20

    import choir_scene

    ctx = _make_context()
    queries, mutations = _skill_mocks()
    source = {
        "source_id": choir_scene.key(ctx.userdata.location_id),
        "location_id": ctx.userdata.location_id,
        "status": "dormant",
        "phase": "search",
        "round": 1,
        "owner": {
            "id": "choir_zone",
            "name": "The Choir",
            "creature_id": "hollow_choir",
            "type": "enemy",
            "initiative": 0,
            "hp_current": 200,
            "hp_max": 200,
            "ac": 18,
        },
    }
    if scene == "elsewhere":
        ctx.userdata.location_id = "other_scene"
    elif scene == "destroyed":
        source = {key: value for key, value in source.items() if key in {"source_id", "location_id", "status"}}
        source["status"] = "destroyed"
    disadvantage = disadvantage and scene == "active"
    queries.get_player.return_value = {**SAMPLE_PLAYER, "flags": {source["source_id"]: json.dumps(source)}}
    with patch("check_resolution.dice_roll", side_effect=[_d20(17), _d20(3)]) as rolls:
        raw = await _check_skill_impl(ctx, skill, "moderate", "wrong voices", queries=queries, mutations=mutations)
    assert json.loads(raw)["roll"] == (3 if disadvantage else 17)
    assert rolls.call_count == (2 if disadvantage else 1)
