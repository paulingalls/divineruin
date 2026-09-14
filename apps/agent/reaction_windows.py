"""Derive the reaction windows a held enemy action opens (M29, story-016).

decision 46 / game_mechanics_combat.md:182-187 give the Beat-3 loop its shape — the DM narrates
each enemy action, PAUSES for a reaction window, and the engine holds enemy damage until each
window closes. Nothing in the tree mapped an enemy action to a member of
``abilities.REACTION_WINDOWS`` before this module, so the DM had to guess a window among nine
(constraint 6). This is that map.

Pure: a function of the action dict alone. It cannot see ownership or budget. The Beat-3 pump
combines ``CombatParticipant.has_reaction_ability`` with ``CombatState.reactions_available``, per
game_mechanics_combat.md:131 ("if the player has no reaction abilities, the DM doesn't pause").

WHY `properties` AND NOT `applies_condition`. `properties` is a bounded vocabulary across
content/encounter_templates.json's 68 action_pool entries — ranged 6, buff 5, knockback 4,
grapple 2, control 2, aoe 2, healing 1, 46 bare — and only `grapple` has a reaction consumer
today: rogue_slippery ("Reaction to a restrain/grapple effect: automatically escape") and
spy_slippery ("Reaction when restrained/grappled"). `applies_condition` is deliberately NOT read:
its one carrier is Hollow Shriek, which applies `frightened`, and neither on_condition_imposed
consumer reads fear — both read grapple/restrain — so deriving off it would open a window nothing
can use. Fear IS consumed, by bard_countercharm and diplomat_countercharm on `on_ally_targeted`,
which the pre-roll window already reaches.
"""

from __future__ import annotations

# The one property with a reaction consumer today. Named rather than inlined because the census
# test pins its two content carriers (Seizing Grab on mawling_1/mawling_2) — a content edit that
# drops them strands rogue_slippery and spy_slippery, and the census is what says so.
GRAPPLE_PROPERTY = "grapple"

# on_enemy_action is the catch-all: it opens for EVERY held enemy action, at both stages. Its one
# applicable consumer (whisper_implant_doubt, "when an enemy SUCCEEDS an attack or ability") needs
# the post-roll outcome to exist; its other three consumers are socially triggered and have
# nothing to bite on in a weapon-only action_pool — recorded inapplicable, not rescued.
CATCH_ALL = "on_enemy_action"

# The stages a held action passes through, in order. Recorded on the held entry (``opened``) so a
# window is offered exactly once per stage — a non-attack action has no roll to mark its progress,
# so the roll alone cannot serve as the position marker. They live here, with the window
# vocabulary, because combat_hold and combat_reaction_effect both need them and combat_hold
# imports combat_reaction_effect (so the constants cannot live in combat_hold without a cycle).
PRE_ROLL = "pre_roll"
POST_ROLL = "post_roll"

_STAGES = (PRE_ROLL, POST_ROLL)


def pre_roll_triggers(action: dict) -> tuple[str, ...]:
    """The windows a held enemy action opens BEFORE its roll.

    The targeting windows plus the catch-all. `on_condition_imposed` is not here: both its
    consumers escape a grapple that has already landed, which only the post-roll stage knows.
    """
    return ("on_targeted", "on_ally_targeted", CATCH_ALL)


def post_roll_triggers(action: dict, *, hit: bool) -> tuple[str, ...]:
    """The windows a held enemy action opens AFTER its roll and BEFORE its damage.

    This is the pre-damage pause story-018's Uncanny Dodge needs: the outcome is known, the HP
    write has not happened. A landed grapple additionally opens `on_condition_imposed`; a missed
    one imposes nothing.
    """
    if not hit:
        return ("on_enemy_miss", CATCH_ALL)
    triggers = ["on_hit", "on_ally_hit", CATCH_ALL]
    if GRAPPLE_PROPERTY in (action.get("properties") or []):
        triggers.append("on_condition_imposed")
    return tuple(triggers)


def open_window_for(
    *,
    round_number: int,
    seq: int,
    stage: str,
    actor_id: str,
    target_id: str | None,
    triggers: tuple[str, ...],
) -> dict:
    """The window descriptor the DM reads out of ``resolve_phase``'s ``next.waiting_on``.

    ``id`` is deterministic and unique per (round, held-action seq, stage) so the DM passes back
    an id the engine minted rather than one it guessed (constraint 6). JSONB-native throughout —
    it round-trips through CombatState.to_dict/from_dict untouched.
    """
    if stage not in _STAGES:
        raise ValueError(f"unknown reaction window stage {stage!r}; expected one of {_STAGES}")
    return {
        "id": f"r{round_number}-{seq}-{stage}",
        "stage": stage,
        "actor_id": actor_id,
        "target_id": target_id,
        "triggers": list(triggers),
    }
