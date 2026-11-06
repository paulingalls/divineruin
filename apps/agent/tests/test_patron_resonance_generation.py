"""Patron generation through activate and the shared transactional casting path."""

import json
from contextlib import asynccontextmanager
from dataclasses import replace
from functools import partial
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from sample_fixtures import make_context, make_db_mod

import spell_casting
import spells
from activate_tools import _activate_impl


async def cast(
    patron,
    spell_id="arcane_fireball",
    *,
    spell=None,
    terrain="forest",
    ward=False,
    target_id=None,
    target_ids=None,
    rows=None,
    visit=None,
    corruption=0,
    race=None,
    ctx=None,
    database=None,
    connection=None,
    favor=True,
    **facts,
):
    ctx = ctx or make_context()
    player_id = ctx.userdata.acting_player_id
    caster = ctx.userdata.member_state(player_id)
    caster.resonance.current = 5
    caster.corruption_level = corruption
    spell = spell or spells.get_spell(spell_id)
    row = {
        "player_id": player_id,
        "class": {"arcane": "mage", "divine": "cleric", "primal": "druid"}[spell.source],
        "level": 20,
        "focus": {"current": 50},
        "divine_favor": {"patron": patron},
        "race": race,
    }
    if not favor:
        row.pop("divine_favor")
    if isinstance(favor, dict):
        row["divine_favor"] = favor
    table = {player_id: row, **(rows or {})}
    queries = MagicMock(
        get_player=AsyncMock(side_effect=lambda pid, **kw: table.get(pid)),
        get_players_for_update=AsyncMock(
            side_effect=lambda ids, **kw: {pid: table[pid] for pid in ids if pid in table}
        ),
    )
    if database is None:
        database, conn = make_db_mod()
        conn.fetchrow = AsyncMock(return_value=visit)
    else:
        conn = connection
    persistence = MagicMock(update_player_resources=AsyncMock())
    mutations = MagicMock(update_player_resonance=AsyncMock())
    events = MagicMock(publish_resonance_changed=AsyncMock())
    catalog = (
        spells
        if spell is spells.get_spell(spell.id)
        else MagicMock(wraps=spells, get_spell=MagicMock(return_value=spell))
    )
    entry = partial(
        spell_casting._cast_spell_impl,
        db_mod=database,
        queries_mod=queries,
        content_mod=MagicMock(get_location_terrain=AsyncMock(return_value=terrain)),
        persistence_mod=persistence,
        resonance_mutations_mod=mutations,
        resonance_events_mod=events,
        spells_mod=catalog,
        concentration_mutations_mod=MagicMock(update_player_concentration=AsyncMock()),
        character_spells_mod=MagicMock(get_known=AsyncMock(return_value=[{"spell_id": spell.id}])),
        ward_resolution_mod=MagicMock(resolve_scope_ward=AsyncMock(return_value={} if ward else None)),
        **facts,
    )
    try:
        raw = await _activate_impl(
            ctx,
            spell.id,
            target_id=target_id,
            target_ids=target_ids,
            spells_mod=catalog,
            cast_spell_mod=MagicMock(_cast_spell_impl=entry),
        )
    except Exception:
        persistence.update_player_resources.assert_not_awaited()
        mutations.update_player_resonance.assert_not_awaited()
        events.publish_resonance_changed.assert_not_awaited()
        raise
    packet = json.loads(raw)
    generated = packet["resonance_generated"]
    if spell.focus_cost:
        persistence.update_player_resources.assert_awaited_once_with(player_id, focus=50 - spell.focus_cost, conn=conn)
    if generated:
        mutations.update_player_resonance.assert_awaited_once_with(player_id, 4 + generated, conn=conn)
        assert caster.resonance.current == 4 + generated
        events.publish_resonance_changed.assert_awaited_once()
    else:
        mutations.update_player_resonance.assert_not_awaited()
        events.publish_resonance_changed.assert_not_awaited()
        assert caster.resonance.current == 5
    return packet


@pytest.mark.parametrize(
    "spell_id,expected", [("arcane_fireball", 2), ("arcane_haste", 2), ("arcane_bolt", 0), ("arcane_detect_magic", 1)]
)
async def test_kaelen(spell_id, expected):
    packet = await cast("kaelen", spell_id)
    assert packet["resonance_generated"] == expected
    standard = await cast(None, spell_id)
    if expected != standard["resonance_generated"]:
        assert packet["patron_resonance"] == {
            "patron": "kaelen",
            "applies_to": ["combat_aid"],
            "standard": standard["resonance_generated"],
            "generated": expected,
        }
    else:
        assert "patron_resonance" not in packet
    assert "patron_resonance" not in standard


