"""What a spent reaction DOES to the held blow it answered (M29, story-018).

story-017 made a reaction an interrupt and recorded WHICH ability answered WHICH held action
(``reaction_spend``). It changed nothing else: the player paid the round's one reaction and the
blow landed unaltered — note 0f3945fa(f). game_mechanics_combat.md:187 names the outcomes that
were missing ("Uncanny Dodge halves damage, Shield of Faith causes a miss"); this module is them.

It owns ONE hook: ``close``, called by ``combat_hold.pump`` at the moment it discards the window
the DM just came back from. Everything it needs it derives from the spend record and the held
entry — it adds no state of its own.

Counterspell, the third outcome the spec names, is NOT here and is not faked: its window is
``on_spell_cast`` and no enemy in content casts a spell, so the window has no producer (debt
08bc5548). ``tests/combat/test_reaction_resolution.py`` pins it refused rather than shipping a
guard that certifies nothing.
"""

from __future__ import annotations

import logging
from dataclasses import replace

import reaction_spend
import reaction_windows
from combat_support import deserialize_roll, serialize_roll
from declarations import resolve_declaration

logger = logging.getLogger("divineruin.tools")

# The wired set, transcribed from content/archetype_abilities.json. Explicit ids rather than
# prose-matching on the catalog's ``effect`` text: the rows carry no mechanical field, and adding
# one is a cross-language content change this story does not own. Their honesty against the
# catalog is pinned by test_reaction_resolution's drift guard, not by this comment.
HALVES_DAMAGE = frozenset({"rogue_uncanny_dodge"})


def bound_spend(state, head: dict, stage: str) -> dict | None:
    """The spend record answering THIS held action at THIS stage, with its reactor's id.

    ``held_seq`` is what makes a reaction change only the blow it was spent against; ``stage``
    is what stops a pre-roll spend from firing a second time when the post-roll window closes.
    Matched on the record's own fields rather than on ``window_id`` because ``reaction_spend``
    deliberately refused to make the id's ``r<n>-<seq>-<stage>`` format a contract.

    A legacy bool upgraded by ``reaction_spend.normalize`` carries ``stage: None`` and so matches
    nothing — "spent, no binding" applies no modifier, exactly as that upgrade documents.
    """
    for actor_id, entry in state.reactions_available.items():
        if not reaction_spend.is_spent(entry):
            continue
        if entry["stage"] == stage and entry["held_seq"] == head["seq"]:
            return {"actor_id": actor_id, **entry}
    return None


def _held_target(state, head: dict):
    declaration = resolve_declaration(head["declaration"])
    return state.get_participant(declaration.target_id) if declaration.target_id else None


def halve(head: dict, target) -> None:
    """Rewrite the held roll so the blow deals half its damage. Mutates ``head["roll"]``.

    The HP write is recomputed, not scaled: ``apply_attack_result`` sets ``hp_current`` from the
    roll's ABSOLUTE ``target_hp_remaining`` (combat_support.py:286) and never derives it from
    ``damage``, so halving the damage number alone would leave the player at the unhalved HP.
    ``target.hp_current`` IS the pre-roll HP — the post-roll window is pre-damage by construction.

    Rewriting the SERIALIZED ROLL rather than the summary is what carries the halving to all five
    of its consumers through the untouched trunk path: hp_current, the concentration DC, the
    DICE_ROLL payload, the recorded event line and the packet summary.

    ``bonus_damage`` is halved with it because it is a COMPONENT of ``damage``, not a label
    (check_resolution_attack.py:150 does ``damage += bonus_damage``) and the summary surfaces both
    — a Temporary Hollowed attacker's necrotic die would otherwise be reported as larger than the
    whole blow. The killing-blow context is cleared when the halving saves the target, so the DM is
    never handed a dramatic killing blow for a player who is still standing.
    """
    result, held_ac = deserialize_roll(head["roll"])
    halved = result.damage // 2
    remaining = max(0, target.hp_current - halved)
    fields = {
        "damage": halved,
        "bonus_damage": result.bonus_damage // 2,
        "target_hp_remaining": remaining,
        "overkill": max(0, halved - target.hp_current),
        "target_killed": remaining <= 0,
    }
    if result.context == "killing_blow" and remaining > 0:
        fields["dramatic"] = False
        fields["context"] = ""
    head["roll"] = serialize_roll(replace(result, **fields), held_ac)


def close(state, head: dict, window: dict) -> None:
    """Apply whatever the reaction spent against ``head`` at ``window``'s stage actually does.

    Called by ``combat_hold.pump`` as it discards the window the DM has come back from — the one
    point where the spend is known and the blow has not yet been applied.
    """
    spend = bound_spend(state, head, window["stage"])
    if spend is None:
        return

    if window["stage"] == reaction_windows.POST_ROLL and spend["ability_id"] in HALVES_DAMAGE:
        target = _held_target(state, head)
        # on_hit means the reactor was the one HIT. A reactor guarding someone else is
        # guardian_intercept's shape (on_ally_hit), which is a different, unwired mechanic —
        # halving an ally's damage off an on_hit spend would invent one.
        if target is not None and spend["actor_id"] == target.id and head["roll"] is not None:
            halve(head, target)
            logger.info(
                "reaction %s halved %s's blow against %s",
                spend["ability_id"],
                head["actor_id"],
                target.id,
            )
