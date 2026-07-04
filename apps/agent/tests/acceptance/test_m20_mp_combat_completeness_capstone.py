"""Capstone: M20 multiplayer combat-completeness E2E (auto-marked acceptance, per-run Postgres
testcontainer). Drives the REAL phase-loop flow for a live 2-PC party — NOT
`combat_end._end_combat_db` directly — so the engine's wrap gate + end-combat orchestration decide
the outcome, exactly as prod hits them once a real 2nd player joins (M19).

Proves the three M20 gaps compose through the real flow:
- Scenario A (loot attribution + primary haul, story-001): a real 2-PC VICTORY over a multi-enemy
  humanoid group emits one ITEM_ACQUIRED per fallen enemy, each carrying the round-robin recipient
  `player_id` (seat parity a,b,a,b,a); the victory handoff's `loot`/`currency_gold` are the PRIMARY's
  own share, never the summed party haul.
- Scenario B (multi-PC echo-defeat gate, story-002): a Stage-2 Hollowed PC falls and rises as a
  temporary_hollowed echo; destroying the echo while the OTHER PC still stands does NOT end combat
  (the M20 gate) — combat only reaches DEFEAT once the standing PC is also down, and each member
  then resurrects at its own divergent tier-3 anchor.

Determinism comes from an injected resolver (never real dice) + a patched loot table (chance 1.0 so
every standard/elite enemy drops exactly one entry) + a seeded `combat_end` RNG for currency. Each
scenario uses its own id set so the session-scoped migrated container stays isolated (reset_db_pool
is function-scoped).
"""

from __future__ import annotations

import json
import random
from unittest.mock import AsyncMock, MagicMock, patch

from acceptance.seeds import seed_player
from combat._helpers import _damage_resolver
from sample_fixtures import make_context, make_mock_room, published_payloads

import combat_end
import combat_init
import combat_turn
import db
import db_queries
import event_types as E
from check_resolution_attack import AttackResult

_WEAPON = {"name": "Longsword", "damage": "1d8", "damage_type": "slashing", "properties": []}
_DEFEND = {"type": "defend"}
# All 5 enemies are standard/elite humanoids (currency-bearing, loot_humanoid_soldier) — a chance-1.0
# loot table therefore drops exactly one entry per enemy, deterministic without seeding the loot RNG.
# ashmark_patrol carries a stance_gate, but no reputation writer ships (SMM risk f3af7b633b44) so it
# always resolves hostile; the isinstance(raw, tuple) assert fails loud if that ever changes.
_ENCOUNTER = "ashmark_patrol"
_LOOT_STUB = {"drops": [{"item_id": "iron_scrap", "chance": 1.0, "quantity": 1}]}
_HOLLOWED_STAGE2 = {"type": "hollowed", "duration": None, "source": "veil", "stage": 2}


def _lethal_resolver():
    """A resolve_attack stand-in whose every strike is an instant-death overkill blow."""
    result = AttackResult(
        hit=True,
        roll=15,
        attack_modifier=3,
        attack_total=18,
        target_ac=15,
        damage=9999,
        damage_type="slashing",
        target_hp_remaining=0,
        target_killed=True,
        overkill=9999,
        narrative_hint="A killing blow.",
    )
    r = MagicMock()
    r.resolve_attack = MagicMock(return_value=result)
    return r


async def _seed_pc(
    pool,
    player_id: str,
    *,
    location_id: str,
    hp_current: int,
    last_rested: str | None = None,
    conditions: list[dict] | None = None,
):
    """Seed a PC armed with a Longsword (so combat_init derives an action_pool) at ``hp_current`` HP.
    Optional ``conditions`` (e.g. the Stage-2 Hollowed condition) are written to players.data so
    combat_init loads them onto the participant; optional ``last_rested`` sets the tier-3 anchor."""
    await seed_player(pool, player_id=player_id, location_id=location_id)
    await pool.execute(
        "UPDATE players SET data = jsonb_set(jsonb_set(data, '{equipment}', $2::jsonb), "
        "'{hp,current}', $3::jsonb) WHERE player_id = $1",
        player_id,
        json.dumps({"main_hand": _WEAPON}),
        json.dumps(hp_current),
    )
    if conditions is not None:
        await pool.execute(
            "UPDATE players SET data = jsonb_set(data, '{conditions}', $2::jsonb) WHERE player_id = $1",
            player_id,
            json.dumps(conditions),
        )
    if last_rested is not None:
        await pool.execute(
            "UPDATE players SET data = jsonb_set(data, '{last_rested_settlement_id}', $2::jsonb) WHERE player_id = $1",
            player_id,
            json.dumps(last_rested),
        )
    return player_id


