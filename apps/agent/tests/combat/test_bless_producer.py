"""M4.8 story-004: Bless spell producer — apply Blessed on cast.

Stories 001-003 built the CONSUMER side (BonusDie model, +1d4 fold, consume-on-roll). This
story is the PRODUCER: a spell whose catalog row carries a structured `applies_condition`
lands that condition on the cast's target. Single-target (multi-target is story-007). Both
paths wired (customer decision story-004-in-combat-scope):

- A) catalog schema: Spell.applies_condition, parsed + fail-loud validated against the
     condition catalog.
- B) out-of-combat producer: _resolve_cast applies + persists the condition to the target's
     players.data SSOT (gated on not session.in_combat) and surfaces it in the cast packet.
- C) in-combat producer: _resolve_one_packet applies the produced condition to the target
     CombatParticipant on the working state (rides save_combat_state).
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from combat._helpers import _damage_resolver
from livekit.agents.llm import ToolError
from sample_fixtures import make_context, make_db_mod

import combat_turn
import conditions
import db_mutations
import spell_casting
import spells
from session_data import CombatParticipant, CombatState, SessionData
from spells import Spell, parse_spell_row

# A divine_bless-shaped catalog row carrying the new structured producer field. Mirrors the
# strict M3.3 row shape (resonance_by_source/terrain_effects/audio_cue/concentration required).
_BLESS_ROW = {
    "id": "divine_bless",
    "name": "Bless",
    "source": "divine",
    "spell_tier": "minor",
    "focus_cost": 2,
    "mechanics": "An ally gains +1d4 on attacks and saves. Concentration.",
    "narration_cue": "You speak their name and your patron hears — warmth settling into bones.",
    "resonance_by_source": {"divine": 1},
    "terrain_effects": {},
    "audio_cue": "",
    "concentration": True,
}


# --- Group A: catalog schema (pure parse) ---


def test_parse_carries_applies_condition():
    spell = parse_spell_row("divine_bless", {**_BLESS_ROW, "applies_condition": "blessed"})
    assert spell.applies_condition == "blessed"


def test_parse_without_applies_condition_defaults_none():
    # Existing spells (no producer field) parse with applies_condition None — no condition produced.
    spell = parse_spell_row(
        "arcane_bolt", {**_BLESS_ROW, "id": "arcane_bolt", "source": "arcane", "resonance_by_source": {"arcane": 0}}
    )
    assert spell.applies_condition is None


def test_parse_unknown_applies_condition_fails_loud():
    # Strict-loader convention: a typo'd / unknown condition type fails at parse, naming the row.
    with pytest.raises(ValueError, match="applies_condition"):
        parse_spell_row("divine_bless", {**_BLESS_ROW, "applies_condition": "not_a_condition"})


# --- Group B: out-of-combat producer (mock-conn) ---


def _bless_spell(applies_condition: str | None = "blessed", *, focus_cost: int = 0) -> Spell:
    """A divine spell (resonance 0, default focus 0) that resolves past the Focus/Resonance gates
    with no side-effects but the producer hook — only applies_condition matters here. Bump
    focus_cost to exercise the affordability gate (Spell is frozen, so set it at construction)."""
    return Spell(
        id="divine_bless",
        name="Bless",
        source="divine",
        spell_tier="minor",
        focus_cost=focus_cost,
        mechanics="An ally gains +1d4 on attacks and saves.",
        narration_cue="Warmth settling into bones.",
        audio_cue="",
        resonance_by_source={"divine": 0},
        terrain_effects={},
        concentration=False,
        applies_condition=applies_condition,
    )


def _caster(player_id: str = "caster_1", conditions_list: list | None = None) -> dict:
    return {
        "player_id": player_id,
        "name": "Caster",
        "class": "cleric",
        "level": 5,
        "focus": {"current": 10, "max": 10},
        "conditions": conditions_list if conditions_list is not None else [],
    }


async def _cast_ooc(
    spell: Spell,
    *,
    caster: dict,
    target_id: str | None = None,
    rows: dict | None = None,
    party_member_ids: list[str] | None = None,
    companion_id: str | None = None,
):
    """Drive _cast_spell_impl out of combat (make_context -> no combat_state -> in_combat False).
    Returns (packet, conditions_mutations mock, get_player mock) for producer assertions.
    ``party_member_ids`` (M4.8 story-007 party gate) must include any non-caster target — the OOC
    producer now refuses a target that is neither a party member nor the caster's companion."""
    ctx = make_context(player_id=caster["player_id"], party_member_ids=party_member_ids, companion_id=companion_id)
    mock_db, _conn = make_db_mod()
    table = {caster["player_id"]: caster, **(rows or {})}

    async def _get_player(pid, *, conn=None, for_update=False):
        return table.get(pid)

    async def _get_players_for_update(pids, *, conn=None):
        return {pid: table[pid] for pid in pids if pid in table}

    queries = MagicMock(
        get_player=AsyncMock(side_effect=_get_player),
        get_players_for_update=AsyncMock(side_effect=_get_players_for_update),
    )
    persistence = MagicMock(update_player_resources=AsyncMock())
    res_mut = MagicMock(update_player_resonance=AsyncMock())
    events = MagicMock(publish_resonance_changed=AsyncMock())
    spells_mod = MagicMock(get_spell=MagicMock(return_value=spell))
    cond_mut = MagicMock(save_many_player_conditions=AsyncMock())
    raw = await spell_casting._cast_spell_impl(
        ctx,
        spell.id,
        target_id=target_id,
        db_mod=mock_db,
        queries_mod=queries,
        persistence_mod=persistence,
        resonance_mutations_mod=res_mut,
        resonance_events_mod=events,
        spells_mod=spells_mod,
        conditions_mod=conditions,
        conditions_mutations_mod=cond_mut,
    )
    return json.loads(raw), cond_mut, queries.get_players_for_update


