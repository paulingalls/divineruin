"""Tests for learn(kind='variant') initiation — mentor_variant_tools._learn_variant_impl (M9 story-002).

learn(variant, id) does not acquire instantly; it INITIATES a multi-session mentor
training loop: seeds the cycle-progress row at 0 and creates a
technique_mentor_variant training activity. cycles_required (3) comes from the
content config seeded by the autouse conftest fixture.
"""

import json
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from livekit.agents.llm import ToolError
from sample_fixtures import FIXED_NOW, make_context, make_db_mod

from mentor_requirements import MentorRequirementsResult
from mentor_variant_tools import _learn_variant_impl
from training_rules import TrainingCycleInit


def _variant(ability_id="warrior_cleaving_blow", mentor_id="guildmaster_torin"):
    return MagicMock(
        id="warrior_cleaving_blow_drathian",
        ability_id=ability_id,
        mentor_id=mentor_id,
        cultural_attribution="Drathian Clans technique",
    )


def _variants_mod(variant=None):
    mod = MagicMock()
    if variant is None:
        mod.get_mentor_variant = MagicMock(side_effect=ValueError("unknown"))
    else:
        mod.get_mentor_variant = MagicMock(return_value=variant)
    return mod


def _progress_mod(*, unlocked=False):
    mod = MagicMock()
    mod.is_unlocked = AsyncMock(return_value=unlocked)
    mod.seed_progress = AsyncMock()
    return mod


def _abilities_mod(ability_type="elective", name="Cleaving Blow"):
    """Mock abilities module: get_ability returns a base of the given type."""
    mod = MagicMock()
    base = MagicMock(ability_type=ability_type, name=name)
    mod.get_ability = MagicMock(return_value=base)
    return mod


def _persistence_mod(*, owns=True):
    mod = MagicMock()
    mod.owns_elective = AsyncMock(return_value=owns)
    return mod


def _cycle(first_half_seconds=6 * 3600):
    return TrainingCycleInit(
        state="running_first_half",
        first_half_seconds=first_half_seconds,
        decision_at=FIXED_NOW + timedelta(seconds=first_half_seconds),
    )


def _rules_factory(cycle):
    def _stub(_activity_type, _start_time):
        return cycle

    return _stub


def _reqs_mod(*, met=True, unmet=()):
    """story-002 check seam: returns a canned MentorRequirementsResult."""
    mod = MagicMock()
    mod.check_mentor_requirements = AsyncMock(return_value=MentorRequirementsResult(met=met, unmet=list(unmet)))
    return mod


def _preconds_mod(*, present=True):
    """Co-location seam (story-003 reuses require_npc_present): raises ToolError when absent."""
    mod = MagicMock()
    side = None if present else ToolError("mentor isn't here to train this variant.")
    mod.require_npc_present = AsyncMock(side_effect=side)
    return mod


