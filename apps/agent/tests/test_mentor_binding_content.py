"""Mentor requirements apply to all variants; duplicating them per variant risks drift.
The closed mentor set has no runtime binding validation."""

import json
from pathlib import Path

from role_archetypes import DISPOSITIONS as _DISPOSITION_LADDER
from rules_engine import SKILL_TIER_ORDER

_ROOT = Path(__file__).resolve().parents[3]
_CONTENT = _ROOT / "content"


def _load(name: str) -> list[dict]:
    return json.loads((_CONTENT / name).read_text())


def _mentor_ids_from_variants() -> set[str]:
    return {row["mentor_id"] for row in _load("mentor_variants.json")}


def _npcs_by_id() -> dict[str, dict]:
    return {n["id"]: n for n in _load("npcs.json")}


def test_every_variant_mentor_has_a_mentor_binding():
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
        # Must be >= 1: a training loop needs at least one cycle, and learn(variant)'s
        # `training_cycles or <flat default>` fallback treats 0 as unset (would silently
        # substitute the flat default), so 0 is a content bug we catch here at the boundary.
        assert (
            isinstance(block.get("training_cycles"), int)
            and not isinstance(block["training_cycles"], bool)
            and block["training_cycles"] >= 1
        ), f"{mentor_id}: training_cycles must be an int >= 1"
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
        # A non-null skill gate must be the "SkillName: Tier" shape story-002's reader parses
        # (interface contract). A bare "Athletics" would pass the str check above but break the
        # reader — so the guard must enforce the same shape it exists to protect.
        skill = req["skill"]
        if skill is not None:
            name, sep, tier = skill.partition(":")
            assert sep and name.strip() and tier.strip().lower() in SKILL_TIER_ORDER, (
                f"{mentor_id}: skill {skill!r} must be 'SkillName: Tier' with tier in {SKILL_TIER_ORDER}"
            )


def test_only_mentor_npcs_carry_a_mentor_block():
    mentor_ids = _mentor_ids_from_variants()
    for npc in _load("npcs.json"):
        if "mentor" in npc:
            assert npc["id"] in mentor_ids, (
                f"{npc['id']} carries a mentor block but teaches no variants in mentor_variants.json"
            )
