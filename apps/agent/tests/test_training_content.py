"""Tests for training content JSON files (content/training_*.json).

Verifies the authored content files exist with the expected schema and values,
matching training_rules.TRAINING_ACTIVITY_CONFIG exactly. The seeding script
copies these files into the training_activity_types and training_programs tables.
"""

import json
from pathlib import Path

CONTENT_DIR = Path(__file__).resolve().parents[3] / "content"

EXPECTED_ACTIVITY_TYPES = {
    "spell_cantrip",
    "spell_minor",
    "spell_standard",
    "spell_major",
    "spell_supreme",
    "recipe_study",
    "technique_base",
    "technique_mentor",
    "technique_mentor_variant",
    "skill_practice",
}

EXPECTED_PROGRAMS = {
    "combat_basics",
    "endurance_training",
    "arcane_study",
    "perception_drills",
}


def _load_json(filename: str) -> list[dict]:
    path = CONTENT_DIR / filename
    assert path.exists(), f"{filename} not found at {path}"
    with path.open() as f:
        return json.load(f)


class TestTrainingActivityTypesContent:
    def test_all_activity_type_ids_present(self):
        data = _load_json("training_activity_types.json")
        ids = {entry["id"] for entry in data}
        assert ids == EXPECTED_ACTIVITY_TYPES

    def test_each_entry_has_duration_ranges(self):
        data = _load_json("training_activity_types.json")
        for entry in data:
            assert "first_half_min_seconds" in entry
            assert "first_half_max_seconds" in entry
            assert "second_half_min_seconds" in entry
            assert "second_half_max_seconds" in entry
            assert entry["first_half_min_seconds"] > 0
            assert entry["first_half_max_seconds"] >= entry["first_half_min_seconds"]
            assert entry["second_half_min_seconds"] > 0
            assert entry["second_half_max_seconds"] >= entry["second_half_min_seconds"]

    def test_each_entry_has_midpoint_decision_with_two_options(self):
        data = _load_json("training_activity_types.json")
        for entry in data:
            decision = entry["midpoint_decision"]
            assert "prompt" in decision
            assert isinstance(decision["prompt"], str)
            assert len(decision["prompt"]) > 10
            options = decision["options"]
            assert len(options) == 2
            for opt in options:
                assert "id" in opt
                assert "label" in opt
                assert "micro_bonus" in opt

    def test_matches_python_training_activity_config(self):
        """Content JSON must match training_rules.TRAINING_ACTIVITY_CONFIG exactly."""
        from training_rules import TRAINING_ACTIVITY_CONFIG

        data = _load_json("training_activity_types.json")
        by_id = {entry["id"]: entry for entry in data}

        for activity_type, cfg in TRAINING_ACTIVITY_CONFIG.items():
            dur, decision = cfg.duration, cfg.decision
            assert activity_type in by_id, f"{activity_type} missing from JSON"
            entry = by_id[activity_type]
            assert entry["first_half_min_seconds"] == dur.first_half_min
            assert entry["first_half_max_seconds"] == dur.first_half_max
            assert entry["second_half_min_seconds"] == dur.second_half_min
            assert entry["second_half_max_seconds"] == dur.second_half_max
            assert entry["midpoint_decision"]["prompt"] == decision.prompt
            json_option_ids = [o["id"] for o in entry["midpoint_decision"]["options"]]
            py_option_ids = [o.id for o in decision.options]
            assert json_option_ids == py_option_ids


class TestTrainingProgramsContent:
    def test_all_four_program_ids_present(self):
        data = _load_json("training_programs.json")
        ids = {entry["id"] for entry in data}
        assert ids == EXPECTED_PROGRAMS

    def test_each_program_references_valid_activity_type(self):
        activity_types = _load_json("training_activity_types.json")
        known_types = {e["id"] for e in activity_types}

        programs = _load_json("training_programs.json")
        for prog in programs:
            assert prog["training_activity_type"] in known_types, (
                f"Program {prog['id']} references unknown activity type {prog['training_activity_type']}"
            )

    def test_each_program_has_required_fields(self):
        data = _load_json("training_programs.json")
        for entry in data:
            assert "id" in entry
            assert "name" in entry
            assert "training_activity_type" in entry
            assert "stat" in entry
            assert "dc" in entry
            assert "mentor_id" in entry
