"""Build the reference party through player-facing character choices."""

import json
from unittest.mock import AsyncMock, patch

from livekit.agents import RunContext
from sample_fixtures import make_context, make_mock_room

import abilities
import ability_persistence
import character_spells
import db
import db_mutations
import db_queries
import elective_choices
import spells
from choice_tools import select
from combat_ability_gate import combat_ability
from creation_classes import CLASSES
from creation_rules import CATEGORY_ATTRIBUTE_ORDER
from creation_subset import DEFAULT_PATRONS
from creation_tools import finalize_character, set_creation_choice
from inventory_tools import transact
from patron_synergy import get_archetype_synergy
from progression_tools import _award_xp_core
from query_tools import query_info
from recipe_tools import learn
from rest_mechanics import prepare_spells_on_long_rest
from rest_tools import rest
from rules_engine import ATTRIBUTE_INCREASE_LEVELS, XP_FOR_LEVEL
from session_data import CreationState, SessionData

REST_LOCATION = "accord_hearthstone_tavern"
EQUIPMENT = {
    "warrior": ("veil_forged_greatblade", "masterwork_plate"),
    "mage": (),
    "rogue": ("hollow_edge_blade", "warded_robes"),
    "cleric": ("hollow_ward_armor",),
}
SPELL_LOADOUTS = {
    "mage": ("arcane", 3, 13, ("arcane_disintegrate", "arcane_magic_missile")),
    "cleric": ("divine", 2, 11, ("divine_divine_judgment", "divine_mass_heal")),
}


async def build_reference_player(archetype: str, player_id: str, destination: str) -> tuple[str, ...]:
    ctx = make_context(player_id, room=make_mock_room())
    ctx.userdata.creation_state = CreationState()
    patron = DEFAULT_PATRONS[archetype]
    for category, value in (("class", archetype), ("name", archetype.title()), ("race", "human"), ("deity", patron)):
        assert json.loads(await set_creation_choice(ctx, category, value))["value"] == value
    with patch("creation_tools.generate_player_portrait", new_callable=AsyncMock):
        assert isinstance(await finalize_character(ctx), tuple)
    player = await db_queries.get_player(player_id)
    assert player is not None
    assert player["divine_favor"]["patron"] == patron
    synergy = get_archetype_synergy(archetype, patron)
    assert synergy is not None and synergy["clauses"]
    await award_levels(ctx, player)
    standing = json.loads(await query_info(ctx, "patron"))
    assert standing["patron_id"] == patron and standing["tier"] == "Acknowledged"
    assert standing["layer_1_gift"]["status"] == "active"
    assert standing["synergy"] == synergy
    assert [ability["tier"] for ability in standing["abilities"] if ability["eligible"]] == ["Acknowledged"]

    if archetype in SPELL_LOADOUTS:
        chosen = await prepare_electives(ctx, archetype)
    else:
        chosen = await choose_techniques(ctx, archetype)
    slots = {}
    for item in EQUIPMENT[archetype]:
        assert json.loads(await transact(ctx, item, 1, "exchange", "Reference equipment"))["action"] == "added"
        receipt = json.loads(await transact(ctx, item, 0, "equip"))
        assert receipt["action"] == "equipped" and receipt["item_id"] == item
        slots[receipt["slot"]] = item

    player = await db_queries.get_player(player_id)
    assert player is not None
    for slot, item in slots.items():
        assert player["equipment"][slot]["id"] == item
    inventory = await db_queries.get_player_inventory(player_id)
    assert set(slots.values()) <= {slot["id"] for slot in inventory if slot["slot_info"]["equipped"]}

    await db_mutations.update_player_location(player_id, REST_LOCATION)
    ctx.userdata.location_id = REST_LOCATION
    assert json.loads(await rest(ctx, "long"))["rested"]
    await db_mutations.update_player_location(player_id, destination)
    return chosen


async def award_levels(ctx: RunContext[SessionData], player: dict) -> None:
    pid = ctx.userdata.acting_player_id
    order = CATEGORY_ATTRIBUTE_ORDER[CLASSES[player["class"]].category]
    assert order[0] == CLASSES[player["class"]].primary_attribute
    async with db.transaction() as conn:
        award = await _award_xp_core(
            player_id=pid,
            player=player,
            amount=XP_FOR_LEVEL[20],
            reason="Balance reference",
            conn=conn,
            pending_events=[],
        )
    assert award.result.new_level == 20
    expected = dict(player["attributes"])
    increases: dict[str, dict[str, int]] = {}
    for level in sorted(ATTRIBUTE_INCREASE_LEVELS):
        allocation: dict[str, int] = {}
        for _ in range(2):
            attribute = next(attribute for attribute in order if expected[attribute] < 20)
            expected[attribute] += 1
            allocation[attribute] = allocation.get(attribute, 0) + 1
        increases[str(level)] = allocation
    row = await db_queries.get_player(pid)
    assert row is not None and row["attributes"] == expected
    assert {level: record["allocation"] for level, record in row["attribute_increases"].items()} == increases


async def choose_techniques(ctx: RunContext[SessionData], archetype: str) -> tuple[str, ...]:
    pid = ctx.userdata.acting_player_id
    catalog = abilities.get_archetype_abilities(archetype)
    selected = []
    for level in elective_choices.TIERS:
        pool = elective_choices.pool(catalog, level)
        pick = next((a for a in pool if combat_ability(a)), pool[0])
        receipt = json.loads(await select(ctx, f"{elective_choices.PREFIX}{level}", pick.id))
        assert receipt["chosen"] == pick.id
        assert await ability_persistence.owns_elective(pid, pick.id)
        selected.append(pick.id)
    owned = await ability_persistence.get_character_abilities(pid)
    assert {row["ability_id"] for row in owned if row["equipped"]} == set(selected)
    return tuple(selected)


async def prepare_electives(ctx: RunContext[SessionData], archetype: str) -> tuple[str, ...]:
    pid = ctx.userdata.acting_player_id
    source, cantrips, slots, priority = SPELL_LOADOUTS[archetype]
    core = {a.spell_id for a in abilities.get_archetype_abilities(archetype) if a.ability_type == "core"}
    known = {row["spell_id"] for row in await character_spells.get_known(pid)}
    assert len(known) == 2, (archetype, known)
    ids = dict.fromkeys(
        [*priority, *(spell.id for spell in spells.get_spells_by_source(source) if spell.id not in core)]
    )
    chosen = [spell_id for spell_id in ids if spells.get_spell(spell_id).spell_tier == "cantrip"][:cantrips] + [
        spell_id for spell_id in ids if spells.get_spell(spell_id).spell_tier != "cantrip"
    ][:slots]
    assert len(chosen) == cantrips + slots
    for spell_id in chosen:
        if spell_id not in known:
            assert json.loads(await learn(ctx, "spell", spell_id, "npc_teaching"))["learned"] == spell_id
    async with db.transaction() as conn:
        await prepare_spells_on_long_rest(
            pid,
            chosen,
            slot_limit=cantrips + slots,
            archetype_id=archetype,
            character_level=20,
            in_natural_terrain=False,
            conn=conn,
        )
    assert {row["spell_id"] for row in await character_spells.get_prepared(pid)} == set(chosen)
    return tuple(chosen)
