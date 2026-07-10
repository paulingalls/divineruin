"""Capstone: M25 Phase-5 verb consolidation, end-to-end.

Three merged stories folded five capability tools into one polymorphic ``activate(id)``
verb: story-001 built the dispatcher (``activate_tools.activate`` / ``_activate_impl``),
story-002 wired it onto combat and demoted ``cast_spell``, ``request_ability_activation``,
``activate_veil_ward``, ``inner_fire``, and story-003 wired it onto exploration and demoted
``deploy_veil_anchor``. Each per-story review passed independently; this capstone is the
integration net those reviews cannot see — it proves the ASSEMBLED whole holds: the verb is
registered where it should be (and nowhere the folded nouns still are), the tool-count budget
holds, and all five capability kinds route correctly through one real-PG seeded testcontainer
(auto-marked ``acceptance`` by tests/acceptance/conftest.py).

No production code changes — every symbol here is owned by the three merged stories.
"""

from __future__ import annotations

import json

from acceptance.seeds import _set_race, seed_player_with_pools
from sample_fixtures import make_context, make_mock_room, published_payloads

import db
import db_mutations
import db_mutations_resonance
import db_queries
import event_types as E
import spells
from activate_tools import _activate_impl
from blacksmith_agent import BLACKSMITH_TOOLS
from combat_agent import COMBAT_AGENT_TOOLS
from creation_agent import CREATION_TOOLS
from dispatch_agent import DISPATCH_TOOLS
from exploration_agent import EXPLORATION_TOOLS
from llm_config import MAX_STRICT_TOOLS
from onboarding_agent import ONBOARDING_TOOLS
from session_data import CombatParticipant, CombatState

_FOLDED_NOUNS = frozenset(
    {
        "cast_spell",
        "request_ability_activation",
        "activate_veil_ward",
        "inner_fire",
        "deploy_veil_anchor",
    }
)

_ALL_AGENT_TOOLS = {
    "combat": COMBAT_AGENT_TOOLS,
    "exploration": EXPLORATION_TOOLS,
    "dispatch": DISPATCH_TOOLS,
    "onboarding": ONBOARDING_TOOLS,
    "creation": CREATION_TOOLS,
    "blacksmith": BLACKSMITH_TOOLS,
}


def test_activate_registered_on_combat_and_exploration_folded_nouns_gone_everywhere() -> None:
    """The highest-value catch: activate must be on combat + exploration, and none of the five
    folded wrappers may still be registered on ANY of the six agents."""
    assert any(t.__name__ == "activate" for t in COMBAT_AGENT_TOOLS)
    assert any(t.__name__ == "activate" for t in EXPLORATION_TOOLS)

    for agent_name, tools in _ALL_AGENT_TOOLS.items():
        names = {t.__name__ for t in tools}
        leaked = names & _FOLDED_NOUNS
        assert not leaked, f"{agent_name} still registers folded nouns: {leaked}"


def test_tool_budget_holds_exact_counts() -> None:
    """Exact counts pin the fold's tool-ceiling win — a regression here silently re-inflates
    the strict tool budget the fold exists to protect."""
    assert len(COMBAT_AGENT_TOOLS) == 11
    assert len(COMBAT_AGENT_TOOLS) <= MAX_STRICT_TOOLS - 4

    assert len(EXPLORATION_TOOLS) == 18
    assert len(EXPLORATION_TOOLS) <= MAX_STRICT_TOOLS - 2


async def _focus_current(player_id: str) -> int:
    player = await db_queries.get_player(player_id, conn=await db.get_pool())
    assert player is not None
    return player["focus"]["current"]


async def test_activate_routes_a_spell_id_and_accrues_resonance(reset_db_pool: str) -> None:
    """Kind 1/5: a content spell id routes to _cast_spell_impl — Focus deducts, Resonance
    accrues and persists (mirrors test_m33_casting_capstone)."""
    pool = await db.get_pool()
    player_id = "cap_m25_activate_spell"
    try:
        await seed_player_with_pools(pool, player_id=player_id, focus_current=18)
        await spells.load_spells()
        spell = spells.get_spell("arcane_fireball")
        expected_gen = spell.resonance_by_source[spell.source]

        await _activate_impl(make_context(player_id), "arcane_fireball")

        assert await _focus_current(player_id) == 18 - spell.focus_cost
        persisted = await db_mutations_resonance.read_player_resonance(player_id, conn=pool)
        assert persisted["current"] == expected_gen
    finally:
        await pool.execute("DELETE FROM players WHERE player_id = $1", player_id)


async def test_activate_routes_an_ability_id_and_deducts_stamina(reset_db_pool: str) -> None:
    """Kind 2/5: a content ability id routes to _request_ability_activation_impl — real Stamina
    deducts (mirrors test_story_005_m22_ability_capstone)."""
    import abilities

    pool = await db.get_pool()
    player_id = "cap_m25_activate_ability"
    try:
        await seed_player_with_pools(pool, player_id=player_id, class_="warrior")
        await abilities.load_abilities()

        raw = await _activate_impl(make_context(player_id), "warrior_devastating_strike")
        result = json.loads(raw)
        assert result["deducted"] == {"stamina": 3, "focus": 0}

        player = await db_queries.get_player(player_id)
        assert player is not None
        assert player["stamina"]["current"] == 7
    finally:
        await pool.execute("DELETE FROM players WHERE player_id = $1", player_id)


