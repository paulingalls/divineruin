"""M4.8 story-005: Inspire ability producer + ability-targeting infra.

Mirrors story-004's Bless SPELL producer, but Inspire (bard_inspire/diplomat_inspire) is an
ABILITY, not a spell — and abilities had no target or condition-apply path. This story adds:

- A) catalog schema: Ability.applies_condition, parsed + fail-loud validated against the
     condition catalog (mirror spells.py).
- B) out-of-combat producer: request_ability_activation gains target_id and applies+persists
     the ability's condition to the target's players.data SSOT (caster/player target), or
     narrates-only for a non-player target.
- C) in-combat producer: a NEW non-spell ability-condition path (mirroring de_escalate) applies
     the condition to the target CombatParticipant on the working state.

The producer contract is the one recorded in story-004 (decision applies-condition-producer-contract):
condition_applied surfaces only when the condition actually landed (conditions.has_condition).
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from combat._helpers import _damage_resolver
from sample_fixtures import make_context, make_db_mod

import ability_tools
import combat_turn
import conditions
import db_mutations
import db_queries
from abilities import Ability, Cost, parse_ability_row
from session_data import CombatParticipant, CombatState, SessionData

# A bard_inspire-shaped catalog row carrying the new structured producer field.
_INSPIRE_ROW = {
    "id": "bard_inspire",
    "archetype_id": "bard",
    "name": "Inspire",
    "ability_type": "core",
    "level_requirement": 1,
    "cost": {"stamina": 0, "focus": 2, "scaling": None},
    "effect": "Grant an ally a die to add to any roll.",
    "narration_cue": "A few ringing words, and an ally stands ready to shine.",
}


# --- Group A: ability schema (pure parse) ---


def test_parse_carries_applies_condition():
    a = parse_ability_row("bard_inspire", {**_INSPIRE_ROW, "applies_condition": "inspired"})
    assert a.applies_condition == "inspired"


def test_parse_without_applies_condition_defaults_none():
    # Existing abilities (no producer field) parse with applies_condition None — no condition produced.
    a = parse_ability_row("warrior_devastating_strike", {**_INSPIRE_ROW, "id": "warrior_devastating_strike"})
    assert a.applies_condition is None


def test_parse_unknown_applies_condition_fails_loud():
    # Strict-loader convention: a typo'd / unknown condition type fails at parse, naming the row.
    with pytest.raises(ValueError, match="applies_condition"):
        parse_ability_row("bard_inspire", {**_INSPIRE_ROW, "applies_condition": "not_a_condition"})


# --- Group B: out-of-combat producer (mock-conn) ---


def _inspire_ability(applies_condition: str | None = "inspired") -> Ability:
    """A bard_inspire Ability (focus 2, no stamina) carrying the producer field."""
    return Ability(
        id="bard_inspire",
        archetype_id="bard",
        name="Inspire",
        ability_type="core",
        level_requirement=1,
        cost=Cost(stamina=0, focus=2, scaling=None),
        effect="Grant an ally a die to add to any roll.",
        narration_cue="A few ringing words.",
        applies_condition=applies_condition,
    )


def _bard(player_id: str = "bard_1", conditions_list: list | None = None) -> dict:
    return {
        "player_id": player_id,
        "name": "Bard",
        "class": "bard",
        "level": 5,
        "focus": {"current": 10, "max": 10},
        "stamina": {"current": 10, "max": 10},
        "conditions": conditions_list if conditions_list is not None else [],
    }


async def _activate(
    ability: Ability,
    *,
    caster: dict,
    target_id: str | None = None,
    target_ids: list[str] | None = None,
    rows: dict | None = None,
    in_combat: bool = False,
    party_member_ids: list[str] | None = None,
    companion_id: str | None = None,
):
    """Drive _request_ability_activation_impl out of combat. Returns (response, conditions_mutations
    mock, get_player mock) for producer assertions. ``in_combat`` sets a combat_state so the OOC
    producer's not-in-combat persist gate can be exercised. ``party_member_ids`` (M4.8 story-007
    party gate) must include any non-caster target — the OOC producer now refuses a target that is
    neither a party member nor the caster's companion."""
    ctx = make_context(player_id=caster["player_id"], party_member_ids=party_member_ids, companion_id=companion_id)
    if in_combat:
        ctx.userdata.combat_state = CombatState(combat_id="c_inspire_guard", participants=[], initiative_order=[])
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
    persistence = MagicMock(
        update_player_resources=AsyncMock(),
        get_active_variant=AsyncMock(return_value=None),
        owns_elective=AsyncMock(return_value=False),
    )
    abilities_mod = MagicMock(get_ability=MagicMock(return_value=ability), owns_ability=MagicMock(return_value=True))
    cond_mut = MagicMock(save_many_player_conditions=AsyncMock())
    raw = await ability_tools._request_ability_activation_impl(
        ctx,
        ability.id,
        target_id=target_id,
        target_ids=target_ids,
        db_mod=mock_db,
        queries_mod=queries,
        persistence_mod=persistence,
        abilities_mod=abilities_mod,
        conditions_mod=conditions,
        conditions_mutations_mod=cond_mut,
    )
    return json.loads(raw), cond_mut, queries.get_player


