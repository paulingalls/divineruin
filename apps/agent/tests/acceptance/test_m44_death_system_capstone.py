"""Capstone: M4.4 death/dying/resurrection end-to-end against a real Postgres testcontainer.

Stories 001-008 shipped the pieces: the death-cost tier engine + persisted history (001), the
instant-death verdict + companion auto-stabilize (002), the resurrection loop + 4-tier anchor
(003), the party-wipe engine + Mortaen patron bonus/waive (004), the combat-START condition load
(005), the Hollowed-death clear + hollow_killed flag (007), and the Temporary Hollowed combat
ride-along (008). This capstone proves they COMPOSE on ONE seeded testcontainer (auto-marked
`acceptance` by tests/acceptance/conftest.py), driving the REAL entry points — the combat death
mechanic (combat_support._resolve_attack_packet), the pure Beat-4 wrap (combat_phase._wrap), the
defeat router (combat_end._end_combat_db), the party-wipe engine (resurrection), and the
combat-START load (combat_init._start_combat_impl) — against real PostgreSQL.

Determinism: the only seam patched is the d20 (check_resolution.dice_roll). Lethality/overkill is
forced by injecting an AttackResult through the _resolve_attack_packet(resolver=...) seam and by
setting hp_current directly — attack DAMAGE rolls go through the separate
check_resolution_attack.dice_roll, NOT the d20 seam. Each test uses a distinct player_id / combat_id
since the testcontainer DB is shared.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from sample_fixtures import make_context, make_mock_room

import combat_end
import combat_init
import combat_phase
import combat_support
import conditions
import db
import db_mutations
import db_mutations_resurrection as dmr
import db_queries
import resurrection
from check_resolution_attack import AttackResult
from combat_events import EventSink
from session_data import CombatParticipant, CombatState

_ATTRS = {
    "strength": 14,
    "dexterity": 12,
    "constitution": 13,
    "intelligence": 11,
    "wisdom": 10,
    "charisma": 8,  # the lowest attribute — where a "lowest"-target death cost lands
}

# Players die at the off-catalog `off_catalog_wilds` (absent from the seeded locations), so the
# resurrection anchor falls all the way through to tier-4: the seeded `starting_area`-tagged
# location. Pin the concrete id so a future catalog retag can't silently shift the anchor and have
# these tests still pass on the looser `== dc["anchor"]` self-consistency check.
_STARTER_ZONE = "accord_market_square"


async def _seed_player(pool, player_id: str, **overrides) -> None:
    """Upsert a fully-specified players.data row (the default seed_player lacks death_history /
    conditions / divine_favor). Off-catalog location so the resurrection anchor falls to the
    deterministic starter zone (tier-4)."""
    data = {
        "player_id": player_id,
        "class": "warrior",
        "level": 5,
        "attributes": dict(_ATTRS),
        "hp": {"current": 0, "max": 40},
        "maxhp_override": 0,
        "location_id": "off_catalog_wilds",
        "death_history": {"count": 0, "costs": []},
    }
    data.update(overrides)
    await pool.execute(
        "INSERT INTO players (player_id, data) VALUES ($1, $2::jsonb) "
        "ON CONFLICT (player_id) DO UPDATE SET data = $2::jsonb",
        player_id,
        json.dumps(data),
    )


def _terminal_state(combat_id: str, player: CombatParticipant, enemy: CombatParticipant) -> CombatState:
    return CombatState(
        combat_id=combat_id,
        participants=[player, enemy],
        initiative_order=[player.id, enemy.id],
        round_number=1,
        current_turn_index=0,
        location_id="off_catalog_wilds",
        beat="wrap",
    )


def _overkill_resolver(target: CombatParticipant):
    """A resolve_attack stand-in that lands an instant-death overkill blow (overkill >= hp_max)."""
    result = AttackResult(
        hit=True,
        roll=15,
        attack_modifier=3,
        attack_total=18,
        target_ac=target.ac,
        damage=target.hp_max * 3,
        damage_type="slashing",
        target_hp_remaining=0,
        target_killed=True,
        overkill=target.hp_max * 2,
        narrative_hint="A killing blow.",
    )
    resolver = MagicMock()
    resolver.resolve_attack = MagicMock(return_value=result)
    return resolver


# --- Scenario A: death -> tiered cost -> Mortaen anchor -> persisted history (AC1) ---


async def test_defeat_applies_tiered_cost_and_revives_at_anchor(reset_db_pool: str) -> None:
    pool = await db.get_pool()
    player_id = "cap_m44_a"
    await _seed_player(pool, player_id, death_history={"count": 1, "costs": []})  # next death = #2 (moderate)
    ctx = make_context(player_id, location_id="off_catalog_wilds", room=make_mock_room())

    player = CombatParticipant(
        id=player_id,
        name="Kael",
        type="player",
        initiative=15,
        hp_current=0,
        hp_max=40,
        ac=14,
        is_fallen=True,
        is_dead=True,
    )
    enemy = CombatParticipant(
        id="goblin_a",
        name="Goblin",
        type="enemy",
        initiative=12,
        hp_current=7,
        hp_max=7,
        ac=10,
        xp_value=50,
        is_fallen=True,
    )
    cs = _terminal_state("combat_cap_m44_a", player, enemy)
    await db_mutations.save_combat_state(cs.combat_id, cs.to_dict(), conn=pool)
    ctx.userdata.combat_state = cs

    end_data = await combat_end._end_combat_db(
        ctx.userdata, cs, "defeat", mutations=db_mutations, queries=db_queries, conn=pool, sink=EventSink()
    )
    dc = end_data["death_context"]
    assert dc["tier"] == "moderate" and dc["death_count"] == 2
    assert dc["attribute_delta"] == -1 and dc["attribute"] is not None

    revived = await db_queries.get_player(player_id, conn=pool)
    assert revived is not None
    assert revived["death_history"]["count"] == 2  # recorded
    assert revived["attributes"][dc["attribute"]] == _ATTRS[dc["attribute"]] - 1  # cost persisted
    assert dc["anchor"] == _STARTER_ZONE  # off-catalog death -> tier-4 starter zone
    assert revived["location_id"] == dc["anchor"]  # revived at the resolved anchor
    assert revived["hp"]["current"] == dc["revive_hp"]  # clamped to effective max


# --- Scenario B: instant-death + companion auto-stabilize (AC2) ---


async def test_overkill_instant_death_and_companion_auto_stabilizes(reset_db_pool: str) -> None:
    pool = await db.get_pool()
    player_id = "cap_m44_b"
    await _seed_player(pool, player_id)
    ctx = make_context(player_id, location_id="off_catalog_wilds", room=make_mock_room())

    player = CombatParticipant(id=player_id, name="Kael", type="player", initiative=15, hp_current=12, hp_max=40, ac=14)
    companion = CombatParticipant(
        id="ally_1",
        name="Sable",
        type="companion",
        initiative=14,
        hp_current=0,
        hp_max=20,
        ac=12,
        is_fallen=True,
        death_save_failures=combat_phase._DEATH_SAVE_LIMIT,
    )
    enemy = CombatParticipant(
        id="goblin_a",
        name="Goblin",
        type="enemy",
        initiative=12,
        hp_current=7,
        hp_max=7,
        ac=10,
        action_pool=[{"name": "Scimitar", "damage": "1d6"}],
    )
    cs = CombatState(
        combat_id="combat_cap_m44_b",
        participants=[player, companion, enemy],
        initiative_order=[player_id, "ally_1", "goblin_a"],
        round_number=1,
        current_turn_index=0,
        location_id="off_catalog_wilds",
        beat="resolution",
    )
    ctx.userdata.combat_state = cs

    assert player.is_dead is False  # pin the pre-attack state so the transition is real, not vacuous
    # The enemy lands an overkill blow on the player -> instant death (the REAL mechanic).
    await combat_support._resolve_attack_packet(
        ctx.userdata,
        enemy,
        enemy.action_pool[0],
        player,
        mutations=db_mutations,
        queries=db_queries,
        resolver=_overkill_resolver(player),
        conn=pool,
        sink=EventSink(),
    )
    assert player.is_dead is True

    wrap = combat_phase._wrap(cs)
    assert player_id not in wrap.death_saves_due  # instant-dead skips the death-save grind
    assert companion.death_save_failures == combat_phase._DEATH_SAVE_LIMIT - 1  # auto-stabilized
    assert companion.death_save_successes == combat_phase._STABILIZE_LIMIT
    assert wrap.combat_ended is True and wrap.outcome == "defeat"


# --- Scenario C: party wipe + Mortaen patron (AC3) — the real-PG gap ---


async def test_party_wipe_waives_patron_first_death_others_pay(reset_db_pool: str) -> None:
    pool = await db.get_pool()
    patron_id, payer_id = "cap_m44_c_patron", "cap_m44_c_payer"
    await _seed_player(pool, patron_id, divine_favor={"patron": "mortaen"}, death_history={"count": 0, "costs": []})
    await _seed_player(pool, payer_id, death_history={"count": 1, "costs": []})  # next = #2 (moderate)
    m1 = await db_queries.get_player(patron_id, conn=pool)
    m2 = await db_queries.get_player(payer_id, conn=pool)
    assert m1 is not None and m2 is not None

    contexts = await resurrection.resurrect_party_on_defeat([m1, m2], combat_cleared=False, conn=pool)
    by_id = {patron_id: contexts[0], payer_id: contexts[1]}

    # The Mortaen patron's first-ever death is waived: not counted, no cost — still revived.
    assert by_id[patron_id]["tier"] == "waived" and by_id[patron_id]["attribute_delta"] == 0
    # The non-patron pays independently.
    assert by_id[payer_id]["tier"] == "moderate" and by_id[payer_id]["attribute_delta"] == -1
    # Both revived at ONE shared anchor (the tier-4 starter zone, since they died off-catalog).
    assert by_id[patron_id]["anchor"] == by_id[payer_id]["anchor"] == _STARTER_ZONE

    revived_patron = await db_queries.get_player(patron_id, conn=pool)
    revived_payer = await db_queries.get_player(payer_id, conn=pool)
    assert revived_patron is not None and revived_payer is not None
    assert revived_patron["death_history"]["count"] == 0  # waived: not recorded
    assert revived_payer["death_history"]["count"] == 2  # charged
    assert revived_patron["location_id"] == revived_payer["location_id"] == by_id[patron_id]["anchor"]


# --- Scenario D: pre-combat Exhausted loads at combat start + survives the death lifecycle (AC4) ---


async def test_precombat_exhausted_loads_then_survives_death(reset_db_pool: str) -> None:
    pool = await db.get_pool()
    player_id = "cap_m44_d"
    exhausted = conditions.apply_condition([], "exhausted", source="forced_march")  # 1 stack
    await _seed_player(pool, player_id, conditions=exhausted)
    ctx = make_context(player_id, location_id="off_catalog_wilds", room=make_mock_room())

    # Combat START loads the persisted Exhausted onto the player CombatParticipant (AC4 part 1).
    raw = await combat_init._start_combat_impl(ctx, "hollow_wisp", "A hollow wisp coalesces.")
    assert isinstance(raw, tuple)  # hostile encounter -> combat handoff
    cs = ctx.userdata.combat_state
    assert cs is not None
    loaded = cs.get_participant(player_id)
    assert loaded is not None and any(c["type"] == "exhausted" for c in loaded.conditions)

    # The player falls; the defeat router persists the death AND the Exhausted survives it.
    loaded.is_fallen = True
    loaded.is_dead = True
    end_data = await combat_end._end_combat_db(
        ctx.userdata, cs, "defeat", mutations=db_mutations, queries=db_queries, conn=pool, sink=EventSink()
    )
    assert end_data["death_context"]["death_count"] == 1  # first death recorded

    revived = await db_queries.get_player(player_id, conn=pool)
    assert revived is not None
    assert end_data["death_context"]["anchor"] == _STARTER_ZONE  # off-catalog death -> tier-4
    assert revived["location_id"] == end_data["death_context"]["anchor"]  # resurrected at anchor
    assert any(c["type"] == "exhausted" for c in (revived.get("conditions") or []))  # Exhausted survived


# --- Scenario E: Hollowed / Temporary Hollowed full path (added per customer) ---


async def test_hollowed_rise_destroy_then_mortaen_death(reset_db_pool: str) -> None:
    pool = await db.get_pool()
    player_id = "cap_m44_e"
    hollowed2 = [{"type": "hollowed", "duration": None, "source": "veil", "stage": 2}]
    await _seed_player(pool, player_id, conditions=hollowed2)
    ctx = make_context(player_id, location_id="off_catalog_wilds", room=make_mock_room())

    player = CombatParticipant(
        id=player_id,
        name="Kael",
        type="player",
        initiative=15,
        hp_current=8,
        hp_max=40,
        ac=14,
        conditions=list(hollowed2),
    )
    enemy = CombatParticipant(
        id="goblin_a",
        name="Goblin",
        type="enemy",
        initiative=12,
        hp_current=7,
        hp_max=7,
        ac=10,
        action_pool=[{"name": "Scimitar", "damage": "1d6"}],
    )
    cs = CombatState(
        combat_id="combat_cap_m44_e",
        participants=[player, enemy],
        initiative_order=[player_id, "goblin_a"],
        round_number=1,
        current_turn_index=0,
        location_id="off_catalog_wilds",
        beat="resolution",
    )
    ctx.userdata.combat_state = cs

    # The Stage-2 Hollowed player drops to 0 -> rises as a Temporary Hollowed echo (does NOT fall).
    await combat_support._resolve_attack_packet(
        ctx.userdata,
        enemy,
        enemy.action_pool[0],
        player,
        mutations=db_mutations,
        queries=db_queries,
        resolver=_overkill_resolver(player),
        conn=pool,
        sink=EventSink(),
    )
    assert player.type == "temporary_hollowed" and player.is_fallen is False
    assert combat_phase._wrap(cs).combat_ended is False  # a live echo blocks combat-end

    # Destroy the echo -> the wrap reports defeat.
    await combat_support._resolve_attack_packet(
        ctx.userdata,
        enemy,
        enemy.action_pool[0],
        player,
        mutations=db_mutations,
        queries=db_queries,
        resolver=_overkill_resolver(player),
        conn=pool,
        sink=EventSink(),
    )
    wrap = combat_phase._wrap(cs)
    assert wrap.combat_ended is True and wrap.outcome == "defeat"

    # The defeat router runs the Mortaen death keyed on the player row (Hollowed branch).
    end_data = await combat_end._end_combat_db(
        ctx.userdata, cs, "defeat", mutations=db_mutations, queries=db_queries, conn=pool, sink=EventSink()
    )
    assert end_data["death_context"]["hollow_killed"] is True

    revived = await db_queries.get_player(player_id, conn=pool)
    assert revived is not None
    assert await dmr.read_hollow_killed(player_id, conn=pool) is True
    assert all(c["type"] != "hollowed" for c in (revived.get("conditions") or []))  # Hollowed cleared
    assert end_data["death_context"]["anchor"] == _STARTER_ZONE  # off-catalog death -> tier-4
    assert revived["location_id"] == end_data["death_context"]["anchor"]
