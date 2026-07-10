"""Capstone: M24 scope-owned, party-wide, duration-bound Veil Ward end-to-end (real Postgres).

Every prior M24 story proved its own seam, mostly against mocked connections. This capstone drives
the whole model through the REAL phase loop with a live two-member party on one seeded testcontainer,
mocking neither half of any contract — it exists because a prior sprint shipped a feature whose two
halves each mocked the other and passed while broken.

AC1: one party member raises a Cleric ward -> every caster IN the encounter halves, not just the
raiser, and both clients see one scope-wide (no caster_id) VEIL_WARD_CHANGED broadcast.
AC2: the encounter ward's only home is CombatState -- combat's end IS its expiry (no veil_wards row
ever exists for it), and the next out-of-combat cast is unhalved.
AC3: no players row carries the legacy `data.veil_ward` key migration 057 removed.
AC4: two independent clocks never leak into each other's scope -- a Paladin's ROUNDS(3) ward ticks
only at the combat WRAP beat (decrement-then-test, so it survives wraps 1-2 and dies on the 3rd), and
an Artificer anchor's REAL_TIME hour ticks only against the world clock (untouched by WRAP beats,
expiring lazily on read once NOW() passes it).

Every scope/player id here is cap_m24_-prefixed and unique per test -- the testcontainer DB is shared
across the session, so a stray ward left at a shared location would silently halve every other test's
casts.
"""

from __future__ import annotations

import json

from acceptance.seeds import seed_player_with_pools
from combat._helpers import _damage_resolver
from sample_fixtures import make_context, make_mock_room, published_payloads

import combat_init
import combat_turn
import db
import db_mutations
import event_types as E
import spell_casting
import spells
import veil_anchor_tools
import veil_ward_tools

_WEAPON = {"name": "Longsword", "damage": "1d8", "damage_type": "slashing", "properties": []}
_SPELL_ID = "arcane_fireball"


async def _bump_level(pool, player_id: str, level: int) -> None:
    """WARD_SOURCES gates level (cleric 7 / paladin 10); seed_player_with_pools defaults to 2."""
    await pool.execute(
        "UPDATE players SET data = jsonb_set(data, '{level}', $2::jsonb) WHERE player_id = $1",
        player_id,
        json.dumps(level),
    )


async def _equip_weapon(pool, player_id: str) -> None:
    """So combat_init synthesizes a non-empty action_pool (it builds the pool from equipment
    entries that carry `damage`) -- needed for an ATTACK declaration to land real damage."""
    await pool.execute(
        "UPDATE players SET data = jsonb_set(data, '{equipment}', $2::jsonb) WHERE player_id = $1",
        player_id,
        json.dumps({"main_hand": _WEAPON}),
    )