@pytest.mark.asyncio
async def test_ooc_mass_inspire_multi_target_persists_to_each_and_voices_all():
    # story-017: an OOC multi-target ability (bard_mass_inspire) lands the condition on EVERY targeted
    # ally's players.data SSOT and the response names all of them (condition_targets) — completing the
    # produce matrix (the spell OOC path + the in-combat ability path already do this).
    a1 = _bard("ally_a", conditions_list=[])
    a2 = _bard("ally_b", conditions_list=[])
    response, cond_mut, _gp = await _activate(
        _mass_inspire_ability(),
        caster=_bard(),
        target_ids=["ally_a", "ally_b"],
        rows={"ally_a": a1, "ally_b": a2},
        party_member_ids=["bard_1", "ally_a", "ally_b"],
    )

    assert response["condition_applied"] == "inspired"
    assert set(response["condition_targets"]) == {"ally_a", "ally_b"}
    written = cond_mut.save_many_player_conditions.call_args.args[0]
    assert set(written.keys()) == {"ally_a", "ally_b"}  # persisted to each


@pytest.mark.asyncio
async def test_ooc_ability_over_cap_target_ids_rejected_via_ssot():
    # The cap is enforced through the SAME normalize_target_list SSOT (rejects over-cap / both-args /
    # empty / a single-target ability mass-targeted) — no resource write, no condition.
    from livekit.agents.llm import ToolError

    with pytest.raises(ToolError, match="at most 2"):
        await _activate(_mass_inspire_ability(max_targets=2), caster=_bard(), target_ids=["a", "b", "c"])
    with pytest.raises(ToolError, match="not both"):
        await _activate(_mass_inspire_ability(), caster=_bard(), target_id="a", target_ids=["b"])
    with pytest.raises(ToolError, match="does not support multiple"):
        await _activate(_inspire_ability(), caster=_bard(), target_ids=["a", "b"])  # single-target ability


@pytest.mark.asyncio
async def test_ooc_inspire_on_ally_persists_inspired_to_target():
    # AC1: Inspire on an ally -> Inspired persisted to the TARGET's conditions SSOT; response signals it.
    ally = _bard("ally_2", conditions_list=[])
    response, cond_mut, _gp = await _activate(
        _inspire_ability(),
        caster=_bard(),
        target_id="ally_2",
        rows={"ally_2": ally},
        party_member_ids=["bard_1", "ally_2"],
    )

    assert response["condition_applied"] == "inspired"
    cond_mut.save_many_player_conditions.assert_awaited_once()
    written = cond_mut.save_many_player_conditions.call_args.args[0]
    assert set(written.keys()) == {"ally_2"}
    assert "inspired" in [c["type"] for c in written["ally_2"]]