class TestLearnVariant:
    @pytest.mark.asyncio
    async def test_happy_path_seeds_progress_and_creates_activity(self):
        ctx = make_context()
        db_mod, conn = make_db_mod()
        progress = _progress_mod(unlocked=False)
        training = MagicMock()
        training.get_player_training_activities = AsyncMock(return_value=[])
        training.create_training_activity = AsyncMock(return_value="train_var1")
        result = json.loads(
            await _learn_variant_impl(
                ctx,
                "warrior_cleaving_blow_drathian",
                "",
                db_mod=db_mod,
                db_training_mod=training,
                variants_mod=_variants_mod(_variant()),
                progress_mod=progress,
                abilities_mod=_abilities_mod(),
                persistence_mod=_persistence_mod(owns=True),
                requirements_mod=_reqs_mod(),
                preconditions_mod=_preconds_mod(),
                rules_mod=_rules_factory(_cycle(8 * 3600)),
                now_fn=lambda: FIXED_NOW,
            )
        )
        assert result["training_started"] == "warrior_cleaving_blow_drathian"
        assert result["ability_id"] == "warrior_cleaving_blow"
        assert result["mentor_id"] == "guildmaster_torin"
        assert result["cycles_required"] == 3  # technique_mentor_variant config
        assert result["activity_id"] == "train_var1"
        assert result["state"] == "running_first_half"
        ctx.disallow_interruptions.assert_called_once()
        # Progress seeded at 0 before the activity is created.
        progress.seed_progress.assert_awaited_once_with("player_1", "warrior_cleaving_blow_drathian", 3, conn=conn)
        kwargs = training.create_training_activity.await_args.kwargs
        assert kwargs["activity_type"] == "technique_mentor_variant"
        assert kwargs["state"] == "running_first_half"
        assert kwargs["transition_at"] == FIXED_NOW + timedelta(seconds=8 * 3600)
        assert kwargs["conn"] is conn
        assert kwargs["data"]["variant_id"] == "warrior_cleaving_blow_drathian"
        assert kwargs["data"]["ability_id"] == "warrior_cleaving_blow"
        assert kwargs["data"]["mentor_id"] == "guildmaster_torin"

    @pytest.mark.asyncio
    async def test_rejects_when_base_not_owned(self):
        # Own-the-base gate (story-006): you cannot train a variant of a technique
        # you don't own. Rejects without seeding progress or creating an activity.
        ctx = make_context()
        db_mod, _ = make_db_mod()
        progress = _progress_mod(unlocked=False)
        training = MagicMock()
        training.get_player_training_activities = AsyncMock(return_value=[])
        training.create_training_activity = AsyncMock()
        with pytest.raises(ToolError, match="own the base"):
            await _learn_variant_impl(
                ctx,
                "warrior_cleaving_blow_drathian",
                "",
                db_mod=db_mod,
                db_training_mod=training,
                variants_mod=_variants_mod(_variant()),
                progress_mod=progress,
                abilities_mod=_abilities_mod(),
                persistence_mod=_persistence_mod(owns=False),
                requirements_mod=_reqs_mod(),
                preconditions_mod=_preconds_mod(),
                rules_mod=_rules_factory(_cycle()),
                now_fn=lambda: FIXED_NOW,
            )
        progress.seed_progress.assert_not_awaited()
        training.create_training_activity.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_rejects_when_base_ability_not_elective(self):
        # A variant whose base is core/reaction is unmodeled — reject loud rather
        # than train a variant of an always-known ability.
        ctx = make_context()
        db_mod, _ = make_db_mod()
        progress = _progress_mod(unlocked=False)
        training = MagicMock()
        training.get_player_training_activities = AsyncMock(return_value=[])
        training.create_training_activity = AsyncMock()
        with pytest.raises(ToolError, match="elective"):
            await _learn_variant_impl(
                ctx,
                "warrior_cleaving_blow_drathian",
                "",
                db_mod=db_mod,
                db_training_mod=training,
                variants_mod=_variants_mod(_variant()),
                progress_mod=progress,
                abilities_mod=_abilities_mod(ability_type="core"),
                persistence_mod=_persistence_mod(owns=True),
                requirements_mod=_reqs_mod(),
                preconditions_mod=_preconds_mod(),
                rules_mod=_rules_factory(_cycle()),
                now_fn=lambda: FIXED_NOW,
            )
        progress.seed_progress.assert_not_awaited()
        training.create_training_activity.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_non_empty_source_rejected(self):
        # learn(variant) is documented to OMIT source — a variant is acquired via the
        # async mentor loop, not instantly. A non-empty source is rejected (not silently
        # ignored), for parity with learn(recipe)/learn(spell) closed-set validation.
        ctx = make_context()
        with pytest.raises(ToolError, match="no source"):
            await _learn_variant_impl(ctx, "warrior_cleaving_blow_drathian", "discovery")
        ctx.disallow_interruptions.assert_called_once()

    @pytest.mark.asyncio
    async def test_unknown_variant_raises(self):
        ctx = make_context()
        db_mod, _ = make_db_mod()
        training = MagicMock()
        training.create_training_activity = AsyncMock()
        with pytest.raises(ToolError, match="Unknown mentor variant"):
            await _learn_variant_impl(
                ctx,
                "no_such_variant",
                "",
                db_mod=db_mod,
                db_training_mod=training,
                variants_mod=_variants_mod(None),
                progress_mod=_progress_mod(),
                rules_mod=_rules_factory(_cycle()),
                now_fn=lambda: FIXED_NOW,
            )
        training.create_training_activity.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_already_unlocked_raises(self):
        ctx = make_context()
        db_mod, _ = make_db_mod()
        progress = _progress_mod(unlocked=True)
        training = MagicMock()
        training.get_player_training_activities = AsyncMock(return_value=[])
        training.create_training_activity = AsyncMock()
        with pytest.raises(ToolError, match="already unlocked"):
            await _learn_variant_impl(
                ctx,
                "warrior_cleaving_blow_drathian",
                "",
                db_mod=db_mod,
                db_training_mod=training,
                variants_mod=_variants_mod(_variant()),
                progress_mod=progress,
                requirements_mod=_reqs_mod(),
                preconditions_mod=_preconds_mod(),
                rules_mod=_rules_factory(_cycle()),
                now_fn=lambda: FIXED_NOW,
            )
        progress.seed_progress.assert_not_awaited()
        training.create_training_activity.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_training_already_in_progress_raises(self):
        ctx = make_context()
        db_mod, _ = make_db_mod()
        progress = _progress_mod(unlocked=False)
        training = MagicMock()
        training.get_player_training_activities = AsyncMock(
            return_value=[{"id": "train_existing", "state": "running_first_half"}]
        )
        training.create_training_activity = AsyncMock()
        with pytest.raises(ToolError, match="already in progress"):
            await _learn_variant_impl(
                ctx,
                "warrior_cleaving_blow_drathian",
                "",
                db_mod=db_mod,
                db_training_mod=training,
                variants_mod=_variants_mod(_variant()),
                progress_mod=progress,
                requirements_mod=_reqs_mod(),
                preconditions_mod=_preconds_mod(),
                rules_mod=_rules_factory(_cycle()),
                now_fn=lambda: FIXED_NOW,
            )
        progress.seed_progress.assert_not_awaited()
        training.create_training_activity.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_invalid_variant_id_format_raises_before_lookup(self):
        ctx = make_context()
        db_mod, _ = make_db_mod()
        variants = _variants_mod(_variant())
        with pytest.raises(ToolError, match="variant_id"):
            await _learn_variant_impl(
                ctx,
                "bad id!! spaces",
                "",
                db_mod=db_mod,
                db_training_mod=MagicMock(),
                variants_mod=variants,
                progress_mod=_progress_mod(),
                now_fn=lambda: FIXED_NOW,
            )
        variants.get_mentor_variant.assert_not_called()

    @pytest.mark.asyncio
    async def test_rejects_when_mentor_not_co_located(self):
        # Co-location gate (story-003): training can't begin unless the bound mentor is
        # present at the player's location. It runs BEFORE the requirement check — even
        # with requirements unmet, the co-location ToolError wins and the check is skipped.
        ctx = make_context()
        db_mod, _ = make_db_mod()
        progress = _progress_mod(unlocked=False)
        training = MagicMock()
        training.get_player_training_activities = AsyncMock(return_value=[])
        training.create_training_activity = AsyncMock()
        reqs = _reqs_mod(met=False, unmet=["gold: need 50, have 0"])
        with pytest.raises(ToolError, match="isn't here"):
            await _learn_variant_impl(
                ctx,
                "warrior_cleaving_blow_drathian",
                "",
                db_mod=db_mod,
                db_training_mod=training,
                variants_mod=_variants_mod(_variant()),
                progress_mod=progress,
                abilities_mod=_abilities_mod(),
                persistence_mod=_persistence_mod(owns=True),
                requirements_mod=reqs,
                preconditions_mod=_preconds_mod(present=False),
                rules_mod=_rules_factory(_cycle()),
                now_fn=lambda: FIXED_NOW,
            )
        reqs.check_mentor_requirements.assert_not_awaited()  # co-location gates first
        progress.seed_progress.assert_not_awaited()
        training.create_training_activity.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_rejects_when_requirements_unmet(self):
        # Requirement gate (story-003): co-located but the player doesn't meet the mentor's
        # disposition/quest/gold/skill — the specific unmet labels surface in the refusal.
        ctx = make_context()
        db_mod, _ = make_db_mod()
        progress = _progress_mod(unlocked=False)
        training = MagicMock()
        training.get_player_training_activities = AsyncMock(return_value=[])
        training.create_training_activity = AsyncMock()
        with pytest.raises(ToolError, match="gold: need 50"):
            await _learn_variant_impl(
                ctx,
                "warrior_cleaving_blow_drathian",
                "",
                db_mod=db_mod,
                db_training_mod=training,
                variants_mod=_variants_mod(_variant()),
                progress_mod=progress,
                abilities_mod=_abilities_mod(),
                persistence_mod=_persistence_mod(owns=True),
                requirements_mod=_reqs_mod(met=False, unmet=["gold: need 50, have 0"]),
                preconditions_mod=_preconds_mod(present=True),
                rules_mod=_rules_factory(_cycle()),
                now_fn=lambda: FIXED_NOW,
            )
        progress.seed_progress.assert_not_awaited()
        training.create_training_activity.assert_not_awaited()
