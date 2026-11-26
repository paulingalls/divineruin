"""What a spent reaction does to the held blow it answered.

Counterspell, the third outcome game_mechanics_combat.md:187 names, is NOT here and is not faked: its window is
``on_spell_cast`` and no enemy in content casts a spell, so the window has no producer (debt
08bc5548). ``tests/combat/test_reaction_catalog_reach.py`` pins it refused at every window the
engine can open, rather than shipping a guard that certifies nothing.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import cast

import abilities
import ability_voice_rules
import architect_entomb
import combat_grapple
import combat_reaction_contest
import combat_structures
import conditions
import reaction_spend
import reaction_windows
import temp_hp
from check_resolution import D20Roll
from combat_attack_roll import held_reaction_ac
from combat_damage_affinity import with_landed_damage
from combat_participant import BARK_SKIN_AC_BONUS
from combat_support import deserialize_roll, serialize_roll
from declarations import resolve_declaration
from session_data import CombatParticipant

logger = logging.getLogger("divineruin.tools")

# The wired set, transcribed from content/archetype_abilities.json. Explicit ids rather than
# prose-matching on the catalog's ``effect`` text: the rows carry no mechanical field, and adding
# one is a cross-language content change this story does not own. Their honesty against the
# catalog is pinned by test_reaction_resolution's drift guard, not by this comment.
HALVES_DAMAGE = frozenset({"rogue_uncanny_dodge"})
BARK_SKIN = frozenset({"druid_bark_skin", "warden_bark_skin"})
SHIELD_BEARING = frozenset({"guardian_retaliating_shield"})
SLIPPERY_REACTIONS = frozenset({"rogue_slippery", "spy_slippery"})
AC_BONUS = {
    "cleric_shield_of_faith": 2,
    "oracle_shield_of_faith": 2,
    "paladin_shield_of_faith": 2,
    "marshal_interceding_order": 2,
}
SAVE_ADVANTAGE = {
    "bard_countercharm": frozenset({"frightened", "charmed"}),
    "diplomat_countercharm": frozenset({"frightened", "charmed"}),
}


def bound_spends(state, head: dict, stage: str, *, window_id: str | None = None) -> list[dict]:
    """Every spend answering this held action at this stage, with each reactor's id.

    ``held_seq`` is what makes a reaction change only the blow it was spent against; ``stage``
    is what stops a pre-roll spend from firing when the post-roll window closes. Movement can
    open several windows per action, so it also matches the opaque id of the closing window.

    A legacy bool upgraded by ``reaction_spend.normalize`` carries ``stage: None`` and so matches
    nothing — "spent, no binding" applies no modifier, exactly as that upgrade documents.
    """
    return [
        {"actor_id": actor_id, **entry}
        for actor_id, entry in state.reactions_available.items()
        if reaction_spend.is_spent(entry)
        and entry["stage"] == stage
        and entry["held_seq"] == head["seq"]
        and (stage != reaction_windows.MOVEMENT or entry["window_id"] == window_id)
    ]


def intercept_target(state, head: dict) -> CombatParticipant | None:
    spends = [
        spend
        for spend in bound_spends(state, head, reaction_windows.POST_ROLL)
        if reaction_spend.intercepts_damage(spend)
    ]
    if not spends:
        return None
    (spend,) = spends
    target = state.get_participant(spend["actor_id"])
    if target is None:
        raise ValueError(f"Intercept names missing guardian {spend['actor_id']!r}")
    return target


def ac_bonus(state, head: dict) -> int:
    """Use live recipient eligibility until the roll freezes its contribution."""
    if head.get("roll") is not None:
        return held_reaction_ac(head)

    return max(
        (
            AC_BONUS.get(spend["ability_id"], 0)
            for spend in bound_spends(state, head, reaction_windows.PRE_ROLL)
            if ability_voice_rules.reaction_effect_eligible(state, head, spend)
        ),
        default=0,
    )


def save_advantage(state, head: dict, condition: str | None) -> bool:
    return any(
        condition in SAVE_ADVANTAGE.get(spend["ability_id"], ())
        and ability_voice_rules.reaction_effect_eligible(state, head, spend)
        for spend in bound_spends(state, head, reaction_windows.PRE_ROLL)
    )


def shield_reaction(state, head: dict) -> str | None:
    """The post-roll spend that puts a shield in the blow's way, if the reactor is the one hit.

    A shield hit is accrued off the TARGET's inventory (combat_support reads
    ``get_player_inventory(target.id)`` and selects equipped shield gear from its item and
    material rows), so a reactor who is not the target has no gear in that call — reporting
    one would wear the wrong player's shield.
    """
    target = _held_target(state, head)
    if target is None:
        return None
    return next(
        (
            spend["ability_id"]
            for spend in bound_spends(state, head, reaction_windows.POST_ROLL)
            if spend["ability_id"] in SHIELD_BEARING and spend["actor_id"] == target.id
        ),
        None,
    )


def grapple_blocked(state, head: dict) -> bool:
    target = _held_target(state, head)
    return target is not None and any(
        spend["ability_id"] in SLIPPERY_REACTIONS and spend["actor_id"] == target.id
        for spend in bound_spends(state, head, reaction_windows.POST_ROLL)
    )


def record_shield_wear(packets: list[dict], state, head: dict, summary: dict) -> None:
    """Name the shield's wear on the reaction packet, once the resolved blow reports it happened.

    Not decided at window close: the accrual needs the player's INVENTORY, which only
    ``apply_attack_result`` reads (an async query), so "a shield reaction was spent" is not yet "a
    shield took the hit" — a guardian with nothing equipped accrues nothing. Reading it back off
    the resolved summary keeps ``mechanical_effect`` a statement of what happened rather than of
    what was attempted.
    """
    target = _held_target(state, head)
    if target is None or "shield" not in (summary.get("durability") or {}):
        return
    packet = next(
        (
            row
            for row in packets
            if row["actor_id"] == target.id and row["ability_id"] in SHIELD_BEARING and row["mechanical_effect"] is None
        ),
        None,
    )
    if packet is not None:
        packet["mechanical_effect"] = "shield_durability"


def record_intercept(packets: list[dict], summary: dict) -> None:
    if not summary.get("hit"):
        return
    recipient = summary.get("damage_target_id")
    for packet in packets:
        if packet["actor_id"] == recipient and packet["ability_id"] == reaction_spend.INTERCEPT:
            packet["mechanical_effect"] = "damage_intercepted"


def record_save_advantage(packets: list[dict], summary: dict) -> None:
    """Label the reaction from the resolved save: ``close`` runs before the save is rolled."""
    if not summary.get("save_advantage"):
        return
    packet = next(
        (row for row in packets if row["ability_id"] in SAVE_ADVANTAGE and row["mechanical_effect"] is None),
        None,
    )
    if packet is not None:
        packet["mechanical_effect"] = "save_advantage"


def _held_target(state, head: dict):
    declaration = resolve_declaration(head["declaration"])
    return state.get_participant(declaration.target_id) if declaration.target_id else None


def halve(head: dict, target) -> None:
    """Halve the held blow against live HP so its summary and impact agree after a reload.

    The dice event precedes the post-roll reaction window and still describes the original roll.
    """
    result, held_ac = deserialize_roll(head["roll"])
    halved = with_landed_damage(
        result,
        result.damage // 2,
        target.hp_current,
        temporary=temp_hp.player_pool(target),
        hp_floor=conditions.damage_hp_floor(target.conditions),
        bonus_damage=result.bonus_damage // 2,
        rider_damage=result.rider_damage // 2,
        synergy_damage=result.synergy_damage // 2,
    )
    head["roll"] = serialize_roll(halved, held_ac)


def apply_bark_skin(head: dict, target: CombatParticipant) -> None:
    result, held_ac = deserialize_roll(head["roll"])
    if not D20Roll(result.attack_modifier, held_ac).evaluate(result.roll).success:
        raise ValueError("Bark Skin expected a held hit that reached the original AC")

    raised_ac = held_ac + BARK_SKIN_AC_BONUS
    verdict = D20Roll(result.attack_modifier, raised_ac).evaluate(result.roll)
    result = replace(result, target_ac=raised_ac, narrative_hint=verdict.narrative_hint)
    if not verdict.success:
        result = with_landed_damage(
            replace(result, hit=False),
            0,
            target.hp_current,
            critical_success=False,
            bonus_damage=0,
            bonus_damage_type=None,
            rider_damage=0,
            rider_damage_type=None,
            rider_ignores_resistance=False,
            sneak_attack_dice=None,
            sneak_attack_raw_damage=0,
            synergy_damage=0,
            synergy_damage_type=None,
            synergy_clause_id=None,
            order_rider=None,
            order_damage_dice=None,
            order_raw_damage=0,
            coordinated_rider=None,
            pincer_dice=None,
            pincer_raw_damage=0,
            sacrifice_rider=None,
        )
    target.bark_skin_active = True
    head["roll"] = serialize_roll(result, raised_ac)


def _apply(
    state,
    head: dict,
    window: dict,
    spend: dict,
    attack_action: dict | None,
    contest: dict | None,
    ac_spend: dict | None = None,
    hesitated: bool = False,
) -> str | None:
    """Do what this reaction does to the held blow, and name it — or None if it did nothing.

    The label is what the close ACTUALLY did, never a lookup on the ability id: a shield of faith
    spent at the pre-roll window of an ``applies_condition`` action (Hollow Shriek resolves through
    the save-gated path, with no attack roll) modified no AC, and reporting one would tell the DM
    a blow was turned aside that was never rolled.
    """
    ability_id = spend["ability_id"]
    target = _held_target(state, head)

    if contest is not None:
        if not contest["success"]:
            return None
        return combat_reaction_contest.EFFECTS[ability_id]

    if hesitated:
        return None

    if window["stage"] == reaction_windows.PRE_ROLL:
        if spend is ac_spend and attack_action is not None:
            return "target_ac_bonus"
        return None

    if ability_id in BARK_SKIN and target is not None and spend["actor_id"] == target.id:
        apply_bark_skin(head, target)
        return "round_ac_bonus"

    if (
        ability_id in HALVES_DAMAGE
        and head["roll"] is not None
        and target is not None
        and spend["actor_id"] == target.id
    ):
        halve(head, target)
        logger.info("reaction %s halved %s's blow against %s", ability_id, head["actor_id"], target.id)
        return "damage_halved"
    if ability_id in SLIPPERY_REACTIONS and target is not None and spend["actor_id"] == target.id:
        if "completed_condition" in head:
            chamber_id = head["completed_condition"]["chamber_id"]
            chamber = state.get_participant(chamber_id)
            if chamber is None or architect_entomb.source(state, target.id) != chamber_id:
                raise ValueError(f"Entomb chamber {chamber_id!r} is not linked to {target.id!r}")
            combat_structures.collapse_wall(state, chamber)
            return "restraint_escaped"
        if conditions.has_condition(target.conditions, "grappled"):
            return "grapple_blocked_still_held"
        return "grapple_escaped"
    return None


def close(state, head: dict, window: dict, *, attack_action: dict | None, contest_rng=None) -> list[dict]:
    """Apply what every reaction spent at ``window`` does to ``head``: one packet per spend.

    Two AC bonuses do not stack, so only the first spend carrying the largest one reports
    ``target_ac_bonus``; a winning Objection leaves every other spend at the window null.

    Called by ``combat_hold.pump`` before it applies a held attack or emits a completed condition packet.

    The packet is SYNTHESIZED here rather than read from a declaration: story-017 retired
    ``DeclarationType.REACTION``, so a reaction produces no declaration packet at all. ``resolved``
    is kept for shape parity with every other packet and carries no claim — ``mechanical_effect``
    is the load-bearing field, which is note 0f3945fa(f) answered ("resolved: true meant only that
    the resource was spent").

    ``attack_action`` is the pump's own verdict on whether this held action swings an attack roll,
    passed in rather than re-derived: the predicate belongs to combat_hold, which imports this
    module.
    """
    spends = bound_spends(state, head, window["stage"])
    contests = [combat_reaction_contest.resolve_or_reuse(state, head, spend, rng=contest_rng) for spend in spends]
    hesitated = combat_reaction_contest.hesitated(head)
    ac_candidates = [spend for spend in spends if ability_voice_rules.reaction_effect_eligible(state, head, spend)]
    ac_spend = max(ac_candidates, key=lambda spend: AC_BONUS.get(spend["ability_id"], 0), default=None)
    if ac_spend is not None and ac_spend["ability_id"] not in AC_BONUS:
        ac_spend = None
    packets = []
    for spend, contest in zip(spends, contests, strict=True):
        effect = _apply(state, head, window, spend, attack_action, contest, ac_spend, hesitated)
        ability = abilities.get_ability(spend["ability_id"])
        packet = {
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
        if contest is not None:
            packet["reactor_total"] = contest["reactor_total"]
            packet["opposer_total"] = contest["opposer_total"]
        if effect == "restraint_escaped":
            packet["chamber_id"] = head["completed_condition"]["chamber_id"]
        if effect == "grapple_blocked_still_held":
            target = cast(CombatParticipant, _held_target(state, head))
            grappler_id = combat_grapple.grappler_id(target.conditions)
            if grappler_id is None:
                # validate_condition_dict PERMITS a grappled row with no source ("absent fields are
                # fine"), so this is a shape the read boundary accepts, not corruption — and raising
                # here would escape pump() past its HeldActionUnresolvable catch (a ValueError
                # SUBCLASS), roll the phase back, and re-raise on the persisted row every retry:
                # a wedged combat where the label alone was wrong. The label already tells the truth
                # (still held); only the holder's name is missing, so the DM says "something still
                # has you". HeldActionUnresolvable is not importable here - combat_hold imports this
                # module.
                logger.error("reaction %s: %s is grappled with no source; holder unnamed", ability.id, target.id)
            else:
                packet["grappler_id"] = grappler_id
        packets.append(packet)
    return packets