@pytest.mark.asyncio
async def test_ooc_inspire_self_cast_applies_to_caster():
    # Self-target (no target_id) applies Inspired to the caster, reusing the for_update caster row.
    response, cond_mut, get_player = await _activate(_inspire_ability(), caster=_bard("bard_1"))

    assert response["condition_applied"] == "inspired"
    cond_mut.save_many_player_conditions.assert_awaited_once()
    written = cond_mut.save_many_player_conditions.call_args.args[0]
    assert set(written.keys()) == {"bard_1"}
    assert "inspired" in [c["type"] for c in written["bard_1"]]
    assert get_player.await_count == 1  # self-target reuses the caster row — no extra fetch


@pytest.mark.asyncio
async def test_ooc_inspire_non_player_target_narrates_without_persist():
    # Regression guard (mirrors story-004): buffing the caster's COMPANION (allowlisted
    # narrate-only, no players.data row) narrates condition_applied but writes nothing — never
    # hard-errors (M4.8 story-007's companion allowlist).
    response, cond_mut, _gp = await _activate(_inspire_ability(), caster=_bard(), target_id="kael", companion_id="kael")

    assert response["condition_applied"] == "inspired"
    cond_mut.save_many_player_conditions.assert_not_awaited()


@pytest.mark.asyncio
async def test_ooc_ability_no_applies_condition_does_not_persist():
    # AC3: an ability with no applies_condition produces nothing — existing abilities unchanged.
    response, cond_mut, _gp = await _activate(_inspire_ability(applies_condition=None), caster=_bard())

    assert "condition_applied" not in response
    cond_mut.save_many_player_conditions.assert_not_awaited()


@pytest.mark.asyncio
async def test_ooc_producer_does_not_persist_in_combat():
    # In combat the participant is the SSOT and declare_phase owns the apply; an in-combat call to the
    # OOC tool must NOT write Inspired to players.data (mirrors the spell producer's not-in-combat gate).
    response, cond_mut, _gp = await _activate(_inspire_ability(), caster=_bard(), in_combat=True)

    assert "condition_applied" not in response
    cond_mut.save_many_player_conditions.assert_not_awaited()


# --- Group C: in-combat non-spell ability-condition path ---


@pytest.mark.asyncio
async def test_incombat_target_gone_wastes_without_deducting():
    # A declared target_id that's no longer on the working state wastes the declaration WITHOUT
    # deducting the ability's cost — a buff that can't land must never burn Focus (mirrors the attack
    # path's wasted-target guard). resolved:False, no resource write, no condition.
    import combat_ability
    from declarations import Declaration, DeclarationType

    caster = CombatParticipant(id="c1", name="Lyra", type="player", initiative=15, hp_current=25, hp_max=25, ac=14)
    state = CombatState(combat_id="c_gone", participants=[caster], initiative_order=["c1"])
    decl = Declaration(type=DeclarationType.ABILITY, action="bard_inspire", target_id="ghost")
    persistence = MagicMock(update_player_resources=AsyncMock())

    summary = await combat_ability._resolve_ability_condition_packet(
        SessionData(player_id="c1", location_id="accord_guild_hall", room=None),
        caster,
        decl,
        _inspire_ability(),
        state=state,
        conn=MagicMock(),
        player=_bard("c1"),
        persistence=persistence,
    )

    assert summary["resolved"] is False
    assert "condition_applied" not in summary
    persistence.update_player_resources.assert_not_awaited()