async def test_activate_routes_the_reserved_inner_fire_token(reset_db_pool: str) -> None:
    """Kind 3/5: the id-less reserved token 'draethar_inner_fire' routes to _inner_fire_impl in
    combat — Resonance drops by 3 and 1d6 self fire damage applies (mirrors test_m34)."""
    import racial_resonance

    pool = await db.get_pool()
    player_id = "cap_m25_activate_inner_fire"
    try:
        await seed_player_with_pools(pool, player_id=player_id, focus_current=18)
        await _set_race(pool, player_id, "draethar")
        await spells.load_spells()
        await racial_resonance.load_racial_resonance()

        ctx = make_context(player_id)
        ctx.userdata.resonance.current = 9  # already at Overreach — no cast needed for this seam
        ctx.userdata.combat_state = CombatState(
            combat_id="cap_m25_inner_fire_combat",
            participants=[
                CombatParticipant(
                    id=player_id, name="Pyre", type="player", initiative=14, hp_current=28, hp_max=28, ac=14
                ),
                CombatParticipant(
                    id="hollow_1", name="Hollow", type="enemy", initiative=8, hp_current=9, hp_max=9, ac=12
                ),
            ],
            initiative_order=[player_id, "hollow_1"],
        )

        fire = json.loads(await _activate_impl(ctx, "draethar_inner_fire"))
        assert fire["resonance_reduced"] == 3
        assert 1 <= fire["fire_damage"] <= 6

        persisted = await db_mutations_resonance.read_player_resonance(player_id, conn=pool)
        assert persisted["current"] == 6
    finally:
        await pool.execute("DELETE FROM players WHERE player_id = $1", player_id)


async def test_activate_routes_an_anchor_item_id_and_writes_a_location_ward(reset_db_pool: str) -> None:
    """Kind 4/5: a carried Veil Anchor item id routes to _deploy_veil_anchor_impl in exploration
    — writes a location-scope veil_wards row, decrements inventory (mirrors test_m24)."""
    pool = await db.get_pool()
    player_id = "cap_m25_activate_anchor"
    location_id = "cap_m25_activate_anchor_hall"
    try:
        await seed_player_with_pools(pool, player_id=player_id, focus_current=10)
        await db_mutations.add_inventory_item(player_id, "veil_ward_anchor_small", 1, conn=pool)

        room = make_mock_room()
        ctx = make_context(player_id, location_id=location_id, room=room)

        raw = await _activate_impl(ctx, "veil_ward_anchor_small")
        result = json.loads(raw)
        assert result["active"] is True
        assert result["source"] == "artificer"

        row = await pool.fetchrow("SELECT source FROM veil_wards WHERE scope_id = $1", location_id)
        assert row is not None
        assert row["source"] == "artificer"

        ward_events = [p for p in published_payloads(room) if p["type"] == E.VEIL_WARD_CHANGED]
        assert len(ward_events) == 1

        slot = await db_queries.get_inventory_item(player_id, "veil_ward_anchor_small", conn=pool)
        assert slot is None or slot["quantity"] == 0
    finally:
        await pool.execute("DELETE FROM veil_wards WHERE scope_id = $1", location_id)
        await pool.execute("DELETE FROM players WHERE player_id = $1", player_id)


async def test_activate_routes_the_reserved_veil_ward_token_ooc(reset_db_pool: str) -> None:
    """Kind 5/5: the id-less reserved token 'veil_ward' routes to _activate_veil_ward_impl OOC
    in exploration (combat_state is None) — a cleric level 7 raises a location-scope ward
    (mirrors test_exploration_collapse's OOC ward test)."""
    pool = await db.get_pool()
    player_id = "cap_m25_activate_ward_ooc"
    location_id = "cap_m25_activate_ward_hall"
    try:
        await seed_player_with_pools(pool, player_id=player_id, class_="cleric", focus_current=20)
        await pool.execute(
            "UPDATE players SET data = jsonb_set(data, '{level}', $2::jsonb) WHERE player_id = $1",
            player_id,
            json.dumps(7),  # WARD_SOURCES gates cleric at level 7
        )

        room = make_mock_room()
        ctx = make_context(player_id, location_id=location_id, room=room)
        assert ctx.userdata.combat_state is None

        raw = await _activate_impl(ctx, "veil_ward")
        result = json.loads(raw)
        assert result["active"] is True
        assert result["scope"] == "location"

        row = await pool.fetchrow("SELECT source, dismissible FROM veil_wards WHERE scope_id = $1", location_id)
        assert row is not None
        assert row["source"] == "cleric"
        assert row["dismissible"] is True

        ward_events = [p for p in published_payloads(room) if p["type"] == E.VEIL_WARD_CHANGED]
        assert len(ward_events) == 1
        assert ward_events[0]["scope_id"] == location_id
    finally:
        await pool.execute("DELETE FROM veil_wards WHERE scope_id = $1", location_id)
        await pool.execute("DELETE FROM players WHERE player_id = $1", player_id)