def _attack(action: str, target_id: str) -> dict:
    return {"type": "attack", "action": action, "target_id": target_id}


def _living_enemies(cs):
    return [p for p in cs.participants if p.type == "enemy" and not p.is_fallen]


def _participants(ctx):
    return {p.id: p for p in ctx.userdata.combat_state.participants}


async def test_real_2pc_victory_attributes_loot_and_scopes_primary_haul(reset_db_pool):
    """Scenario A: a live 2-PC party fights a multi-enemy humanoid group to VICTORY through the real
    phase loop. Only PC attacks are declared (the enemies never swing), so the PCs down every enemy
    over a few phases and survive. Assert each ITEM_ACQUIRED carries the round-robin recipient
    player_id (seat parity), and the victory handoff's loot/currency are the PRIMARY's own share."""
    pool = await db.get_pool()
    pc_a, pc_b = "cap_m20_vic_pc_a", "cap_m20_vic_pc_b"  # pc_a < pc_b so seat_order == [pc_a, pc_b]
    await _seed_pc(pool, pc_a, location_id="accord_guild_hall", hp_current=40)
    await _seed_pc(pool, pc_b, location_id="accord_guild_hall", hp_current=40)

    ctx = make_context(pc_a, location_id="accord_guild_hall", room=make_mock_room(), party_member_ids=[pc_b])

    with (
        patch.object(combat_end.db_content_queries, "get_loot_table", AsyncMock(return_value=_LOOT_STUB)),
        patch("combat_end.random.Random", return_value=random.Random(20250704)),
    ):
        raw = await combat_init._start_combat_impl(ctx, _ENCOUNTER, "A Thornwatch patrol turns hostile.")
        assert isinstance(raw, tuple)  # hostile handoff (stance gate resolves hostile — no rep writer)
        n_enemies = len(_living_enemies(ctx.userdata.combat_state))

        result = None
        for _ in range(12):  # bounded: 2 kills/phase over 5 enemies -> ~3 phases
            living = _living_enemies(ctx.userdata.combat_state)
            if not living:
                break
            decls = {pc_a: _attack("Longsword", living[0].id)}
            if len(living) > 1:
                decls[pc_b] = _attack("Longsword", living[1].id)  # distinct target — no double-hit on one
            await combat_turn._declare_phase_impl(ctx, decls)
            result = await combat_turn._resolve_phase_impl(ctx, resolver=_lethal_resolver())
            if isinstance(result, tuple):
                break

    assert isinstance(result, tuple)  # combat ENDED through the real loop
    assert ctx.userdata.combat_state is None
    payload = json.loads(result[1])
    assert payload["outcome"] == "victory"

    # One ITEM_ACQUIRED per fallen enemy, each attributed to its round-robin recipient (story-001).
    items = [p for p in published_payloads(ctx.userdata.room) if p["type"] == E.ITEM_ACQUIRED]
    assert len(items) == n_enemies
    seat = [pc_a, pc_b]
    assert [it["player_id"] for it in items] == [seat[i % 2] for i in range(n_enemies)]

    # Primary-scoped haul: the handoff's loot is ONLY the primary's own (even-index) drops.
    assert len(payload["loot"]) == sum(1 for i in range(n_enemies) if i % 2 == 0)

    # Per-member currency: one CURRENCY_GAINED each, equal shares; the primary handoff carries a
    # single share, NOT the summed party total.
    currency = [p for p in published_payloads(ctx.userdata.room) if p["type"] == E.CURRENCY_GAINED]
    assert {c["player_id"] for c in currency} == {pc_a, pc_b}
    amounts = [c["amount"] for c in currency]
    assert amounts[0] == amounts[1] > 0  # equal split, non-zero
    assert payload["currency_gold"] == amounts[0]  # primary's own share
    assert payload["currency_gold"] < sum(amounts)  # NOT the summed party haul