@pytest.mark.asyncio
async def test_ooc_cast_on_ally_persists_blessed_to_target():
    # AC1: cast Bless on an ally -> Blessed persisted to the TARGET's conditions SSOT; packet signals it.
    ally = _caster("ally_2", conditions_list=[])
    packet, cond_mut, _gp = await _cast_ooc(
        _bless_spell(),
        caster=_caster(),
        target_id="ally_2",
        rows={"ally_2": ally},
        party_member_ids=["caster_1", "ally_2"],
    )

    assert packet["condition_applied"] == "blessed"
    cond_mut.save_many_player_conditions.assert_awaited_once()
    written = cond_mut.save_many_player_conditions.call_args.args[0]
    assert set(written.keys()) == {"ally_2"}  # persisted to the target, not the caster
    assert "blessed" in [c["type"] for c in written["ally_2"]]


@pytest.mark.asyncio
async def test_ooc_self_cast_applies_to_caster():
    # AC2: a self-cast (no target_id) applies Blessed to the caster, reusing the caster row.
    packet, cond_mut, get_players_for_update = await _cast_ooc(_bless_spell(), caster=_caster("caster_1"))

    assert packet["condition_applied"] == "blessed"
    cond_mut.save_many_player_conditions.assert_awaited_once()
    written = cond_mut.save_many_player_conditions.call_args.args[0]
    assert set(written.keys()) == {"caster_1"}
    assert "blessed" in [c["type"] for c in written["caster_1"]]
    # story-008: self-cast locks only the caster via ONE id-ordered batch; the producer reuses that
    # row (no non-caster target fetch) — so exactly one get_players_for_update call.
    assert get_players_for_update.await_count == 1


@pytest.mark.asyncio
async def test_ooc_cast_no_applies_condition_does_not_persist():
    # AC3: a spell with no applies_condition produces nothing — existing casts unchanged.
    packet, cond_mut, _gp = await _cast_ooc(_bless_spell(applies_condition=None), caster=_caster())

    assert "condition_applied" not in packet
    cond_mut.save_many_player_conditions.assert_not_awaited()


@pytest.mark.asyncio
async def test_ooc_cast_on_non_player_target_narrates_without_persist():
    # Regression guard (finding #1): buffing the caster's COMPANION (an allowlisted narrate-only
    # target, no players.data row) must NOT hard-error — it narrates condition_applied for the DM
    # and writes nothing (M4.8 story-007's companion allowlist, replacing the old any-absent-id
    # narrate-only fallback the party gate now closes).
    packet, cond_mut, _gp = await _cast_ooc(_bless_spell(), caster=_caster(), target_id="kael", companion_id="kael")

    assert packet["condition_applied"] == "blessed"  # DM still voices the buff
    cond_mut.save_many_player_conditions.assert_not_awaited()  # no players.data write for a companion


@pytest.mark.asyncio
async def test_ooc_unaffordable_cast_persists_nothing():
    # Finding #10: the producer is gated AFTER the Focus check, so a refused/unaffordable cast must
    # produce no condition. A focus_cost=3 spell against a 2-Focus caster raises ToolError before the
    # producer hook ever runs — nothing persisted, no packet returned.
    broke_caster = _caster("broke_1")
    broke_caster["focus"] = {"current": 2, "max": 10}
    with pytest.raises(ToolError):
        await _cast_ooc(_bless_spell(focus_cost=3), caster=broke_caster)


# --- Group C: in-combat producer (real-PG, real divine_bless catalog row) ---