async def test_ward_raised_by_one_member_halves_every_caster_in_the_encounter(reset_db_pool: str) -> None:
    """AC1: a differential inside ONE encounter -- unwarded baseline, then A raises, then BOTH A (the
    raiser) and B (not the raiser) cast halved. Party-wide, not caster-keyed. Exactly one scope-wide
    VEIL_WARD_CHANGED broadcast, carrying no caster_id -- there is nothing for a client to filter."""
    pool = await db.get_pool()
    a, b = "cap_m24_ac1_cleric", "cap_m24_ac1_mage"
    location = "cap_m24_ac1_hall"
    await seed_player_with_pools(pool, player_id=a, class_="cleric", focus_current=20)
    await _bump_level(pool, a, 7)
    await seed_player_with_pools(pool, player_id=b, class_="mage", focus_current=20)
    await spells.load_spells()

    spell = spells.get_spell(_SPELL_ID)
    base = spell.resonance_by_source[spell.source]  # 3
    assert base > 1  # halving is observable (3 -> 1, not 0 -> 0)

    room = make_mock_room()
    ctx = make_context(a, location_id=location, room=room, party_member_ids=[b])
    raw = await combat_init._start_combat_impl(ctx, "hollow_wisp", "A hollow wisp coalesces from the drift.")
    assert isinstance(raw, tuple)  # hostile encounter -> combat handoff
    cs = ctx.userdata.combat_state
    enemy = next(p for p in cs.participants if p.type == "enemy")

    def _cast_decls() -> dict:
        return {
            a: {"type": "ability", "action": _SPELL_ID, "target_id": enemy.id},
            b: {"type": "ability", "action": _SPELL_ID, "target_id": enemy.id},
            enemy.id: {"type": "attack", "action": enemy.action_pool[0]["name"], "target_id": a},
        }

    # Phase 1, unwarded: both cast at the unhalved baseline.
    await combat_turn._declare_phase_impl(ctx, _cast_decls())
    result1 = await combat_turn._resolve_phase_impl(ctx, resolver=_damage_resolver(3))
    assert isinstance(result1, str)  # combat continues
    packets1 = {p["actor_id"]: p for p in json.loads(result1)["packets"]}
    assert packets1[a]["cast"]["ward_active"] is False
    assert packets1[a]["cast"]["resonance_generated"] == base
    assert packets1[b]["cast"]["ward_active"] is False
    assert packets1[b]["cast"]["resonance_generated"] == base

    # A raises a Cleric ward (the real activation tool, real pool).
    await veil_ward_tools._activate_veil_ward_impl(ctx, True)

    # Phase 2, warded: BOTH the raiser and the non-raiser halve.
    await combat_turn._declare_phase_impl(ctx, _cast_decls())
    result2 = await combat_turn._resolve_phase_impl(ctx, resolver=_damage_resolver(3))
    assert isinstance(result2, str)
    packets2 = {p["actor_id"]: p for p in json.loads(result2)["packets"]}
    assert packets2[a]["cast"]["ward_active"] is True
    assert packets2[a]["cast"]["resonance_generated"] == base // 2
    assert packets2[b]["cast"]["ward_active"] is True
    assert packets2[b]["cast"]["resonance_generated"] == base // 2

    # Both clients light up: ONE scope-wide broadcast, no caster_id to filter on.
    ward_events = [p for p in published_payloads(room) if p["type"] == E.VEIL_WARD_CHANGED]
    assert len(ward_events) == 1
    payload = ward_events[0]
    assert payload["active"] is True
    assert payload["scope_kind"] == "encounter"
    assert payload["scope_id"] == cs.combat_id
    assert payload["source"] == "cleric"
    assert "caster_id" not in payload


async def test_encounter_ward_dies_with_the_combat_and_the_next_cast_is_unhalved(reset_db_pool: str) -> None:
    """AC2: the encounter scope has exactly ONE home -- combat's row deletion IS the ward's expiry.
    No veil_wards row is ever written for it, the combat-end broadcast reports active=False, and a
    following out-of-combat cast generates the unhalved baseline."""
    pool = await db.get_pool()
    player_id = "cap_m24_ac2_cleric"
    location = "cap_m24_ac2_hall"
    await seed_player_with_pools(pool, player_id=player_id, class_="cleric", focus_current=20)
    await _bump_level(pool, player_id, 7)
    await _equip_weapon(pool, player_id)
    await spells.load_spells()

    spell = spells.get_spell(_SPELL_ID)
    base = spell.resonance_by_source[spell.source]

    room = make_mock_room()
    ctx = make_context(player_id, location_id=location, room=room)
    raw = await combat_init._start_combat_impl(ctx, "hollow_wisp", "A hollow wisp coalesces from the drift.")
    assert isinstance(raw, tuple)
    combat_id = ctx.userdata.combat_state.combat_id
    enemy = next(p for p in ctx.userdata.combat_state.participants if p.type == "enemy")

    await veil_ward_tools._activate_veil_ward_impl(ctx, True)
    assert ctx.userdata.combat_state.veil_ward == {"source": "cleric", "rounds_remaining": None}

    # Drop the wisp (22 HP) in one hit -> combat ends this phase.
    decls = {
        player_id: {"type": "attack", "action": "Longsword", "target_id": enemy.id},
        enemy.id: {"type": "attack", "action": enemy.action_pool[0]["name"], "target_id": player_id},
    }
    await combat_turn._declare_phase_impl(ctx, decls)
    result = await combat_turn._resolve_phase_impl(ctx, resolver=_damage_resolver(22))
    assert isinstance(result, tuple)  # the winning wrap fires end_combat and hands back
    assert ctx.userdata.combat_state is None

    # The combat row is gone, and the encounter ward NEVER had a veil_wards row -- for either scope.
    assert await pool.fetchrow("SELECT 1 FROM combat_instances WHERE combat_id = $1", combat_id) is None
    assert await pool.fetchval("SELECT count(*) FROM veil_wards WHERE scope_id = $1", combat_id) == 0
    assert await pool.fetchval("SELECT count(*) FROM veil_wards WHERE scope_id = $1", location) == 0

    # combat-end broadcast the ward's expiry: no location ward covers this scope, so active=False.
    ward_events = [p for p in published_payloads(room) if p["type"] == E.VEIL_WARD_CHANGED]
    assert ward_events[-1]["active"] is False

    # A following out-of-combat cast generates the unhalved baseline.
    packet = json.loads(await spell_casting._cast_spell_impl(ctx, _SPELL_ID))
    assert packet["ward_active"] is False
    assert packet["resonance_generated"] == base