@pytest.mark.parametrize(
    "patron,spell_id,kwargs,expected",
    [
        ("thyra", "primal_blight", {"terrain": "forest"}, 2),
        ("thyra", "primal_blight", {"terrain": "farmland"}, 5),
        ("thyra", "primal_blight", {"terrain": "ancient_forest"}, 0),
        ("thyra", "arcane_fireball", {}, 2),
        ("thyra", "arcane_detect_magic", {}, 0),
        ("orenthel", "divine_heal_wounds", {"corruption": 2}, 0),
        ("orenthel", "primal_healing_touch", {"corruption": 2}, 0),
        ("mortaen", "arcane_magic_missile", {"target_id": "ally", "rows": {"ally": {"hp": {"current": 0}}}}, 0),
        ("nythera", "arcane_fireball", {"visit": {"data": {"connections": []}}}, 2),
    ],
)
async def test_other_patron_casts(patron, spell_id, kwargs, expected):
    if spell_id == "primal_blight":
        kwargs = {**kwargs, "spell": replace(spells.get_spell(spell_id), resonance_by_source={"primal": 6})}
    packet = await cast(patron, spell_id, **kwargs)
    assert packet["resonance_generated"] == expected
    standard = await cast(None, spell_id, **kwargs)
    assert packet["patron_resonance"]["standard"] == standard["resonance_generated"]
    assert packet["patron_resonance"]["generated"] == expected
    assert packet["patron_resonance"]["patron"] == patron
    assert "patron_resonance" not in standard


@pytest.mark.parametrize(
    "patron,fact,spell_id,expected",
    [
        ("syrath", "is_concealed", "arcane_fireball", 1),
        ("syrath", "is_concealed", "arcane_magic_missile", 0),
        ("valdris", "target_wronged_caster", "arcane_disintegrate", 2),
        ("valdris", "target_wronged_caster", "arcane_haste", 1),
    ],
)
async def test_explicit_producer_handoff(patron, fact: str, spell_id, expected):
    facts: dict[str, Any] = {fact: True}
    packet = await cast(patron, spell_id, target_id="enemy", **facts)
    assert packet["resonance_generated"] == expected
    facts[fact] = False
    standard = await cast(patron, spell_id, target_id="enemy", **facts)
    assert packet["patron_resonance"]["standard"] == standard["resonance_generated"]
    assert "patron_resonance" not in standard


@pytest.mark.parametrize(
    "patron,spell_id,kwargs",
    [
        ("kaelen", "arcane_hold_person", {}),
        ("kaelen", "divine_zone_of_truth", {}),
        ("thyra", "primal_blight", {"terrain": "city"}),
        ("thyra", "arcane_fireball", {"terrain": "village"}),
        ("orenthel", "divine_greater_restoration", {}),
        ("orenthel", "divine_dispel_corruption", {}),
        ("orenthel", "arcane_fireball", {}),
        ("mortaen", "arcane_magic_missile", {"target_id": "ally", "rows": {"ally": {"hp": {"current": 1}}}}),
        ("mortaen", "arcane_magic_missile", {"target_id": "unknown"}),
        ("mortaen", "arcane_magic_missile", {}),
        ("nythera", "arcane_fireball", {"visit": {"data": {"revisited": True}}}),
        ("nythera", "arcane_fireball", {}),
        ("valdris", "arcane_fireball", {"target_id": "enemy", "target_wronged_caster": True}),
        ("valdris", "arcane_haste", {"target_wronged_caster": True}),
    ],
)
async def test_unmet_predicate(patron, spell_id, kwargs):
    packet = await cast(patron, spell_id, **kwargs)
    standard = await cast(None, spell_id, **kwargs)
    assert packet["resonance_generated"] == standard["resonance_generated"]
    assert "patron_resonance" not in packet


@pytest.mark.parametrize(
    "spell_id,kwargs",
    [
        ("arcane_magic_missile", {"ward": False}),
        ("arcane_fireball", {"ward": True}),
        ("arcane_bolt", {"corruption": 2}),
    ],
)
async def test_kaelen_final_floor(spell_id, kwargs):
    assert (await cast("kaelen", spell_id, **kwargs))["resonance_generated"] == 0


