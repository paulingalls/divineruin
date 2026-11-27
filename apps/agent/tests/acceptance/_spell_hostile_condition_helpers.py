"""Registered combat declarations backed by the seeded spell and creature catalogs."""

from unittest.mock import patch
from uuid import uuid4

import pytest
from acceptance._capstone_helpers import _d20, _resolve_round
from acceptance.seeds import seed_player_with_pools
from combat.test_spell_damage_lands import load_combat, saved_player
from voice_condition_fixtures import participant, place_actors

import combat_turn
import db
import db_mutations
from caster_state import ConcentrationState
from creature_catalog import query_creature_by_id
from creature_combat import translate_creature
from declaration_payloads import AbilityDecl, AttackDecl, DefendDecl
from party_state import PartyState
from session_data import CombatParticipant

HOLD = "arcane_hold_person"
STUN = "arcane_power_word_stun"
DETECT = "arcane_detect_magic"


@pytest.fixture
async def dev_db_pool(reset_db_pool):
    return await db.get_pool()


async def set_foe(ctx, creature="bandit", hp=100, foe_id="foe"):
    state = ctx.userdata.combat_state
    row = await query_creature_by_id(creature)
    derived = translate_creature(row, encounter_id="spell_conditions", enemy_id=foe_id, role="standard")
    foe = state.get_participant(foe_id)
    if foe is None:
        foe = CombatParticipant(foe_id, derived["name"], "enemy", 12, hp, hp, derived["ac"])
        state.participants.append(foe)
        state.initiative_order.append(foe_id)
    for key in (
        "category",
        "creature_id",
        "hollow",
        "attributes",
        "action_pool",
        "saving_throw_proficiencies",
        "corruption_field",
        "regeneration",
        "choir_reaction",
    ):
        setattr(foe, key, derived[key])
    foe.hp_current = foe.hp_max = hp
    place_actors(state)
    await db_mutations.save_combat_state(state.combat_id, state.to_dict())
    return foe


def defend(actor_id):
    return DefendDecl(reshape=[], kind="defend", actor_id=actor_id)


def cast_spell(actor_id, spell, target: str | None = "foe"):
    return AbilityDecl(
        kind="ability", actor_id=actor_id, action=spell, targets=[target] if target else [], argument_type=""
    )


def attack(actor_id, action, target_id, rider=""):
    return AttackDecl(
        kind="attack",
        actor_id=actor_id,
        action=action,
        target_id=target_id,
        held_item_id="",
        rider=rider,
        quick_fingers_mode="",
        quick_fingers_item="",
        reshape=[],
    )


async def reload(ctx):
    session = ctx.userdata
    state = await load_combat(session.combat_state.combat_id)
    session.combat_state = state
    for member in session.party.members:
        player = await saved_player(member.player_id)
        member.concentration = ConcentrationState.from_record(player.get("concentration"))
    return state


async def play(ctx, *declarations, face=1, faces=None):
    await combat_turn.declare_phase(ctx, list(declarations))
    with (
        patch(
            "check_resolution.dice_roll",
            return_value=_d20(face),
            side_effect=None if faces is None else [_d20(value) for value in faces],
        ),
        patch("check_resolution_attack.dice_roll", side_effect=lambda notation, **_: _d20(int(notation.split("d")[0]))),
    ):
        result = await _resolve_round(ctx)
    return result["packets"], await reload(ctx)


def receipt(packets, actor_id):
    return next(packet["cast"] for packet in packets if packet["actor_id"] == actor_id and "cast" in packet)


def instance(kind, spell, caster, save):
    return dict(type=kind, duration=None, source=spell, stacks=1, originating_participant_id=caster, tick_save=save)


async def add_player(ctx, archetype, known_spells=()):
    pid = f"spell_{uuid4().hex}"
    pool = await db.get_pool()
    await seed_player_with_pools(pool, player_id=pid, class_=archetype, known_spells=known_spells)
    await pool.execute("UPDATE players SET data=jsonb_set(data,'{level}','8') WHERE player_id=$1", pid)
    session = ctx.userdata
    session.party.members.append(PartyState.solo(pid).primary)
    state = session.combat_state
    place_actors(state, pid)
    state.initiative_order.insert(1, pid)
    actor = participant(state, pid)
    actor.level = 8
    actor.archetype_id = archetype
    actor.attributes = {"intelligence": 18, "strength": 18}
    return pid
