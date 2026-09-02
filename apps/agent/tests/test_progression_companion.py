"""Companion progression reaches the DM prompt and L20 XP Resolve."""

import dataclasses
import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sample_fixtures import _WARRIOR_MILESTONES, GUILD_PLAYER, _milestones_mod_for, make_db_mod

from companion_profiles import get_companion_profile, progression_gains_up_to
from progression_tools import _award_xp_core
from session_data import CompanionState
from system_prompts import build_system_prompt


def test_progression_gains_stop_at_the_player_level():
    profile = get_companion_profile("companion_lira")

    at_19 = progression_gains_up_to(profile, 19)
    at_20 = progression_gains_up_to(profile, 20)

    assert [gain.level for gain in at_19] == [5, 8, 10, 15]
    assert [gain.level for gain in at_20] == [5, 8, 10, 15, 20]
    assert at_20[-1].gains == "Legendary: once per session, auto-Counterspell"


def test_companion_prompt_lists_only_gains_reached_by_the_player():
    profile = get_companion_profile("companion_lira")

    prompt_19 = build_system_prompt(
        "accord_guild_hall",
        CompanionState(id=profile.id, name=profile.name, player_level=19),
    )
    prompt_20 = build_system_prompt(
        "accord_guild_hall",
        CompanionState(id=profile.id, name=profile.name, player_level=20),
    )

    assert all(gain.gains in prompt_19 for gain in progression_gains_up_to(profile, 19))
    assert profile.progression[-1].gains not in prompt_19
    assert profile.progression[-1].gains in prompt_20
    assert "once per session; you track it" in prompt_20


async def _award_from_level(level: int, xp: int, amount: int):
    _, conn = make_db_mod()
    mutations = MagicMock()
    mutations.update_player_xp = AsyncMock()
    mutations.set_player_flag = AsyncMock()
    result = await _award_xp_core(
        player_id="player_1",
        player={**GUILD_PLAYER, "class": "warrior", "level": level, "xp": xp},
        amount=amount,
        reason="legend reached",
        conn=conn,
        pending_events=[],
        mutations=mutations,
        milestones_mod=_milestones_mod_for(_WARRIOR_MILESTONES, "warrior"),
    )
    return result


@pytest.mark.asyncio
async def test_l20_resolve_names_the_assigned_companion_gain_once():
    with patch("progression_tools.milestone_tools.apply_milestone_grant", new_callable=AsyncMock) as apply_grant:
        first = await _award_from_level(19, 10250, 1000)

        assert first.milestone_grants == [
            {
                "name": "Lira — Legendary Companion",
                "effect": "Legendary: once per session, auto-Counterspell",
                "narration_cue": "Voice Lira's legendary gain; once per session; you track it.",
            },
            {"name": "Legendary Action", "effect": "Act outside the turn order.", "narration_cue": "cue"},
        ]
        apply_grant.assert_awaited_once()

        apply_grant.reset_mock()
        replay = await _award_from_level(20, 11250, 100)

        assert replay.milestone_grants == []
        apply_grant.assert_not_awaited()


@pytest.mark.asyncio
async def test_l20_resolve_fails_loud_without_the_assigned_companion_gain():
    profile = get_companion_profile("companion_lira")
    broken = dataclasses.replace(profile, progression=profile.progression[:-1])

    with (
        patch("progression_tools.get_companion_profile", return_value=broken),
        pytest.raises(ValueError, match="L20 progression gain"),
    ):
        await _award_from_level(19, 10250, 1000)


def test_archetype_milestone_doc_closes_all_34_criteria():
    text = (Path(__file__).resolve().parents[3] / "docs" / "milestones" / "02_archetypes.md").read_text()

    assert len(re.findall(r"^- \[x\]", text, flags=re.MULTILINE)) == 34
    assert not re.findall(r"^- \[ \]", text, flags=re.MULTILINE)
    assert "34/34 acceptance criteria are now checked" in text
    assert "30/34 acceptance criteria" not in text
    assert 'legendary companion unlock" half is not implemented' not in text