@pytest.mark.parametrize("patron", [None, "none"])
@pytest.mark.parametrize("spell_id", ["arcane_fireball", "divine_heal_wounds", "primal_healing_touch"])
async def test_unbound(patron, spell_id):
    kwargs: dict[str, Any] = dict(
        target_id="ally",
        rows={"ally": {"hp": {"current": 0}}},
        visit={"data": {}},
        is_concealed=True,
        target_wronged_caster=True,
    )
    packet = await cast(patron, spell_id, **kwargs)
    standard = await cast(None, spell_id, favor=False, **kwargs)
    assert packet == standard
    assert "patron_resonance" not in packet


async def test_thyra_korath_ward_order():
    spell = replace(spells.get_spell("primal_blight"), resonance_by_source={"primal": 6})
    packet = await cast("thyra", spell=spell, race="korath", ward=True)
    assert packet["resonance_generated"] == 0
    assert packet["patron_resonance"]["standard"] == 2


@pytest.mark.parametrize("terrain,catalog", [(None, True), ("forest", False)])
async def test_thyra_refuses_before_spend(terrain, catalog):
    from livekit.agents.llm import ToolError

    spell = spells.get_spell("primal_blight")
    if not catalog:
        spell = replace(spell, resonance_by_source={})
    with pytest.raises(ToolError, match=r"terrain|catalog generation"):
        await cast("thyra", spell=spell, terrain=terrain)


async def test_nythera_arrival_revisit_and_member_history(dev_db_pool):
    import db_mutations
    import movement_tools

    ids = [f"patron_{uuid4().hex}" for _ in range(2)]
    ctx = make_context(player_id=ids[0], party_member_ids=ids)
    async with dev_db_pool.acquire() as conn:
        transaction = conn.transaction()
        await transaction.start()
        try:
            for pid in ids:
                await conn.execute("INSERT INTO players (player_id, data) VALUES ($1, '{}'::jsonb)", pid)
            await db_mutations.upsert_map_progress(ids[1], "first_stop", ["elsewhere"], conn=conn)

            @asynccontextmanager
            async def scope():
                async with conn.transaction():
                    yield conn

            database = MagicMock(transaction=scope, extract_exit_connections=lambda exits: list(exits))
            mutations = MagicMock(
                update_player_location=AsyncMock(), upsert_map_progress=db_mutations.upsert_map_progress
            )

            async def arrive(destination):
                with patch.object(
                    movement_tools.ward_resolution,
                    "resolve_scope_ward_with_scope",
                    AsyncMock(return_value=(None, None)),
                ):
                    await movement_tools.apply_arrival(
                        ctx.userdata,
                        destination,
                        {},
                        db_mod=database,
                        mutations=mutations,
                        travel_mutations=MagicMock(update_player_travel_state=AsyncMock()),
                    )

            async def generation():
                return (await cast("nythera", ctx=ctx, database=database, connection=conn))["resonance_generated"]

            await arrive("first_stop")
            assert await generation() == 2
            other_ctx = make_context(player_id=ids[1], location_id="first_stop")
            other = await cast("nythera", ctx=other_ctx, database=database, connection=conn)
            assert other["resonance_generated"] == 3
            assert "patron_resonance" not in other
            await arrive("first_stop")
            assert await generation() == 2
            await arrive("elsewhere")
            await arrive("first_stop")
            assert await generation() == 3
            data = json.loads(
                await conn.fetchval(
                    "SELECT data FROM player_map_progress WHERE player_id=$1 AND location_id='first_stop'", ids[0]
                )
            )
            assert data == {"connections": [], "revisited": True}
        finally:
            await transaction.rollback()


