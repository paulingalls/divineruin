"""Conformance for content/npcs.json mentor{} bindings (sprint-011 / story-001).

Every mentor referenced by content/mentor_variants.json must carry a mentor-level
training-requirements block on its NPC row. Per decision mentor-binding-shape, the
binding is a single mentor{} object whose requirements gate *all* of that mentor's
variants (DRY against mentor_variants.json, which keeps effect/narration/culture).
Drives the real content so a missing or malformed binding fails loud in CI — there is
no runtime loader validation for the closed mentor set (story-001 plan).
"""

import json
from pathlib import Path

from role_archetypes import DISPOSITIONS as _DISPOSITION_LADDER

_ROOT = Path(__file__).resolve().parents[3]
_CONTENT = _ROOT / "content"


def _load(name: str) -> list[dict]:
    return json.loads((_CONTENT / name).read_text())


def _mentor_ids_from_variants() -> set[str]:
    return {row["mentor_id"] for row in _load("mentor_variants.json")}


def _npcs_by_id() -> dict[str, dict]:
    return {n["id"]: n for n in _load("npcs.json")}


def test_every_variant_mentor_has_a_mentor_binding():
    """The referential gap story-001 closes: each of the 4 mentors that teach variants
    must resolve to an NPC carrying a mentor{} training block for story-002 to read."""
    npcs = _npcs_by_id()
    for mentor_id in sorted(_mentor_ids_from_variants()):
        npc = npcs.get(mentor_id)
        assert npc is not None, f"variant mentor {mentor_id} missing from npcs.json"
        assert "mentor" in npc, f"{mentor_id} has no mentor{{}} training-requirements block"


def test_mentor_blocks_conform_to_the_binding_shape():
    npcs = _npcs_by_id()
    for mentor_id in sorted(_mentor_ids_from_variants()):
        block = npcs[mentor_id]["mentor"]
        assert isinstance(block, dict), f"{mentor_id}: mentor block must be a single object"
        assert isinstance(block.get("culture"), str) and block["culture"], (
            f"{mentor_id}: culture must be a non-empty str"
        )
        # bool is an int subclass — exclude it so a stray true/false fails loud.
        assert isinstance(block.get("training_cycles"), int) and not isinstance(block["training_cycles"], bool), (
            f"{mentor_id}: training_cycles must be an int"
        )
        req = block.get("requirements")
        assert isinstance(req, dict), f"{mentor_id}: requirements must be an object"
        assert req.get("disposition") in _DISPOSITION_LADDER, (
            f"{mentor_id}: disposition {req.get('disposition')!r} off the canonical ladder {_DISPOSITION_LADDER}"
        )
        assert isinstance(req.get("gold"), int) and not isinstance(req["gold"], bool) and req["gold"] >= 0, (
            f"{mentor_id}: gold must be a non-negative int"
        )
        for opt in ("quest", "skill"):
            assert opt in req, f"{mentor_id}: requirements missing '{opt}' key"
            assert req[opt] is None or isinstance(req[opt], str), f"{mentor_id}: {opt} must be str|None"


def test_only_mentor_npcs_carry_a_mentor_block():
    """Guards a stray 'mentor' key typo'd onto a non-mentor NPC: every npc with a mentor
    block must actually be referenced as a mentor by the variant catalog."""
    mentor_ids = _mentor_ids_from_variants()
    for npc in _load("npcs.json"):
        if "mentor" in npc:
            assert npc["id"] in mentor_ids, (
                f"{npc['id']} carries a mentor block but teaches no variants in mentor_variants.json"
            )
