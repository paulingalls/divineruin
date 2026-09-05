"""The world-effect disposition target vocabulary, shared by the runtime and the validators.

One symbol, not three: story-013 found this map copied into tool_support.py, scripts/
seed_content.py and tests/test_content_validation.py, each carrying its own
`"companion": "companion_kael"` entry, so replacing the literal meant a lockstep edit of
three definitions of the same thing.

Deliberately a leaf: no livekit import, so scripts/seed_content.py can import it directly.
"""

# Authored shorthands for the recurring NPCs, resolved to their real ids.
EFFECT_NPC_MAP: dict[str, str] = {
    "torin": "guildmaster_torin",
    "yanna": "elder_yanna",
    "emris": "scholar_emris",
}

# Resolved per-player at runtime (the session's assigned companion), not through the map above.
COMPANION_SHORTHAND = "companion"


def is_valid_disposition_target(shorthand: str, npc_ids: set[str], companion_ids: set[str]) -> bool:
    """Authoring-time check for a `<shorthand>_disposition <delta>` world effect.

    `companion` names whichever companion the player was assigned, so at authoring time it is
    not resolvable to an id at all: it is valid iff any companion exists. Set membership, not
    identity.
    """
    if shorthand == COMPANION_SHORTHAND:
        return bool(companion_ids)
    return EFFECT_NPC_MAP.get(shorthand, shorthand) in (npc_ids | companion_ids)
