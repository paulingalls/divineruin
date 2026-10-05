import json
from pathlib import Path

from npcs import get_npc_sync, parse_npc_row
from role_archetypes import get_role_archetype
from tool_support import filter_knowledge
from voices import VOICES

_CONTENT_PATH = Path(__file__).resolve().parents[3] / "content" / "npcs.json"

_CANONICAL_DISPOSITIONS = {"hostile", "unfriendly", "neutral", "friendly", "trusted"}

_DISPOSITION_REMAP = {
    "elder_yanna": ("wary", "unfriendly"),
    "scholar_emris": ("cautious", "unfriendly"),
    "innkeeper_maren": ("wary", "unfriendly"),
    "aldric_hollowed": ("absent", "neutral"),
    "syrath_operative_nyx": ("cautious", "unfriendly"),
    "mentor_thornwarden_elder": ("wary", "unfriendly"),
}


def _rows() -> list[dict]:
    return json.loads(_CONTENT_PATH.read_text())


def _parsed() -> dict[str, dict]:
    return {row["id"]: parse_npc_row(row["id"], row) for row in _rows()}


def test_every_npc_parses_fail_loud():
    parsed = _parsed()
    assert len(parsed) == 17


def test_npc_ids_are_unique():
    rows = _rows()
    ids = [row["id"] for row in rows]
    assert len(ids) == len(set(ids))


def test_every_npc_binds_a_role_archetype():
    for npc_id, npc in _parsed().items():
        assert isinstance(npc.get("role_archetype"), str) and npc["role_archetype"], (
            f"{npc_id} is missing a role_archetype binding"
        )


def test_every_role_archetype_resolves_in_catalog():
    for npc_id, npc in _parsed().items():
        archetype = get_role_archetype(npc["role_archetype"])
        assert archetype.id == npc["role_archetype"], f"{npc_id} -> unknown archetype"


def test_default_disposition_on_canonical_ladder():
    for npc_id, npc in _parsed().items():
        assert npc["default_disposition"] in _CANONICAL_DISPOSITIONS, (
            f"{npc_id} default_disposition {npc['default_disposition']!r} off the canonical ladder"
        )


def test_persona_field_shapes():
    for npc_id, npc in _parsed().items():
        assert isinstance(npc["name"], str) and npc["name"], npc_id
        assert isinstance(npc["speech_style"], str) and npc["speech_style"], npc_id
        assert isinstance(npc["voice_id"], str) and npc["voice_id"], npc_id
        assert isinstance(npc["personality"], list) and npc["personality"], npc_id
        assert all(isinstance(trait, str) for trait in npc["personality"]), npc_id


def test_disposition_remap_preserves_gated_knowledge():
    """AC-4: each reconciled NPC resolves the same knowledge at old vs new disposition.

    Both the old and new tier sit below the friendly gate, so each must resolve to
    exactly the free-only tier — asserted explicitly so the test fails if a future
    remap (or a vocab change in filter_knowledge) lifts an NPC across the gate, rather
    than passing vacuously on old == new.
    """
    parsed = _parsed()
    for npc_id, (old, new) in _DISPOSITION_REMAP.items():
        npc = parsed[npc_id]
        assert npc["default_disposition"] == new, f"{npc_id} not reconciled to {new}"
        knowledge = npc["knowledge"]
        free_only = filter_knowledge(knowledge, "hostile")
        assert filter_knowledge(knowledge, old) == free_only, (
            f"{npc_id}: old disposition {old!r} unexpectedly above the free tier"
        )
        assert filter_knowledge(knowledge, new) == free_only, (
            f"{npc_id}: disposition remap {old}->{new} changed gated knowledge"
        )


def test_filter_knowledge_monotonic_per_npc():
    for npc_id, npc in _parsed().items():
        knowledge = npc["knowledge"]
        free = set(filter_knowledge(knowledge, "hostile"))
        friendly = set(filter_knowledge(knowledge, "friendly"))
        trusted = set(filter_knowledge(knowledge, "trusted"))
        assert set(knowledge.get("free", [])) <= free, f"{npc_id} free entries missing"
        assert free <= friendly <= trusted, f"{npc_id} knowledge not monotonic by disposition"


def test_get_npc_sync_resolves_seeded_catalog():
    for npc_id in _parsed():
        assert get_npc_sync(npc_id) is not None, f"{npc_id} not in the seeded NPC catalog"
    assert get_npc_sync("does_not_exist") is None


def test_every_voice_id_registered_in_voices():
    """Every NPC voice_id must be a key in voices.VOICES (audio-first golden rule).

    get_voice_config does VOICES.get(character, DEFAULT_VOICE), so an unregistered
    voice_id silently falls back to DM_NARRATOR. The shim consolidation derives an
    NPC's voice from this record, so a gap here mutes the character. story-004
    reconciled npcs.json voice_ids to the SCREAMING_CASE runtime keys and registers
    the previously-missing ones in voices.py.
    """
    for npc_id, npc in _parsed().items():
        assert npc["voice_id"] in VOICES, (
            f"{npc_id} voice_id {npc['voice_id']!r} not in voices.VOICES -> would fall back to DM_NARRATOR"
        )
