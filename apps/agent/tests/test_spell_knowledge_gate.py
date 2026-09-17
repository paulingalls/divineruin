import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from combat._helpers import _resolve_deps, _resolve_round
from livekit.agents.llm import ToolError
from sample_fixtures import make_context, make_db_mod

import character_spells
import spell_casting
import spell_knowledge
import spells
from combat_packet import _prevalidate_ability_focus
from declarations import Declaration, DeclarationType
from query_tools import _query_info_impl
from session_data import CombatParticipant, CombatState


def _player(player_class: str, *, focus: int = 18, level: int = 1) -> dict:
    return {
        "player_id": "player_1",
        "name": "Lyra",
        "class": player_class,
        "level": level,
        "focus": {"current": focus, "max": focus},
    }


def test_castable_spell_ids_unites_core_and_library_without_level_or_preparation():
    assert spell_knowledge.castable_spell_ids("mage", ["divine_revivify"]) >= {
        "arcane_bolt",
        "divine_revivify",
    }
    assert spell_knowledge.castable_spell_ids(None, ["divine_revivify"]) == {"divine_revivify"}


async def _cast(spell_id: str, player: dict, library: list[dict]):
    ctx = make_context()
    ctx.userdata.resonance.current = 4
    ctx.userdata.concentration.spell_id = "arcane_fly"
    db_mod, _conn = make_db_mod()
    queries = MagicMock()
    queries.get_player = AsyncMock(return_value=player)
    queries.get_players_for_update = AsyncMock(return_value={"player_1": player})
    persistence = MagicMock()
    persistence.update_player_resources = AsyncMock()
    resonance_mutations = MagicMock()
    resonance_mutations.update_player_resonance = AsyncMock()
    resonance_events = MagicMock()
    resonance_events.publish_resonance_changed = AsyncMock()

    with patch.object(character_spells, "get_known", new=AsyncMock(return_value=library)):
        result = await spell_casting._cast_spell_impl(
            ctx,
            spell_id,
            db_mod=db_mod,
            queries_mod=queries,
            persistence_mod=persistence,
            resonance_mutations_mod=resonance_mutations,
            resonance_events_mod=resonance_events,
        )
    return json.loads(result), ctx, persistence, resonance_mutations, resonance_events


@pytest.mark.asyncio
async def test_unknown_spell_refuses_before_resources_or_events_change():
    ctx = make_context()
    ctx.userdata.resonance.current = 4
    ctx.userdata.concentration.spell_id = "arcane_fly"
    player = _player("skirmisher")
    db_mod, _conn = make_db_mod()
    queries = MagicMock()
    queries.get_players_for_update = AsyncMock(return_value={"player_1": player})
    persistence = MagicMock(update_player_resources=AsyncMock())
    resonance_mutations = MagicMock(update_player_resonance=AsyncMock())
    resonance_events = MagicMock(publish_resonance_changed=AsyncMock())

    with patch.object(character_spells, "get_known", new=AsyncMock(return_value=[])):
        with pytest.raises(ToolError, match="arcane_fireball isn't a spell you know"):
            await spell_casting._cast_spell_impl(
                ctx,
                "arcane_fireball",
                db_mod=db_mod,
                queries_mod=queries,
                persistence_mod=persistence,
                resonance_mutations_mod=resonance_mutations,
                resonance_events_mod=resonance_events,
            )

    persistence.update_player_resources.assert_not_called()
    resonance_mutations.update_player_resonance.assert_not_called()
    resonance_events.publish_resonance_changed.assert_not_called()
    assert player["focus"]["current"] == 18
    assert ctx.userdata.resonance.current == 4
    assert ctx.userdata.concentration.spell_id == "arcane_fly"


@pytest.mark.asyncio
async def test_core_and_unprepared_library_spells_are_castable():
    bolt, *_ = await _cast("arcane_bolt", _player("mage"), [])
    revivify, *_ = await _cast(
        "divine_revivify",
        _player("cleric", level=1),
        [{"spell_id": "divine_revivify", "is_prepared": False}],
    )

    assert bolt["effect"] == spells.get_spell("arcane_bolt").mechanics
    assert revivify["effect"] == spells.get_spell("divine_revivify").mechanics


@pytest.mark.asyncio
async def test_library_spell_is_refused_when_absent():
    with pytest.raises(ToolError, match="divine_revivify isn't a spell you know"):
        await _cast("divine_revivify", _player("cleric"), [])