async def test_real_echo_destroyed_while_ally_stands_defers_defeat(reset_db_pool):
    """Scenario B: a Stage-2 Hollowed PC falls and rises as a temporary_hollowed echo through the real
    resolver. Destroying the echo while the ally still stands must NOT end combat (the M20 gate,
    story-002); combat only reaches DEFEAT once the ally is also down, then each member resurrects at
    its own divergent tier-3 anchor."""
    pool = await db.get_pool()
    pc_a, pc_b = "cap_m20_echo_pc_a", "cap_m20_echo_pc_b"
    await _seed_pc(
        pool,
        pc_a,
        location_id="off_catalog_wilds",
        hp_current=3,
        last_rested="millhaven",
        conditions=[_HOLLOWED_STAGE2],
    )
    await _seed_pc(pool, pc_b, location_id="off_catalog_wilds", hp_current=28, last_rested="accord_guild_hall")

    ctx = make_context(pc_a, location_id="off_catalog_wilds", room=make_mock_room(), party_member_ids=[pc_b])
    raw = await combat_init._start_combat_impl(ctx, _ENCOUNTER, "A Thornwatch patrol turns hostile.")
    assert isinstance(raw, tuple)
    enemy = _living_enemies(ctx.userdata.combat_state)[0]

    # Phase A: the enemy drops pc_a to 0 -> the Stage-2 Hollowed rise fires (type flips in place).
    await combat_turn._declare_phase_impl(
        ctx, {pc_a: _DEFEND, pc_b: _DEFEND, enemy.id: _attack(enemy.action_pool[0]["name"], pc_a)}
    )
    r_a = await combat_turn._resolve_phase_impl(ctx, resolver=_damage_resolver(3))
    assert isinstance(r_a, str)  # combat continues
    assert _participants(ctx)[pc_a].type == "temporary_hollowed"  # echo rose

    # Phase B: the enemy destroys the echo while pc_b still stands -> combat does NOT end (M20 gate).
    await combat_turn._declare_phase_impl(ctx, {pc_b: _DEFEND, enemy.id: _attack(enemy.action_pool[0]["name"], pc_a)})
    r_b = await combat_turn._resolve_phase_impl(ctx, resolver=_lethal_resolver())
    assert isinstance(r_b, str)  # the destroyed echo did NOT end combat — the ally keeps it alive
    assert ctx.userdata.combat_state is not None
    assert _participants(ctx)[pc_a].is_fallen or _participants(ctx)[pc_a].is_dead  # echo destroyed

    # Phase C: the enemy drops pc_b -> all non-echo players down -> DEFEAT through the real wrap gate.
    with patch.object(combat_end.db_content_queries, "get_loot_table", AsyncMock(return_value=_LOOT_STUB)):
        await combat_turn._declare_phase_impl(
            ctx, {pc_b: _DEFEND, enemy.id: _attack(enemy.action_pool[0]["name"], pc_b)}
        )
        r_c = await combat_turn._resolve_phase_impl(ctx, resolver=_lethal_resolver())

    assert isinstance(r_c, tuple)  # combat ENDED (defeat) only once the ally also fell
    assert ctx.userdata.combat_state is None
    assert json.loads(r_c[1])["outcome"] == "defeat"

    # Per-member resurrection through the real defeat path: each PC revived at its OWN anchor.
    row_a = await db_queries.get_player(pc_a, conn=pool)
    row_b = await db_queries.get_player(pc_b, conn=pool)
    assert row_a is not None and row_b is not None
    assert row_a["location_id"] == "millhaven"  # pc_a (the Hollowed echo-player) at its own anchor
    assert row_b["location_id"] == "accord_guild_hall"  # pc_b at its divergent anchor
    assert row_a["death_history"]["count"] == 1
    assert row_b["death_history"]["count"] == 1