@pytest.mark.asyncio
async def test_incombat_fallen_target_wastes_without_deducting():
    # Can't Inspire a corpse: a fallen target wastes the declaration without deducting the cost.
    import combat_ability
    from declarations import Declaration, DeclarationType

    caster = CombatParticipant(id="c1", name="Lyra", type="player", initiative=15, hp_current=25, hp_max=25, ac=14)
    ally = CombatParticipant(id="a1", name="Ally", type="companion", initiative=10, hp_current=0, hp_max=20, ac=13)
    ally.is_fallen = True
    state = CombatState(combat_id="c_fallen", participants=[caster, ally], initiative_order=["c1", "a1"])
    decl = Declaration(type=DeclarationType.ABILITY, action="bard_inspire", target_id="a1")
    persistence = MagicMock(update_player_resources=AsyncMock())

    summary = await combat_ability._resolve_ability_condition_packet(
        SessionData(player_id="c1", location_id="accord_guild_hall", room=None),
        caster,
        decl,
        _inspire_ability(),
        state=state,
        conn=MagicMock(),
        player=_bard("c1"),
        persistence=persistence,
    )

    assert summary["resolved"] is False
    persistence.update_player_resources.assert_not_awaited()
    assert not [c for c in ally.conditions if c["type"] == "inspired"]


# --- Group D (story-016): multi-target ability-condition path (bard_mass_inspire) ---


def _mass_inspire_ability(max_targets: int | None = 6) -> Ability:
    """A bard_mass_inspire Ability: party-wide Inspire, capped via the targeting SSOT."""
    return Ability(
        id="bard_mass_inspire",
        archetype_id="bard",
        name="Mass Inspire",
        ability_type="core",
        level_requirement=9,
        cost=Cost(stamina=0, focus=5, scaling=None),
        effect="Grant Inspiration to the whole party.",
        narration_cue="every heart in earshot",
        applies_condition="inspired",
        max_targets=max_targets,
    )


def test_parse_carries_max_targets():
    a = parse_ability_row("bard_mass_inspire", {**_INSPIRE_ROW, "id": "bard_mass_inspire", "max_targets": 6})
    assert a.max_targets == 6
    # Existing single-target rows default to None (unbounded/single-target).
    assert parse_ability_row("bard_inspire", _INSPIRE_ROW).max_targets is None


def test_parse_bad_max_targets_fails_loud():
    with pytest.raises(ValueError, match="max_targets"):
        parse_ability_row("bard_mass_inspire", {**_INSPIRE_ROW, "max_targets": 0})


def test_normalize_target_list_caps_ability_targets():
    # AC: the declare-gate caps a multi-target ability through the SAME normalize_target_list SSOT
    # the spells use — it now accepts an Ability (Spell | Ability). Over-cap / both-args / empty / a
    # single-target ability mass-targeted all raise (the gate converts ValueError -> ToolError).
    import spells

    capped = _mass_inspire_ability(max_targets=2)
    assert spells.normalize_target_list(capped, None, ["a", "b"]) == ["a", "b"]  # at the cap: ok
    with pytest.raises(ValueError, match="at most 2"):
        spells.normalize_target_list(capped, None, ["a", "b", "c"])  # over cap
    with pytest.raises(ValueError, match="not both"):
        spells.normalize_target_list(capped, "a", ["b"])  # ambiguous both-args
    with pytest.raises(ValueError, match="at least one"):
        spells.normalize_target_list(capped, None, [])  # empty
    with pytest.raises(ValueError, match="does not support multiple"):
        spells.normalize_target_list(_inspire_ability(), None, ["a", "b"])  # single-target ability