@pytest.mark.asyncio
async def test_combat_unknown_spell_refuses_before_earlier_ally_hp_write():
    ctx = make_context(player_id="ally", party_member_ids=["caster"])
    ctx.userdata.combat_state = CombatState(
        combat_id="story_052_combat",
        participants=[
            CombatParticipant(
                id="ally",
                name="Ally",
                type="player",
                initiative=18,
                hp_current=20,
                hp_max=20,
                ac=14,
                action_pool=[{"name": "Sword", "damage": "1d6", "damage_type": "slashing", "properties": []}],
            ),
            CombatParticipant(
                id="caster", name="Caster", type="player", initiative=10, hp_current=20, hp_max=20, ac=14
            ),
            CombatParticipant(id="enemy", name="Enemy", type="enemy", initiative=5, hp_current=12, hp_max=12, ac=12),
        ],
        initiative_order=["ally", "caster", "enemy"],
        round_number=1,
        current_turn_index=0,
        location_id="accord_guild_hall",
        beat="resolution",
        pending_declarations={
            "ally": {"type": "attack", "action": "Sword", "target_id": "enemy"},
            "caster": {"type": "ability", "action": "arcane_fireball", "target_id": "enemy"},
        },
    )
    deps = _resolve_deps(damage=4)
    rows = {
        "ally": _player("warrior"),
        "caster": {**_player("skirmisher"), "player_id": "caster"},
    }
    deps["queries"].get_player = AsyncMock(side_effect=lambda player_id, **_: rows[player_id])
    cast_resolver = MagicMock()
    cast_resolver._gate_spell = spell_casting._gate_spell
    cast_resolver._resolve_cast = AsyncMock(
        return_value=spell_casting.CastResult(
            packet={"effect": "fire"},
            new_resonance=None,
            concentration_spell_id=spell_casting._UNCHANGED,
            generated=0,
            events=[],
        )
    )

    with patch.object(character_spells, "get_known", new=AsyncMock(return_value=[])):
        with pytest.raises(ToolError, match="arcane_fireball isn't a spell you know"):
            await _resolve_round(ctx, cast_resolver=cast_resolver, **deps)

    enemy = ctx.userdata.combat_state.get_participant("enemy")
    assert enemy is not None
    assert enemy.hp_current == 12
    deps["mutations"].update_player_hp.assert_not_called()


@pytest.mark.asyncio
async def test_combat_prevalidation_reads_a_players_library_once_for_two_spells():
    session = make_context(player_id="caster").userdata
    state = CombatState(
        combat_id="story_052_cache",
        participants=[
            CombatParticipant(id="caster", name="Caster", type="player", initiative=10, hp_current=20, hp_max=20, ac=14)
        ],
        initiative_order=["caster"],
    )
    adv = SimpleNamespace(
        packets=[
            SimpleNamespace(actor_id="caster", declaration=Declaration(type=DeclarationType.ABILITY, action=action))
            for action in ("arcane_bolt", "arcane_fireball")
        ]
    )
    player = {**_player("mage"), "player_id": "caster"}
    queries = MagicMock(get_player=AsyncMock(return_value=player))
    library = MagicMock(get_known=AsyncMock(return_value=[{"spell_id": "arcane_fireball"}]))

    await _prevalidate_ability_focus(
        session,
        state,
        adv,
        conn=object(),
        queries=queries,
        cast_resolver=spell_casting,
        character_spells_mod=library,
    )

    library.get_known.assert_awaited_once()


@pytest.mark.asyncio
async def test_abilities_query_emits_exactly_the_real_gate_set(dev_db_pool):
    player_id = "story_052_query_cleric"
    data = _player("cleric") | {"player_id": player_id}
    await dev_db_pool.execute("DELETE FROM players WHERE player_id = $1", player_id)
    await dev_db_pool.execute(
        "INSERT INTO players (player_id, data) VALUES ($1, $2::jsonb)", player_id, json.dumps(data)
    )
    await character_spells.record_learned(player_id, "divine_revivify", "discovery", conn=dev_db_pool)
    ctx = make_context(player_id=player_id)

    try:
        payload = json.loads(await _query_info_impl(ctx, kind="abilities"))
        emitted = {row["id"] for row in payload["spells"]}
        known = spell_knowledge.castable_spell_ids("cleric", ["divine_revivify"])
        accepted = set()
        for source in ("arcane", "divine", "primal"):
            for spell in spells.get_spells_by_source(source):
                try:
                    spell_casting._gate_spell(data, spell.id, known)
                except ToolError:
                    continue
                accepted.add(spell.id)

        assert emitted == {"divine_heal_wounds", "divine_revivify", "divine_sacred_flame"}
        assert emitted == accepted
        row = next(row for row in payload["spells"] if row["id"] == "divine_revivify")
        assert row == {"id": "divine_revivify", "name": "Revivify", "tier": "major", "focus_cost": 5}
    finally:
        await dev_db_pool.execute("DELETE FROM players WHERE player_id = $1", player_id)
