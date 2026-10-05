from activity_templates import build_narration_prompt
from async_worker_training import build_training_completion_outcome
from training_rules import CompletionResult


def _variant_outcome(cultural_attribution: str | None = "Drathian Clans technique") -> dict:
    return {
        "narrative_context": {
            "mentor_id": "guildmaster_torin",
            "training_stat": "unknown",
            "training_skill": None,
            "tier": "breakthrough",
            "dc": 12,
            "cultural_attribution": cultural_attribution,
        },
        "stat_gains": {"counter_increment": 0, "micro_bonus": None, "skill_advanced": False, "new_tier": None},
        "decision_options": [],
    }


class TestCulturalAttributionInNarration:
    def test_variant_completion_prompt_includes_cultural_attribution(self):
        prompt, _voices = build_narration_prompt("training_completion", _variant_outcome())
        assert "Drathian Clans technique" in prompt

    def test_plain_training_has_no_cultural_line_or_placeholder(self):
        prompt, _voices = build_narration_prompt("training_completion", _variant_outcome(cultural_attribution=None))
        assert "cultural" not in prompt.lower()
        assert "{cultural_attribution_line}" not in prompt

    def test_in_progress_training_prompt_also_carries_attribution(self):
        outcome = _variant_outcome()
        outcome["narrative_context"]["roll"] = 14
        prompt, _voices = build_narration_prompt("training", outcome)
        assert "Drathian Clans technique" in prompt


class TestReplacementNotice:
    def test_completion_prompt_notes_the_replaced_variant(self):
        outcome = _variant_outcome()
        outcome["narrative_context"]["replaced_cultural_attribution"] = "Keldaran Holds technique"
        prompt, _voices = build_narration_prompt("training_completion", outcome)
        assert "Keldaran Holds technique" in prompt
        assert "supplant" in prompt.lower()

    def test_no_replacement_line_when_no_prior_variant(self):
        prompt, _voices = build_narration_prompt("training_completion", _variant_outcome())
        assert "supplant" not in prompt.lower()
        assert "{replacement_line}" not in prompt


class TestOutcomeCarriesCulturalAttribution:
    def test_variant_training_data_propagates_attribution(self):
        completion = CompletionResult(state="complete", counter_increment=0, micro_bonus={})
        data = {
            "variant_id": "warrior_cleaving_blow_drathian",
            "ability_id": "warrior_cleaving_blow",
            "mentor_id": "guildmaster_torin",
            "cultural_attribution": "Drathian Clans technique",
        }
        outcome = build_training_completion_outcome(completion, data, None)
        assert outcome["narrative_context"]["cultural_attribution"] == "Drathian Clans technique"

    def test_skill_training_has_no_attribution(self):
        completion = CompletionResult(state="complete", counter_increment=2, micro_bonus={})
        data = {"mentor_id": "guildmaster_torin", "stat": "wisdom", "skill": "perception"}
        outcome = build_training_completion_outcome(completion, data, None)
        assert outcome["narrative_context"]["cultural_attribution"] is None

    def test_replaced_attribution_propagates_when_present(self):
        completion = CompletionResult(state="complete", counter_increment=0, micro_bonus={})
        data = {
            "variant_id": "warrior_cleaving_blow_drathian",
            "ability_id": "warrior_cleaving_blow",
            "mentor_id": "guildmaster_torin",
            "cultural_attribution": "Drathian Clans technique",
            "replaced_cultural_attribution": "Keldaran Holds technique",
        }
        outcome = build_training_completion_outcome(completion, data, None)
        assert outcome["narrative_context"]["replaced_cultural_attribution"] == "Keldaran Holds technique"

    def test_replaced_attribution_is_none_without_replacement(self):
        completion = CompletionResult(state="complete", counter_increment=0, micro_bonus={})
        data = {"variant_id": "v", "ability_id": "a", "cultural_attribution": "Drathian Clans technique"}
        outcome = build_training_completion_outcome(completion, data, None)
        assert outcome["narrative_context"]["replaced_cultural_attribution"] is None