async def test_no_player_row_carries_legacy_ward_state(reset_db_pool: str) -> None:
    """AC3: migration 057 removed players.data.veil_ward and nothing writes it back. Global, not
    per-player -- stronger than checking one seeded row, and cheap against the whole table."""
    pool = await db.get_pool()
    assert await pool.fetchval("SELECT count(*) FROM players WHERE data ? 'veil_ward'") == 0


async def test_paladin_rounds_ward_expires_on_the_third_wrap(reset_db_pool: str) -> None:
    """AC4 (clock 1 of 2): a Paladin's ROUNDS(3) ward ticks ONLY at the combat WRAP beat, decrement-
    then-test -- it must survive wraps 1 and 2 and die on the 3rd, never the 2nd. Cross-leak: it never
    writes a veil_wards row for either the combat or the location scope."""
    pool = await db.get_pool()
    player_id = "cap_m24_ac4_paladin"
    location = "cap_m24_ac4_paladin_hall"
    await seed_player_with_pools(pool, player_id=player_id, class_="paladin", focus_current=10, stamina_current=10)
    await _bump_level(pool, player_id, 10)
    await _equip_weapon(pool, player_id)

    ctx = make_context(player_id, location_id=location)
    raw = await combat_init._start_combat_impl(ctx, "hollow_wisp", "A hollow wisp coalesces from the drift.")
    assert isinstance(raw, tuple)
    combat_id = ctx.userdata.combat_state.combat_id
    enemy = next(p for p in ctx.userdata.combat_state.participants if p.type == "enemy")

    await veil_ward_tools._activate_veil_ward_impl(ctx, True)
    assert ctx.userdata.combat_state.veil_ward == {"source": "paladin", "rounds_remaining": 3}

    for expected_remaining in (2, 1, None):
        decls = {
            player_id: {"type": "attack", "action": "Longsword", "target_id": enemy.id},
            enemy.id: {"type": "attack", "action": enemy.action_pool[0]["name"], "target_id": player_id},
        }
        await combat_turn._declare_phase_impl(ctx, decls)
        # Fixed low damage -- the 22 HP wisp must outlast all 3 wraps so the clock is observed fully.
        result = await combat_turn._resolve_phase_impl(ctx, resolver=_damage_resolver(1))
        assert isinstance(result, str)  # combat continues through all 3 wraps
        ward = ctx.userdata.combat_state.veil_ward
        if expected_remaining is None:
            assert ward is None  # dies on the 3rd wrap, not the 2nd
        else:
            assert ward == {"source": "paladin", "rounds_remaining": expected_remaining}

    # The ROUNDS clock never touched veil_wards -- for either scope.
    assert await pool.fetchval("SELECT count(*) FROM veil_wards WHERE scope_id = $1", combat_id) == 0
    assert await pool.fetchval("SELECT count(*) FROM veil_wards WHERE scope_id = $1", location) == 0