@pytest.mark.asyncio
async def test_incombat_mass_inspire_lands_on_every_ally_and_voices_them():
    # AC: a multi-target mass-inspire lands `inspired` on EACH targeted ally and the packet names
    # all of them (condition_targets), exactly like multi-target Bless — cost deducted once.
    import combat_ability
    from declarations import Declaration, DeclarationType

    caster = CombatParticipant(id="c1", name="Lyra", type="player", initiative=15, hp_current=25, hp_max=25, ac=14)
    a1 = CombatParticipant(id="a1", name="A1", type="companion", initiative=12, hp_current=20, hp_max=20, ac=13)
    a2 = CombatParticipant(id="a2", name="A2", type="companion", initiative=11, hp_current=20, hp_max=20, ac=13)
    state = CombatState(combat_id="c_mass", participants=[caster, a1, a2], initiative_order=["c1", "a1", "a2"])
    decl = Declaration(type=DeclarationType.ABILITY, action="bard_mass_inspire", target_ids=["a1", "a2"])
    persistence = MagicMock(update_player_resources=AsyncMock())

    summary = await combat_ability._resolve_ability_condition_packet(
        SessionData(player_id="c1", location_id="accord_guild_hall", room=None),
        caster,
        decl,
        _mass_inspire_ability(),
        state=state,
        conn=MagicMock(),
        player=_bard("c1"),
        persistence=persistence,
    )

    assert summary["resolved"] is True
    assert summary["condition_applied"] == "inspired"
    assert summary["condition_targets"] == ["a1", "a2"]
    assert conditions.has_condition(a1.conditions, "inspired")
    assert conditions.has_condition(a2.conditions, "inspired")
    persistence.update_player_resources.assert_awaited_once()  # cost deducted exactly once


# --- Group C (cont.): real-PG, real bard_inspire row ---


async def _seed_caster(pool, player_id: str, *, focus: int = 10) -> None:
    await pool.execute(
        "INSERT INTO players (player_id, data) VALUES ($1, $2::jsonb) "
        "ON CONFLICT (player_id) DO UPDATE SET data = $2::jsonb",
        player_id,
        json.dumps(
            {
                "player_id": player_id,
                "class": "bard",
                "hp": {"current": 25, "max": 25},
                "focus": {"current": focus, "max": focus},
                "stamina": {"current": 10, "max": 10},
            }
        ),
    )


def _inspire_combat_state(combat_id, caster_id, ally_id, enemy_id) -> CombatState:
    """RESOLUTION-beat phase: the Bard declares bard_inspire on an ally (who defends, so the produced
    die isn't immediately consumed), and an enemy survives so combat continues and the working state
    is persisted via save_combat_state."""
    return CombatState(
        combat_id=combat_id,
        participants=[
            CombatParticipant(id=caster_id, name="Lyra", type="player", initiative=15, hp_current=25, hp_max=25, ac=14),
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
        pending_declarations={
            caster_id: {"type": "ability", "action": "bard_inspire", "target_id": ally_id},
            ally_id: {"type": "defend"},
            enemy_id: {"type": "attack", "action": "Scimitar", "target_id": caster_id},
        },
    )


async def test_incombat_inspire_applies_inspired_to_target_participant(dev_db_pool):
    # AC2: a Bard declaring Inspire (a NON-spell ability) on an ally lands Inspired on the TARGET
    # participant and deducts the ability's Focus — the in-combat ability-condition path, no longer
    # rejected as an "Unknown spell".
    pool = dev_db_pool
    caster_id, ally_id, enemy_id = "s005_caster", "s005_ally", "s005_enemy"
    combat_id = "combat_s005_inspire"
    try:
        await _seed_caster(pool, caster_id, focus=10)
        session = SessionData(player_id=caster_id, location_id="accord_guild_hall", room=None)
        ctx = MagicMock()
        ctx.userdata = session
        session.combat_state = _inspire_combat_state(combat_id, caster_id, ally_id, enemy_id)
        await combat_turn._resolve_phase_impl(ctx, resolver=_damage_resolver(3))

        state = session.combat_state
        assert state is not None
        ally = state.get_participant(ally_id)
        assert ally is not None
        inspired = [c for c in ally.conditions if c["type"] == "inspired"]
        assert len(inspired) == 1
        assert inspired[0]["source"] == "bard_inspire"

        # The Bard's Focus was deducted by the ability cost (2) — proves the ability resolved.
        row = await db_queries.get_player(caster_id, conn=pool)
        assert row is not None
        assert row["focus"]["current"] == 8
    finally:
        await pool.execute("DELETE FROM players WHERE player_id = $1", caster_id)
        await db_mutations.delete_combat_state(combat_id, conn=pool)