@pytest.mark.parametrize(
    "patron,spell_id,damage,expected",
    [
        ("kaelen", "arcane_fireball", 1, 2),
        ("kaelen", "arcane_detect_magic", 1, 1),
        ("mortaen", "arcane_magic_missile", 7, 0),
        ("mortaen", "arcane_magic_missile", 6, 1),
    ],
)
async def test_declared_nonprimary_cast_uses_working_targets(patron, spell_id, damage, expected):
    from combat._helpers import _make_combat_state, _resolve_deps
    from voice_condition_fixtures import place_actors

    import combat_turn
    from session_data import CombatParticipant

    ctx = make_context(party_member_ids=["player_1", "caster_2"])
    state = _make_combat_state()
    state.participants.append(
        CombatParticipant(id="caster_2", name="Caster", type="player", initiative=13, hp_current=20, hp_max=20, ac=12)
    )
    state.initiative_order = ["player_1", "caster_2", "goblin_scout_1"]
    ctx.userdata.combat_state = place_actors(state)
    ctx.userdata.member_state("caster_2").resonance.current = 5
    ctx.userdata.patron_id = "orenthel"
    deps = _resolve_deps(damage)
    row = {
        "player_id": "caster_2",
        "class": "mage",
        "level": 20,
        "focus": {"current": 50},
        "divine_favor": {"patron": patron},
    }
    deps["queries"].get_player = AsyncMock(return_value=row)
    library = MagicMock(get_known=AsyncMock(return_value=[{"spell_id": spell_id}]))
    deps["character_spells_mod"] = library
    persistence = MagicMock(update_player_resources=AsyncMock())
    mutations = MagicMock(update_player_resonance=AsyncMock())
    deps["cast_resolver"] = MagicMock(
        _gate_spell=spell_casting._gate_spell,
        _resolve_cast=partial(
            spell_casting._resolve_cast,
            queries_mod=deps["queries"],
            character_spells_mod=library,
            persistence_mod=persistence,
            resonance_mutations_mod=mutations,
            concentration_mutations_mod=MagicMock(update_player_concentration=AsyncMock()),
        ),
    )
    await combat_turn._declare_phase_impl(
        ctx,
        {
            "player_1": {"type": "attack", "action": "Longsword", "target_id": "goblin_scout_1"},
            "caster_2": {"type": "ability", "action": spell_id, "target_id": "goblin_scout_1"},
            "goblin_scout_1": {"type": "defend"},
        },
        mutations=deps["mutations"],
    )
    raw = await combat_turn._resolve_phase_impl(ctx, **deps)
    assert isinstance(raw, str)
    payload = json.loads(raw)
    packet = next(p for p in payload["packets"] if p["actor_id"] == "caster_2")
    assert packet["cast"]["resonance_generated"] == expected
    assert ctx.userdata.resonance.current == 0
    assert ctx.userdata.member_state("caster_2").resonance.current == (5 + expected if expected else 5)
    assert persistence.update_player_resources.await_args.args[0] == "caster_2"
    if expected == 0:
        mutations.update_player_resonance.assert_not_awaited()


@pytest.mark.parametrize(
    "patron,hps,expected",
    [
        ("mortaen", [0, 0], 0),
        ("mortaen", [0, 1], 1),
        ("mortaen", [0, None], 1),
        ("valdris", [0, 0], 1),
    ],
)
async def test_all_targets_must_qualify(patron, hps, expected):
    spell = replace(spells.get_spell("arcane_magic_missile"), max_targets=3)
    rows = {pid: {"hp": {"current": hp}} for pid, hp in zip(["a", "b"], hps, strict=True)}
    packet = await cast(patron, spell=spell, target_ids=["a", "b", "a"], rows=rows, target_wronged_caster=True)
    assert packet["resonance_generated"] == expected
    assert ("patron_resonance" in packet) == (expected == 0)


@pytest.mark.parametrize("spell_id", ["divine_revivify", "divine_resurrection", "primal_regenerate"])
async def test_orenthel_hp_restoration_includes_revival(spell_id):
    packet = await cast("orenthel", spell_id, corruption=2)
    assert packet["resonance_generated"] == 0
    assert packet["patron_resonance"]["standard"] > 0


async def test_nythera_positive_to_zero():
    packet = await cast("nythera", "arcane_detect_magic", visit={"data": {}})
    assert packet["resonance_generated"] == 0
    assert packet["patron_resonance"]["standard"] == 1


@pytest.mark.parametrize("favor", [{}, {"patron": None}, {"patron": "none"}])
async def test_missing_patron(favor):
    packet = await cast(None, favor=favor)
    assert packet["resonance_generated"] == 3
    assert "patron_resonance" not in packet


async def test_unknown_patron_refuses():
    from livekit.agents.llm import ToolError

    with pytest.raises(ToolError, match="Unknown patron"):
        await cast("unregistered")


async def test_kaelen_floor_after_corruption():
    spell = replace(spells.get_spell("arcane_fireball"), resonance_by_source={"arcane": 0})
    packet = await cast("kaelen", spell=spell, corruption=1)
    assert packet["resonance_generated"] == 0
    assert packet["patron_resonance"]["standard"] == 1