async def test_anchor_survives_wrap_beats_and_expires_on_the_world_clock(reset_db_pool: str) -> None:
    """AC4 (clock 2 of 2): a deployed Artificer anchor's REAL_TIME hour ticks ONLY against the world
    clock -- the combat WRAP beat never touches it (no encounter ward is raised, so it stays halved
    from the location scope every phase), and it never leaks a veil_wards row into the encounter
    scope. Advancing NOW() past the anchor's expiry stops the halving; the row itself stays present
    (lazy expiry) until a read hides it."""
    pool = await db.get_pool()
    player_id = "cap_m24_ac4_anchor"
    location = "cap_m24_ac4_anchor_hall"
    await seed_player_with_pools(pool, player_id=player_id, class_="mage", focus_current=20)
    await _equip_weapon(pool, player_id)
    await db_mutations.add_inventory_item(player_id, "veil_ward_anchor_small", 1, conn=pool)
    await spells.load_spells()

    spell = spells.get_spell(_SPELL_ID)
    base = spell.resonance_by_source[spell.source]

    ctx = make_context(player_id, location_id=location)
    await veil_anchor_tools._deploy_veil_anchor_impl(ctx, "veil_ward_anchor_small")
    assert ctx.userdata.location_ward is not None

    raw = await combat_init._start_combat_impl(ctx, "hollow_wisp", "A hollow wisp coalesces from the drift.")
    assert isinstance(raw, tuple)
    assert ctx.userdata.combat_state.veil_ward is None  # no encounter ward raised
    combat_id = ctx.userdata.combat_state.combat_id
    enemy = next(p for p in ctx.userdata.combat_state.participants if p.type == "enemy")

    for _ in range(3):
        decls = {
            player_id: {"type": "ability", "action": _SPELL_ID, "target_id": enemy.id},
            enemy.id: {"type": "attack", "action": enemy.action_pool[0]["name"], "target_id": player_id},
        }
        await combat_turn._declare_phase_impl(ctx, decls)
        result = await combat_turn._resolve_phase_impl(ctx, resolver=_damage_resolver(1))
        assert isinstance(result, str)
        packets = {p["actor_id"]: p for p in json.loads(result)["packets"]}
        assert packets[player_id]["cast"]["ward_active"] is True
        assert packets[player_id]["cast"]["resonance_generated"] == base // 2
        # The WRAP beat never touches the world-clock scope: no encounter ward appears.
        assert ctx.userdata.combat_state.veil_ward is None

    # The location ward never leaked into the encounter scope.
    assert await pool.fetchval("SELECT count(*) FROM veil_wards WHERE scope_id = $1", combat_id) == 0

    # Advance the world clock past the anchor's expiry.
    await pool.execute("UPDATE veil_wards SET expires_at = NOW() - interval '1 second' WHERE scope_id = $1", location)
    # Lazy expiry: the row is still present -- nothing sweeps veil_wards, only the read hides it.
    assert await pool.fetchval("SELECT count(*) FROM veil_wards WHERE scope_id = $1", location) == 1

    # End the fight with a lethal ATTACK so the next cast is genuinely out-of-combat.
    decls = {
        player_id: {"type": "attack", "action": "Longsword", "target_id": enemy.id},
        enemy.id: {"type": "attack", "action": enemy.action_pool[0]["name"], "target_id": player_id},
    }
    await combat_turn._declare_phase_impl(ctx, decls)
    result = await combat_turn._resolve_phase_impl(ctx, resolver=_damage_resolver(22))
    assert isinstance(result, tuple)
    assert ctx.userdata.combat_state is None

    packet = json.loads(await spell_casting._cast_spell_impl(ctx, _SPELL_ID))
    assert packet["ward_active"] is False
    assert packet["resonance_generated"] == base
