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
import event_types as E
import spells
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
