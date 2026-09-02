"""Polymorphic capability-activation dispatcher for the DM agent (M25 Phase-5, story-001).

Five capability tools — cast_spell, request_ability_activation, deploy_veil_anchor,
activate_veil_ward, inner_fire — fold into one verb so the strict-20 tool ceiling stops binding
and new content stops adding tools (ADR 0007 §10). ``activate`` is a pure router: it classifies
the id and dispatches to the matching pre-existing ``_impl``, none of which it modifies.

Two of the five capabilities have no natural content id (the Veil Ward's raise/dismiss and the
Draethar's Inner Fire), so they are modeled as reserved id tokens (customer decision, this
story) rather than special-cased arguments — ``activate`` stays a pure single-id verb.

Resolution order is reserved-first, fail-loud, BEFORE any dispatch (§4/AC4): reserved tokens,
then Veil Anchor item ids (``veil_ward.VEIL_ANCHORS``), then spell ids, then ability ids. Spell
and ability ids are assumed disjoint (verified this story: 87 spells vs 145 abilities, no
overlap) so trying spell-then-ability is unambiguous.

The dispatcher opens no transaction of its own — each target ``_impl`` still manages its own —
but it DOES carry ``@db_tool`` like its five siblings. That decorator is error-handling, not
transaction management: it narrates a DB error escaping an ``_impl`` (a corrupt-row
``JSONDecodeError``, a connection/timeout failure) as a friendly ``ToolError`` instead of letting
a raw exception reach the player. Omitting it would silently drop that protection for every
folded capability.
"""

import logging

from livekit.agents.llm import ToolError, function_tool
from livekit.agents.voice import RunContext

import abilities
import ability_tools
import draethar_inner_fire
import spell_casting
import spells
import veil_anchor_tools
import veil_ward
import veil_ward_tools
from db_errors import db_tool
from session_data import SessionData

logger = logging.getLogger("divineruin.tools")

_VEIL_WARD = "veil_ward"
_VEIL_WARD_DISMISS = "veil_ward_dismiss"
_DRAETHAR_INNER_FIRE = "draethar_inner_fire"
_RESERVED = frozenset({_VEIL_WARD, _VEIL_WARD_DISMISS, _DRAETHAR_INNER_FIRE})


@function_tool()
@db_tool
async def activate(
    context: RunContext[SessionData],
    id: str,
    target_id: str | None = None,
    target_ids: list[str] | None = None,
) -> str:
    """Activate a capability: cast a spell, use an archetype ability, deploy a Veil Anchor, raise
    or dismiss a Veil Ward, or trigger the Draethar's Inner Fire.

    Pass the id of the thing being activated. For spells and abilities this is their content id
    (e.g. 'firebolt', 'warrior_devastating_strike'); for a Veil Anchor it is the carried item's id
    (e.g. 'veil_ward_anchor_small'). Three reserved tokens have no content id of their own:
    'veil_ward' raises a Veil Ward, 'veil_ward_dismiss' drops one, and 'draethar_inner_fire'
    triggers a Draethar's racial Inner Fire.

    Pass target_id when the capability affects ONE other entity (a spell/ability target, or the
    party member raising/dismissing a Veil Ward on their own behalf). Pass target_ids (a list)
    for a spell or ability that hits several allies/enemies at once — not both. Omit both for a
    self-targeted or partyless capability.

    Some activations refuse — narrate the refusal rather than forcing it: a revival spell is
    refused on a Hollow-killed corpse; a spell's own multi-target cap is enforced (too many is
    refused); a Veil Ward raise is refused while one is already up (one shared ward per party) or
    for an ineligible/underleveled/unaffordable caster; Inner Fire is once per encounter and
    combat-only. IN COMBAT a reaction ability is refused unless it is the exact reaction the player
    declared this round through declare_phase, the phase is at the resolution beat, and the round's
    one reaction is unspent — outside combat reactions activate freely. Cantrips are free and scale
    their damage with level."""
    return await _activate_impl(context, id, target_id=target_id, target_ids=target_ids)


def _resolve_kind(id: str, *, spells_mod, abilities_mod, anchors_mod) -> str:
    """Pure classification: which _impl family this id belongs to. Fails loud before any
    dispatch when the id matches nothing (AC4)."""
    if id in _RESERVED:
        return id
    if id in anchors_mod.VEIL_ANCHORS:
        return "anchor"
    try:
        spells_mod.get_spell(id)
        return "spell"
    except ValueError:
        pass
    try:
        abilities_mod.get_ability(id)
        return "ability"
    except ValueError:
        pass
    raise ToolError(f"'{id}' is not an activatable capability.")


async def _activate_impl(
    context: RunContext[SessionData],
    id: str,
    *,
    target_id: str | None = None,
    target_ids: list[str] | None = None,
    spells_mod=spells,
    abilities_mod=abilities,
    anchors_mod=veil_ward,
    cast_spell_mod=spell_casting,
    ability_mod=ability_tools,
    anchor_mod=veil_anchor_tools,
    ward_mod=veil_ward_tools,
    inner_fire_mod=draethar_inner_fire,
) -> str:
    logger.info("activate called: id=%s", id)

    kind = _resolve_kind(id, spells_mod=spells_mod, abilities_mod=abilities_mod, anchors_mod=anchors_mod)

    if kind == _VEIL_WARD:
        return await ward_mod._activate_veil_ward_impl(context, active=True, caster_id=target_id)
    if kind == _VEIL_WARD_DISMISS:
        return await ward_mod._activate_veil_ward_impl(context, active=False, caster_id=target_id)
    if kind == _DRAETHAR_INNER_FIRE:
        return await inner_fire_mod._inner_fire_impl(context)
    if kind == "anchor":
        return await anchor_mod._deploy_veil_anchor_impl(context, id)
    if kind == "spell":
        return await cast_spell_mod._cast_spell_impl(context, id, target_id=target_id, target_ids=target_ids)
    return await ability_mod._request_ability_activation_impl(context, id, target_id=target_id, target_ids=target_ids)