async def _seed_caster(pool, player_id: str, *, focus: int = 10) -> None:
    await pool.execute(
        "INSERT INTO players (player_id, data) VALUES ($1, $2::jsonb) "
        "ON CONFLICT (player_id) DO UPDATE SET data = $2::jsonb",
        player_id,
        json.dumps(
            {"player_id": player_id, "hp": {"current": 25, "max": 25}, "focus": {"current": focus, "max": focus}}
        ),
    )


def _bless_combat_state(combat_id, caster_id, ally_id, enemy_id, *, target_id) -> CombatState:
    """RESOLUTION-beat phase: the caster casts divine_bless (targeting `target_id`), an ally defends
    (no roll, so the produced die isn't immediately consumed), and an enemy survives so combat
    continues and the working state is persisted via save_combat_state.

    The enemy attacks the COMPANION ally (not the caster) on purpose: this test exercises the Bless
    PRODUCER, so the enemy's only job is to keep combat alive. A hit on the concentrating caster
    would roll a real (unpatched) CON save that can fail and strip the just-produced Blessed — the
    concentration-break CONSUMER's behavior, covered separately in test_concentration_break."""
    decls = {
        caster_id: {"type": "ability", "action": "divine_bless", "target_id": target_id},
        ally_id: {"type": "defend"},
        enemy_id: {"type": "attack", "action": "Scimitar", "target_id": ally_id},
    }
    if target_id == caster_id:
        decls.pop(ally_id)  # self-cast: no separate ally needed
    return CombatState(
        combat_id=combat_id,
        participants=[
            CombatParticipant(
                id=caster_id, name="Cleric", type="player", initiative=15, hp_current=25, hp_max=25, ac=14
            ),
            CombatParticipant(
                id=ally_id, name="Ally", type="companion", initiative=10, hp_current=20, hp_max=20, ac=13
            ),
            CombatParticipant(
                id=enemy_id,
                name="Goblin",
                type="enemy",
                initiative=12,
                hp_current=20,
                hp_max=20,
                ac=13,
                action_pool=[{"name": "Scimitar", "damage": "1d6", "damage_type": "slashing"}],
                xp_value=50,
            ),
        ],
        initiative_order=[caster_id, enemy_id, ally_id],
        beat="resolution",
        pending_declarations=decls,
    )


async def _run_bless_phase(pool, combat_id, caster_id, ally_id, enemy_id, *, target_id):
    assert spells.get_spell("divine_bless").applies_condition == "blessed"  # real catalog row
    await _seed_caster(pool, caster_id)
    session = SessionData(player_id=caster_id, location_id="accord_guild_hall", room=None)
    ctx = MagicMock()
    ctx.userdata = session
    session.combat_state = _bless_combat_state(combat_id, caster_id, ally_id, enemy_id, target_id=target_id)
    await combat_turn._resolve_phase_impl(ctx, resolver=_damage_resolver(3))
    state = session.combat_state  # synced to the persisted working state post-commit
    assert state is not None
    return state


async def test_incombat_bless_applies_blessed_to_target_participant(dev_db_pool):
    # In-combat AC: a cast Bless targeting an ally lands Blessed on the TARGET participant (the working
    # state's SSOT), surviving to the persisted combat state (synced to session.combat_state post-commit).
    pool = dev_db_pool
    caster_id, ally_id, enemy_id = "s004_caster", "s004_ally", "s004_enemy"
    combat_id = "combat_s004_bless"
    try:
        state = await _run_bless_phase(pool, combat_id, caster_id, ally_id, enemy_id, target_id=ally_id)
        ally = state.get_participant(ally_id)
        assert ally is not None
        blessed = [c for c in ally.conditions if c["type"] == "blessed"]
        assert len(blessed) == 1
        assert blessed[0]["source"] == "divine_bless"
        # The caster is not the target — Blessed lands only on the declared ally.
        caster = state.get_participant(caster_id)
        assert caster is not None
        assert "blessed" not in [c["type"] for c in caster.conditions]
    finally:
        await pool.execute("DELETE FROM players WHERE player_id = $1", caster_id)
        await db_mutations.delete_combat_state(combat_id, conn=pool)


async def test_incombat_bless_self_cast_applies_to_caster_participant(dev_db_pool):
    # Self-cast (no target_id) lands Blessed on the caster participant via the attacker.id fallback.
    pool = dev_db_pool
    caster_id, ally_id, enemy_id = "s004_self_caster", "s004_self_ally", "s004_self_enemy"
    combat_id = "combat_s004_self"
    try:
        state = await _run_bless_phase(pool, combat_id, caster_id, ally_id, enemy_id, target_id=caster_id)
        caster = state.get_participant(caster_id)
        assert caster is not None
        assert "blessed" in [c["type"] for c in caster.conditions]
    finally:
        await pool.execute("DELETE FROM players WHERE player_id = $1", caster_id)
        await db_mutations.delete_combat_state(combat_id, conn=pool)
