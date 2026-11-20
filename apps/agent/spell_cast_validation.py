"""Spell knowledge, resource gates, and target preparation."""

from livekit.agents.llm import ToolError

import cast_modifiers
import combat_spell_heal
import combat_voice_rules
import patron_echo_choice
import spell_item_resolution
import spell_knowledge
import spells
from party_state import PartyMember
from resource_costs import gate_pool
from session_data import CombatState, SessionData
from tool_support import _validate_id


def _gate_spell(player: dict, spell_id: str, known_spell_ids: frozenset[str], *, spells_mod=spells):
    """Require spell knowledge and affordable Focus before either cast path writes."""
    patron_echo_choice.gate(player)
    try:
        spell = spells_mod.get_spell(spell_id)
    except ValueError as e:
        raise ToolError(str(e)) from e
    if spell.id not in known_spell_ids:
        raise ToolError(f"{spell.id} isn't a spell you know")
    gate_pool(player, "focus", spell.focus_cost, label=spell.name)
    return spell


REVIVAL_SPELL_IDS = frozenset({"divine_revivify"})


def revivify_refused(character_data: dict) -> bool:
    return bool(character_data.get("hollow_killed"))


async def _prepare_cast(
    session: SessionData,
    caster: PartyMember,
    spell_id: str,
    *,
    conn,
    player: dict | None,
    combat_state: CombatState | None,
    target_id: str | None,
    target_ids: list[str] | None,
    content_mod,
    spells_mod,
    condition_produce_mod,
    queries_mod,
    character_spells_mod,
):
    """Validate the cast and prepare targets before any resource write."""
    _validate_id(spell_id, "spell_id")
    item_target = await spell_item_resolution.resolve_item_target(
        session, spell_id, target_id, target_ids, phase=player is not None, content=content_mod
    )
    if target_ids is not None:
        for tid in target_ids:
            _validate_id(tid, "target_id")
    player_id = caster.player_id

    try:
        voice_spell = spells_mod.get_spell(spell_id)
        combat_voice_rules.guard_spell(
            combat_state if combat_state is not None else session.combat_state,
            player_id,
            voice_spell,
            target_id,
            target_ids,
        )
    except ValueError as e:
        raise ToolError(str(e)) from e

    if voice_spell.heal is not None and combat_state is None and session.in_combat:
        raise ToolError(f"{voice_spell.name} is cast in combat with declare_phase")
    heal = voice_spell.heal if combat_state is None else None
    locked_rows: dict[str, dict] | None = None
    if player is None:
        produces_ooc = voice_spell.applies_condition is not None and not session.in_combat
        lock_target_ids = (
            session.party.member_ids if heal is not None and heal["recipients"] == "all_allies" else target_ids
        )
        locked_rows, player = await condition_produce_mod.lock_ooc_caster_and_targets(
            produces_ooc=produces_ooc or item_target is not None or heal is not None,
            player_id=player_id,
            target_id=item_target[0] if item_target else target_id,
            target_ids=lock_target_ids,
            party_member_ids=session.party.member_ids,
            queries_mod=queries_mod,
            conn=conn,
        )
        assert player is not None
    else:
        player = await queries_mod.get_player(player_id, for_update=True, conn=conn)
        if player is None:
            raise ToolError(f"Unknown player: {player_id}")

    known_rows = await character_spells_mod.get_known(player_id, conn=conn)
    known_spell_ids = spell_knowledge.castable_spell_ids(player.get("class"), (row["spell_id"] for row in known_rows))
    spell = _gate_spell(player, spell_id, known_spell_ids, spells_mod=spells_mod)

    if spell_id in REVIVAL_SPELL_IDS:
        if target_id is not None and target_id != player_id:
            gate_row = await queries_mod.get_player(target_id, conn=conn)
            if gate_row is None:
                raise ToolError(f"Unknown target: {target_id}")
        else:
            gate_row = player
        if revivify_refused(gate_row):
            raise ToolError(f"{spell_id} cannot reach the corpse — it is Hollow-killed.")
    patron = (player.get("divine_favor") or {}).get("patron")
    try:
        cast_modifiers.patron_modifiers(patron)
    except ValueError as e:
        raise ToolError(str(e)) from e

    heal_rows = None
    try:
        if heal is not None:
            assert locked_rows is not None
            heal_rows = combat_spell_heal.exploration_recipients(
                spell, heal, player_id, player, target_id, target_ids, locked_rows
            )
            if target_ids is not None:
                target_ids = list(heal_rows)
        elif target_ids is not None:
            target_ids = spells_mod.normalize_target_list(spell, target_id, target_ids)
    except ValueError as e:
        raise ToolError(str(e)) from e
    return spell, player, target_ids, item_target, locked_rows, heal_rows
