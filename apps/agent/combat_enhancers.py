"""Pure enhancer policy for combat declarations (M4.2, story-004).

An enhancer EXPANDS what a single declaration resolves into — it never grants a
second declaration (gm_combat §Action Economy L108-121). This is the pure decision
layer: combat_turn's resolution loop asks it (1) which attack actions one ATTACK
declaration becomes, and (2) which narrated riders to attach. No IO, no state.

Two of the six enhancers are mechanical (real HP): extra_attack, shield_bash. The
other four are narrated riders — descriptive strings the DM voices — because the
engine has no positioning/minion/social systems yet (cunning_action, hit_and_run,
command_lesser, quick_change).
"""

from __future__ import annotations

from declarations import Declaration, DeclarationType

# Enhancer keys carried in CombatParticipant.enhancers.
EXTRA_ATTACK = "extra_attack"
SHIELD_BASH = "shield_bash"
CUNNING_ACTION = "cunning_action"
HIT_AND_RUN = "hit_and_run"
COMMAND_LESSER = "command_lesser"
QUICK_CHANGE = "quick_change"

# A shield bash is a small bludgeoning strike synthesized from the enhancer — no shield
# item is read, since the spec ties bash to the enhancer, not to a shield's stats
# (assumption 1c110872aa53).
SHIELD_BASH_ACTION = {"name": "Shield Bash", "damage": "1d4", "damage_type": "bludgeoning", "properties": []}

# Canonical enhancer vocabulary + the order populated lists follow (deterministic, not
# dict-insertion order).
ALL_ENHANCERS = (EXTRA_ATTACK, SHIELD_BASH, CUNNING_ACTION, HIT_AND_RUN, COMMAND_LESSER, QUICK_CHANGE)

_VALID_CUNNING_RIDERS = ("dash", "disengage", "hide")
_DEFAULT_CUNNING_RIDER = "dash"


def enhancers_from_flags(flags: dict | None) -> list[str]:
    """The enhancer keys a player's data.flags grant (truthy), in ALL_ENHANCERS order.

    Combat init calls this to populate CombatParticipant.enhancers. Only extra_attack is
    grantable today; the other five populate once their grants land (forward-wired,
    concern 655580cea834). Unknown flag keys are ignored.
    """
    if not flags:
        return []
    return [e for e in ALL_ENHANCERS if flags.get(e)]


def attack_sequence(enhancers: list[str], base_action: dict) -> list[dict]:
    """The ordered attack actions one ATTACK declaration resolves into.

    - no relevant enhancer -> [base_action]
    - extra_attack         -> [base_action, base_action]            (resolve the swing twice)
    - shield_bash          -> [base_action, SHIELD_BASH_ACTION]
    - both                 -> [base_action, SHIELD_BASH_ACTION]     (the bash REPLACES the
      extra swing — "replaces one attack if multiattack", gm_combat L120; total stays 2)
    """
    if SHIELD_BASH in enhancers:
        return [base_action, SHIELD_BASH_ACTION]
    if EXTRA_ATTACK in enhancers:
        return [base_action, base_action]
    return [base_action]


def declaration_riders(enhancers: list[str], decl: Declaration) -> list[str]:
    """Narrated (non-mechanical) riders one declaration expands into.

    Each rider rides its host declaration category: the attack-riders on ATTACK,
    quick_change on a social (INTERACT) declaration. Only riders whose enhancer the
    actor holds are emitted. These carry no HP/AC/positioning effect — they are
    descriptive strings for the DM to voice (forward-wired until the underlying
    movement/minion/social systems exist; concern 655580cea834).
    """
    riders: list[str] = []
    if decl.type is DeclarationType.ATTACK:
        if CUNNING_ACTION in enhancers:
            chosen = decl.rider if decl.rider in _VALID_CUNNING_RIDERS else _DEFAULT_CUNNING_RIDER
            riders.append(f"cunning_action:{chosen}")
        if HIT_AND_RUN in enhancers:
            riders.append("hit_and_run:reposition_15ft")
        if COMMAND_LESSER in enhancers:
            riders.append("command_lesser:directs_lesser_hollow")
    if decl.type is DeclarationType.INTERACT and QUICK_CHANGE in enhancers:
        riders.append("quick_change:identity_swap")
    return riders
