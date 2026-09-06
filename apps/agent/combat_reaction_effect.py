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
08bc5548). ``tests/combat/test_reaction_catalog_reach.py`` pins it refused at every window the
engine can open, rather than shipping a guard that certifies nothing.
"""

from __future__ import annotations

import logging
from dataclasses import replace

import abilities
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
SHIELD_BEARING = frozenset({"guardian_retaliating_shield"})
AC_BONUS = {
    "cleric_shield_of_faith": 2,
    "oracle_shield_of_faith": 2,
    "paladin_shield_of_faith": 2,
    "marshal_interceding_order": 2,
}


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


def ac_bonus(state, head: dict) -> int:
    """The AC the pre-roll spend adds to whoever this held blow is aimed at.

    Derived from the one spend record on every call rather than cached onto the held entry — this
    story adds no state of its own. It is asked TWICE per held attack, once by the roll and once by
    the apply half, because ``_replay_resolver`` raises unless both halves compute the same
    effective AC: a bonus in the roll alone would report a target_ac the roll was never made
    against, and the DM would narrate a lie.

    Applied to the blow's TARGET, whoever reacted. That is the person the open window named, and
    the +2 is a property of the attack being answered, not of the reactor.
    """
    spend = bound_spend(state, head, reaction_windows.PRE_ROLL)
    if spend is None:
        return 0
    return AC_BONUS.get(spend["ability_id"], 0)


def shield_reaction(state, head: dict) -> str | None:
    """The post-roll spend that puts a shield in the blow's way, if the reactor is the one hit.

    A shield hit is accrued off the TARGET's inventory (combat_support reads
    ``get_player_inventory(target.id)``), so a reactor who is not the target has no gear in that
    call — reporting one would wear the wrong player's shield.
    """
    spend = bound_spend(state, head, reaction_windows.POST_ROLL)
    if spend is None or spend["ability_id"] not in SHIELD_BEARING:
        return None
    target = _held_target(state, head)
    return spend["ability_id"] if target is not None and spend["actor_id"] == target.id else None


def record_shield_wear(packet: dict | None, summary: dict) -> None:
    """Name the shield's wear on the reaction packet, once the resolved blow reports it happened.

    Not decided at window close: the accrual needs the player's INVENTORY, which only
    ``apply_attack_result`` reads (an async query), so "a shield reaction was spent" is not yet "a
    shield took the hit" — a guardian with nothing equipped accrues nothing. Reading it back off
    the resolved summary keeps ``mechanical_effect`` a statement of what happened rather than of
    what was attempted.
    """
    if packet is not None and packet["mechanical_effect"] is None and "shield" in (summary.get("durability") or {}):
        packet["mechanical_effect"] = "shield_durability"


def _held_target(state, head: dict):
    declaration = resolve_declaration(head["declaration"])
    return state.get_participant(declaration.target_id) if declaration.target_id else None


def halve(head: dict, target) -> None:
    """Rewrite the held roll so the blow deals half its damage. Mutates ``head["roll"]``.

    ``damage`` is the load-bearing field: ``apply_attack_result`` derives ``hp_current`` from the
    target's LIVE HP minus this number, so halving it is what halves the blow. The absolute
    ``target_hp_remaining``/``overkill``/``target_killed`` are rewritten alongside it to keep the
    serialized roll internally coherent across a persist/reload, not because the apply half reads
    them — it stopped, so that a pause that moves the target's HP is not undone at impact.

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


def _apply(state, head: dict, window: dict, spend: dict, attack_action: dict | None) -> str | None:
    """Do what this reaction does to the held blow, and name it — or None if it did nothing.

    The label is what the close ACTUALLY did, never a lookup on the ability id: a shield of faith
    spent at the pre-roll window of an ``applies_condition`` action (Hollow Shriek resolves through
    the save-gated path, with no attack roll) modified no AC, and reporting one would tell the DM
    a blow was turned aside that was never rolled.
    """
    ability_id = spend["ability_id"]
    target = _held_target(state, head)

    if window["stage"] == reaction_windows.PRE_ROLL:
        if ability_id in AC_BONUS and attack_action is not None:
            return "target_ac_bonus"
        return None

    # on_hit means the reactor was the one HIT. A reactor guarding someone else is
    # guardian_intercept's shape (on_ally_hit), a different and unwired mechanic — halving an
    # ally's damage off an on_hit spend would invent one.
    if (
        ability_id in HALVES_DAMAGE
        and head["roll"] is not None
        and target is not None
        and spend["actor_id"] == target.id
    ):
        halve(head, target)
        logger.info("reaction %s halved %s's blow against %s", ability_id, head["actor_id"], target.id)
        return "damage_halved"
    return None


def close(state, head: dict, window: dict, *, attack_action: dict | None) -> dict | None:
    """Apply what the reaction spent at ``window`` does to ``head``, and report it to the DM.

    Called by ``combat_hold.pump`` as it discards the window the DM has come back from — the one
    moment where the spend is known and the blow has not yet been applied.

    The packet is SYNTHESIZED here rather than read from a declaration: story-017 retired
    ``DeclarationType.REACTION``, so a reaction produces no declaration packet at all. ``resolved``
    is kept for shape parity with every other packet and carries no claim — ``mechanical_effect``
    is the load-bearing field, which is note 0f3945fa(f) answered ("resolved: true meant only that
    the resource was spent").

    ``attack_action`` is the pump's own verdict on whether this held action swings an attack roll,
    passed in rather than re-derived: the predicate belongs to combat_hold, which imports this
    module.
    """
    spend = bound_spend(state, head, window["stage"])
    if spend is None:
        return None

    effect = _apply(state, head, window, spend, attack_action)
    ability = abilities.get_ability(spend["ability_id"])
    return {
        "actor_id": spend["actor_id"],
        "resolved": True,
        "declaration_type": "reaction",
        "ability_id": ability.id,
        "ability_name": ability.name,
        "narration_cue": ability.narration_cue,
        "window_id": spend["window_id"],
        "stage": window["stage"],
        "against_actor_id": head["actor_id"],
        "mechanical_effect": effect,
    }
