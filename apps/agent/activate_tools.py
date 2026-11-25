"""Polymorphic capability-activation dispatcher for the DM agent (M25 Phase-5, story-001).

Five capability tools — cast_spell, request_ability_activation, deploy_veil_anchor,
activate_veil_ward, inner_fire — fold into one verb so the strict-20 tool ceiling stops binding
and new content stops adding tools (ADR 0007 §10). ``activate`` is a pure router: it classifies
the id and dispatches to the matching pre-existing ``_impl``, none of which it modifies.

Two of the five capabilities have no natural content id (the Veil Ward's raise/dismiss and the
Draethar's Inner Fire), so they are modeled as reserved id tokens (customer decision, this
story) rather than special-cased arguments — ``activate`` stays a pure single-id verb.

Resolution order is reserved-first, fail-loud, BEFORE any dispatch (§4/AC4): reserved tokens,
then Veil Anchor item ids (``veil_ward.VEIL_ANCHORS``), spell ids, ability ids, and mentor-variant
ids. The routed namespaces are pinned pairwise disjoint by a content test, so precedence is
unambiguous.

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
import item_heal
import mentor_variants
import patron_ability_tools
import patron_gateway
import patron_gift_tools
import reaction_gate
import spell_casting
import spells
import unbound_tools
import veil_anchor_tools
import veil_ward
import veil_ward_tools
import zhael_fate
from action_sound_content import publish_action_sound
from db_errors import db_tool
from declaration_payloads import Destination
from item_effects import CONSUME_PREFIX
from patron_combat_edges import RESTORATION_SURGE, SCALES_VERDICT, VEILSTEP, WILDMOTHERS_WRATH, SurgeCondition
from patron_gifts import SYRATH_SHADOW_VEIL, VEYTHAR_INSIGHT
from reshape_payloads import WallEndpoints
from session_data import SessionData
from thyra_thornwall import GIFT as THORNWALL

logger = logging.getLogger("divineruin.tools")

_VEIL_WARD = "veil_ward"
_VEIL_WARD_DISMISS = "veil_ward_dismiss"
_DRAETHAR_INNER_FIRE = "draethar_inner_fire"
_RESERVED = frozenset(
    {
        *unbound_tools.MILESTONE_IDS,
        _VEIL_WARD,
        _VEIL_WARD_DISMISS,
        _DRAETHAR_INNER_FIRE,
        unbound_tools.RAW_CHANNELING,
        VEYTHAR_INSIGHT,
        SYRATH_SHADOW_VEIL,
        patron_ability_tools.WEIGHT_OF_TRUTH,
        zhael_fate.FATE,
    }
)


@function_tool()
@db_tool
async def activate(
    context: RunContext[SessionData],
    id: str,
    target_id: str | None = None,
    target_ids: list[str] | None = None,
    offer_id: str | None = None,
    keep: zhael_fate.Keep | None = None,
    condition: SurgeCondition | None = None,
    destination: Destination | WallEndpoints | None = None,
) -> str | tuple:
    """Activate a capability: cast a spell, use an archetype ability, deploy a Veil Anchor, raise
    or dismiss a Veil Ward, or trigger the Draethar's Inner Fire.

    In combat, use declare_phase for non-reaction archetype actions. Shield Bash uses rider="shield_bash"
    on a melee weapon attack. Cunning Action uses rider="dash" or rider="hide" on a weapon attack.
    Query abilities for the actor's available ids and attack riders.

    Pass the id of the thing being activated. For spells, abilities, and learned mentor variants
    this is their content id (e.g. 'arcane_bolt', 'warrior_devastating_strike', or
    'warrior_cleaving_blow_keldaran'); for a Veil Anchor it is the carried item's id (e.g.
    'veil_ward_anchor_small'). The reserved tokens have no content id of their own:
    'veil_ward' raises a Veil Ward, 'veil_ward_dismiss' drops one, and 'draethar_inner_fire'
    triggers a Draethar's racial Inner Fire. 'unbound_raw_channeling' adds exactly 3
    Resonance for an Unbound member, once per encounter; query_info(kind='patron') lists it.

    Self-Reliant chooses one save proficiency once: 'unbound_self_reliant_strength',
    'unbound_self_reliant_dexterity', 'unbound_self_reliant_constitution',
    'unbound_self_reliant_intelligence', 'unbound_self_reliant_wisdom',
    'unbound_self_reliant_charisma'. 'unbound_divine_immunity' at Self-Forged negates
    one chosen divine ability once per long rest. query_info(kind='patron') lists availability.

    'syrath_shadow_veil' is combat-only: hide until the current round ends, or until attacking,
    casting, or failing Stealth. A short rest restores this gift.

    After an offered failed knowledge check, 'veythar_lorekeepers_insight' rerolls it once;
    take the new result. A short rest restores this gift.

    For a voiced Fate's Thread offer, activate 'zhael_fates_thread' with offer_id to spend it and
    show the reroll. Then call again with the same offer_id and keep='original' or 'reroll'.
    Before spending, keep='original' declines. Any other tool call keeps the original, and an
    already rolled gift stays spent. Veilstep, Threshold Walk, and Thornwall refuse during a partially resolved
    round and leave the Fate offer open. For offered 'zhael_lucky', use offer_id alone to flip the die and resolve it.

    Patron tier ids come from query_info(kind='patron').abilities: spend only when available;
    narrate refusals. 'valdris_weight_of_truth' spends Weight of Truth until a short rest.

    For 'orenthel_restoration_surge', select one condition: 'poisoned', 'blinded', 'frightened',
    or 'hollowed' (stage 1 only). Use target_id for a present party member or omit it for self.
    Narrate the touch. The gift costs no Focus and recharges on a long rest.

    For Veilstep, use activate(id="syrath_veilstep", destination={x,y,z}), choosing a visible shadow
    up to 60 feet from the follower. Coordinates are in feet. It costs no movement or Resonance and recharges
    on a long rest. A queued move is removed; ask for a new move from the new position at the next
    declaration beat. Without fight geometry, omit destination and narrate the step through shadow.

    Thornwall uses activate(id="thyra_thornwall", destination={start:{x,y,z},end:{x,y,z}}) in combat.
    Choose two points in feet. Keep the barrier clear of creatures, up to 30 feet long and within 30 feet
    at its nearest point. It blocks movement and melee reach and recharges on a long rest.

    Beyond the Horizon uses activate(id="nythera_beyond_the_horizon", target_id=<visited location id>).
    Choose an id from query_info(kind="patron").abilities[].destinations. Outside combat, the whole
    party crosses together. The follower gains 5 Resonance and the gift recharges next session.

    Pass target_id for a selected location or ONE entity (a spell/ability target). A Veil
    Ward is always raised or dismissed by the player speaking; omit target_id for it. Pass target_ids (a list)
    for a spell or ability that hits several allies/enemies at once — not both. Omit both for a
    self-targeted or partyless capability.

    For Mass Heal, omit both selectors; it heals all party players at the caster's location.
    Prayer of Healing is only available outside combat and accepts up to six present party players.

    Outside combat, use a healing item's consume_id from query_info inventory.
    Omit target_id to use one from your stack on yourself or name a present party player.
    In combat use a consume declaration with declare_phase.
    For Dispel Corruption on inventory, use the queried item_target_id as target_id:
    "item:<owner_player_id>:<item_id>", e.g. "item:player_1:rend_shard". It selects the
    owner's whole tainted stack; the owner must be a player in this session's party.
    Item purification is available outside phase resolution, with no target_ids.

    Some activations refuse — narrate the refusal rather than forcing it: a revival spell is
    refused on a Hollow-killed corpse; a spell's own multi-target cap is enforced (too many is
    refused); a Veil Ward raise is refused while one is already up (one shared ward per party) or
    for an ineligible/underleveled/unaffordable caster; Inner Fire is once per encounter and
    combat-only. IN COMBAT a reaction ability is an INTERRUPT: call it while resolve_phase reports an
    open window in next.waiting_on, passing an id listed in next.waiting_on.reactions — the exact
    ids that fit that window — with no declaration first. It is refused when no window is open, when the reaction
    answers a different window, or when the round's one reaction is already spent. Outside combat
    reactions activate freely. Cantrips are free and scale
    their damage with level."""
    if destination is not None and id not in (VEILSTEP, THORNWALL):
        raise ToolError("The destination selector is only for Veilstep or Thornwall.")
    if id == VEILSTEP and isinstance(destination, WallEndpoints):
        raise ToolError("Veilstep takes a destination point.")
    if id == THORNWALL and (
        not isinstance(destination, WallEndpoints)
        or target_id is not None
        or target_ids is not None
        or condition is not None
    ):
        raise ToolError("Thornwall takes start and end points. Omit entity and condition selectors.")
    if id == VEILSTEP and (target_id is not None or target_ids is not None):
        raise ToolError("Veilstep takes a destination point. Omit entity target selectors.")
    if id in zhael_fate.ROLL_ABILITIES:
        if condition is not None:
            raise ToolError("The condition selector is only for Restoration Surge.")
        return await zhael_fate.activate(context.userdata, id, offer_id, keep)
    if offer_id is not None or keep is not None:
        raise ToolError("offer_id is for a held roll; keep belongs to Fate's Thread.")
    if id == patron_gateway.GATEWAY:
        if target_ids is not None or condition is not None:
            raise ToolError("Beyond the Horizon takes one location. Use target_id.")
        return await patron_gateway.activate(context, target_id=target_id)
    if id == SCALES_VERDICT:
        if target_ids is not None or condition is not None:
            raise ToolError("Use target_id to select one living hostile creature for The Scale's Verdict.")
        return await patron_ability_tools.activate_combat_damage(context.userdata, id, target_id=target_id)
    if id == WILDMOTHERS_WRATH and condition is None:
        return await patron_ability_tools.activate_combat_damage(context.userdata, id)
    return await _activate_impl(
        context,
        id,
        target_id=target_id,
        target_ids=target_ids,
        condition=condition,
        destination=destination.model_dump() if destination is not None else None,
    )


def _resolve_kind(id: str, *, spells_mod, abilities_mod, variants_mod, anchors_mod) -> str:
    """Pure classification: which _impl family this id belongs to. Fails loud before any
    dispatch when the id matches nothing (AC4)."""
    if id in _RESERVED:
        return id
    if id in patron_ability_tools.catalog():
        return "patron_ability"
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
    try:
        variants_mod.get_mentor_variant(id)
        return "variant"
    except ValueError:
        pass
    raise ToolError(f"'{id}' is not an activatable capability.")


async def _activate_impl(
    context: RunContext[SessionData],
    id: str,
    *,
    target_id: str | None = None,
    target_ids: list[str] | None = None,
    condition: str | None = None,
    destination: dict | None = None,
    spells_mod=spells,
    abilities_mod=abilities,
    variants_mod=mentor_variants,
    anchors_mod=veil_ward,
    cast_spell_mod=spell_casting,
    ability_mod=ability_tools,
    anchor_mod=veil_anchor_tools,
    ward_mod=veil_ward_tools,
    inner_fire_mod=draethar_inner_fire,
) -> str:
    logger.info("activate called: id=%s", id)
    if condition is not None and id != RESTORATION_SURGE:
        raise ToolError("The condition selector is only for Restoration Surge.")
    if id == RESTORATION_SURGE and target_ids is not None:
        raise ToolError("Restoration Surge targets one player. Use target_id or omit it for self.")
    if id.startswith(CONSUME_PREFIX):
        if target_ids is not None:
            raise ToolError("A healing item uses one target_id. Omit it for the holder.")
        context.disallow_interruptions()
        return await item_heal.consume_exploration(context.userdata, id.removeprefix(CONSUME_PREFIX), target_id)
    try:
        kind = _resolve_kind(
            id,
            spells_mod=spells_mod,
            abilities_mod=abilities_mod,
            variants_mod=variants_mod,
            anchors_mod=anchors_mod,
        )
    except ToolError as unknown:
        session = context.userdata
        offered = reaction_gate.offered_reactions(session.combat_state) if session.combat_state is not None else []
        if not offered:
            raise
        try:
            actor = session.require_reaction_actor()
        except (RuntimeError, ValueError):
            # HINT ONLY — no spend, no write. A turn with no live authenticated speaker (a reconnect
            # or card-tap reply) has no id to filter by; tolerate exactly that by dropping the hint,
            # because the unknown-id refusal still reaches the DM, whereas raising here would reach
            # it as livekit's opaque "An internal error occurred". The spend paths still fail loud.
            raise unknown from None
        valid = [reaction["id"] for reaction in offered if reaction["actor_id"] == actor.player_id]
        if not valid:
            raise
        raise ToolError(f"{unknown} Reactions that fit the open window: {', '.join(valid)}.") from unknown

    if kind in {"patron_ability", patron_ability_tools.WEIGHT_OF_TRUTH}:
        return await patron_ability_tools.activate(
            context, id, target_id=target_id, condition=condition, destination=destination
        )
    if kind == SYRATH_SHADOW_VEIL:
        return await patron_gift_tools.activate_shadow_veil(context)
    if kind == VEYTHAR_INSIGHT:
        return await patron_gift_tools.activate_insight(context)
    if kind in unbound_tools.MILESTONE_IDS:
        return await unbound_tools.activate_milestone(context, id)
    if kind == unbound_tools.RAW_CHANNELING:
        return await unbound_tools._raw_channeling_impl(context)
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
    if kind == "variant":
        variant = variants_mod.get_mentor_variant(id)
        result = await ability_mod._request_ability_activation_impl(
            context,
            variant.ability_id,
            variant_id=id,
            target_id=target_id,
            target_ids=target_ids,
        )
        if not context.userdata.in_combat:
            await publish_action_sound(context.userdata, "action_ability")
        return result
    ability = abilities_mod.get_ability(id)
    if ability.spell_id is not None and not context.userdata.in_combat:
        return await cast_spell_mod._cast_spell_impl(
            context, ability.spell_id, target_id=target_id, target_ids=target_ids
        )
    result = await ability_mod._request_ability_activation_impl(context, id, target_id=target_id, target_ids=target_ids)
    if not context.userdata.in_combat:
        await publish_action_sound(context.userdata, "action_ability")
    return result
