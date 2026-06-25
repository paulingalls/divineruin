"""M4.8 story-003: consumer write-back — consume + persist the beneficial die.

The single-use +1d4 (Blessed/Inspired, story-001/002) is now made live: player-initiated rolls
consume it and persist the removal, while engine-auto saves (Beat-4 tick-clear, concentration-break)
suppress it via the new bonus_dice_eligible flag (customer decision 6102eca13319). In-combat the die
is consumed ONCE per multi-swing declaration. Grouped: A) eligibility flag + engine-auto suppression,
B) in-combat consume-once, C) out-of-combat persist."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sample_fixtures import FixedRng

import combat_packet
from check_resolution_save import resolve_saving_throw
from conditions import apply_condition
from tools._helpers import SAMPLE_PLAYER, _ctx_with_bus, _make_context
from tools.test_discover import LOCATION_WITH_HIDDEN, _roll

BLESSED = apply_condition([], "blessed")
_ATTRS = {"strength": 12, "dexterity": 12, "constitution": 12, "wisdom": 12, "charisma": 12, "intelligence": 12}


def _player(conditions):
    return {"attributes": _ATTRS, "level": 3, "conditions": conditions}


# --- Group A: bonus_dice_eligible flag + engine-auto suppression ---


def test_save_eligible_default_folds_and_consumes():
    # Default (player-initiated) path keeps story-002 behavior: Blessed +1d4 folds + signals consume.
    res = resolve_saving_throw(_player(BLESSED), "wisdom", 12, "x", rng=FixedRng(3))
    base = resolve_saving_throw(_player([]), "wisdom", 12, "x", rng=FixedRng(3))
    assert res.total == base.total + 3
    assert res.consumed_conditions == ("blessed",)


def test_save_eligible_false_skips_fold_and_consume():
    # Engine-auto saves pass bonus_dice_eligible=False: no +1d4, nothing consumed.
    res = resolve_saving_throw(_player(BLESSED), "wisdom", 12, "x", rng=FixedRng(3), bonus_dice_eligible=False)
    base = resolve_saving_throw(_player([]), "wisdom", 12, "x", rng=FixedRng(3))
    assert res.total == base.total
    assert res.consumed_conditions == ()


def test_tick_save_loop_passes_eligible_false():
    # combat_packet._resolve_tick_saves must not let an auto tick-clear save spend the die.
    from combat_packet import _resolve_tick_saves

    save_resolver = MagicMock()
    save_resolver.resolve_saving_throw = MagicMock(return_value=SimpleNamespace(success=False, consumed_conditions=()))
    actor = SimpleNamespace(attributes=_ATTRS, level=3, conditions=apply_condition(BLESSED, "frightened"))
    state = MagicMock()
    state.get_participant = MagicMock(return_value=actor)

    _resolve_tick_saves(state, [{"actor_id": "p1", "type": "frightened", "save": "wis", "source": "x"}], save_resolver)

    _, kwargs = save_resolver.resolve_saving_throw.call_args
    assert kwargs.get("bonus_dice_eligible") is False
    # The tick loop only clears the ticked type on success; blessed is never touched here.
    assert "blessed" in [c["type"] for c in actor.conditions]


@pytest.mark.asyncio
async def test_concentration_break_save_passes_eligible_false():
    # concentration_break's damage-triggered CON save is engine-auto: it must not spend the die.
    import concentration_break

    resolver = MagicMock()
    resolver.resolve_saving_throw = MagicMock(return_value=SimpleNamespace(total=18, consumed_conditions=()))
    queries = MagicMock()
    queries.get_player = AsyncMock(return_value=_player(BLESSED))
    concentration_mutations = MagicMock()
    concentration_mutations.update_player_concentration = AsyncMock()
    session = MagicMock()
    session.player_id = "p1"
    session.concentration = SimpleNamespace(spell_id="divine_bless")
    session.combat_state = None

    await concentration_break.break_concentration_on_damage(
        session,
        damage=10,
        incapacitated=False,
        conn=None,
        queries=queries,
        resolver=resolver,
        concentration_mutations=concentration_mutations,
    )

    _, kwargs = resolver.resolve_saving_throw.call_args
    assert kwargs.get("bonus_dice_eligible") is False


# --- Group B: in-combat consume-once per declaration ---

_WEAPON = {"name": "Longsword", "damage": "1d8", "damage_type": "slashing", "properties": []}


def _combat_mocks():
    mutations = MagicMock()
    mutations.update_player_hp = AsyncMock()
    mutations.save_combat_state = AsyncMock()
    queries = MagicMock()
    queries.get_player_inventory = AsyncMock(return_value=[])
    break_mod = MagicMock()
    break_mod.break_concentration_on_damage = AsyncMock(return_value=None)
    return mutations, queries, break_mod


@pytest.mark.asyncio
async def test_attack_packet_surfaces_consumed_conditions():
    from combat._helpers import _make_combat_state
    from sample_fixtures import make_context

    from check_resolution_attack import AttackResult
    from combat_support import _resolve_attack_packet

    cs = _make_combat_state()
    attacker, target = cs.get_participant("player_1"), cs.get_participant("goblin_scout_1")
    resolver = MagicMock()
    resolver.resolve_attack = MagicMock(
        return_value=AttackResult(
            hit=True,
            roll=15,
            attack_modifier=3,
            attack_total=18,
            target_ac=13,
            damage=3,
            damage_type="slashing",
            critical_success=False,
            critical_failure=False,
            target_hp_remaining=4,
            target_killed=False,
            narrative_hint="x",
            consumed_conditions=("blessed",),
        )
    )
    mutations, queries, break_mod = _combat_mocks()
    resp = await _resolve_attack_packet(
        make_context().userdata,
        attacker,
        dict(_WEAPON),
        target,
        mutations=mutations,
        queries=queries,
        resolver=resolver,
        concentration_break_mod=break_mod,
    )
    assert resp["consumed_conditions"] == ("blessed",)


@pytest.mark.asyncio
async def test_extra_attack_consumes_beneficial_die_once():
    # A 2-swing declaration must apply + consume the single-use die ONCE: swing-1 signals + removes
    # it, swing-2 (clean attacker) gets nothing. Uses the REAL attack resolver.
    from combat._helpers import _make_combat_state
    from sample_fixtures import make_context

    import check_resolution_attack
    from combat_phase import ResolutionPacket
    from declarations import Declaration, DeclarationType

    cs = _make_combat_state(enemy_hp=40)
    player = cs.get_participant("player_1")
    assert player is not None
    player.action_pool = [dict(_WEAPON)]
    player.enhancers = ["extra_attack"]
    player.conditions = apply_condition([], "blessed")
    mutations, queries, break_mod = _combat_mocks()
    packet = ResolutionPacket(
        actor_id="player_1",
        declaration=Declaration(type=DeclarationType.ATTACK, action="Longsword", target_id="goblin_scout_1"),
        initiative=20,
    )
    summary = await combat_packet._resolve_one_packet(
        make_context().userdata,
        cs,
        packet,
        mutations=mutations,
        queries=queries,
        resolver=check_resolution_attack,
        concentration_break_mod=break_mod,
    )
    assert len(summary["attacks"]) == 2
    assert summary["attacks"][0]["consumed_conditions"] == ("blessed",)
    assert summary["attacks"][1]["consumed_conditions"] == ()
    assert "blessed" not in [c["type"] for c in player.conditions]


# --- Group C: out-of-combat consume + persist ---


@pytest.mark.asyncio
async def test_save_tool_consumes_and_persists():
    from check_tools import _check_save_impl
    from tools._helpers import SAMPLE_PLAYER, _make_context

    queries = MagicMock()
    queries.get_player = AsyncMock(return_value={**SAMPLE_PLAYER, "conditions": apply_condition([], "blessed")})
    cond_mut = MagicMock()
    cond_mut.save_player_conditions = AsyncMock()

    await _check_save_impl(_make_context(), "wisdom", 12, "resist", queries=queries, conditions_mutations=cond_mut)

    cond_mut.save_player_conditions.assert_awaited_once()
    args, _ = cond_mut.save_player_conditions.call_args
    assert "blessed" not in [c["type"] for c in args[1]]  # (player_id, conditions)


@pytest.mark.asyncio
async def test_save_tool_no_condition_does_not_persist():
    from check_tools import _check_save_impl
    from tools._helpers import SAMPLE_PLAYER, _make_context

    queries = MagicMock()
    queries.get_player = AsyncMock(return_value={**SAMPLE_PLAYER, "conditions": []})
    cond_mut = MagicMock()
    cond_mut.save_player_conditions = AsyncMock()

    await _check_save_impl(_make_context(), "wisdom", 12, "resist", queries=queries, conditions_mutations=cond_mut)

    cond_mut.save_player_conditions.assert_not_awaited()


@pytest.mark.asyncio
async def test_skill_tool_consumes_and_persists_atomically():
    from sample_fixtures import make_db_mod

    from check_tools import _check_skill_impl
    from tools._helpers import SAMPLE_PLAYER, _make_context, _skill_mocks

    queries, mutations = _skill_mocks()
    queries.get_player = AsyncMock(return_value={**SAMPLE_PLAYER, "conditions": apply_condition([], "inspired")})
    db_mod, conn = make_db_mod()
    cond_mut = MagicMock()
    cond_mut.save_player_conditions = AsyncMock()

    await _check_skill_impl(
        _make_context(),
        "athletics",
        "moderate",
        "climbing",
        queries=queries,
        mutations=mutations,
        db_mod=db_mod,
        conditions_mutations=cond_mut,
    )

    cond_mut.save_player_conditions.assert_awaited_once()
    args, kwargs = cond_mut.save_player_conditions.call_args
    assert "inspired" not in [c["type"] for c in args[1]]
    # Atomic with the skill-advancement write: both run on the transaction's connection.
    assert kwargs.get("conn") is conn


# --- Group C (story-009): the remaining 3 modes — social / discover / gather ---


@pytest.mark.asyncio
async def test_gather_tool_consumes_and_persists_atomically():
    from sample_fixtures import FixedRng, make_db_mod

    from gathering_tools import _check_gather_impl

    player = {**SAMPLE_PLAYER, "conditions": apply_condition([], "inspired")}
    queries = MagicMock()
    queries.get_player = AsyncMock(return_value=player)
    mutations = MagicMock()
    mutations.add_inventory_item = AsyncMock()
    content = MagicMock()
    content.get_location = AsyncMock(
        return_value={"id": "greyvale_wilderness_north", "region": "greyvale", "resource_table": {"common": ["herb"]}}
    )
    content.get_gathering_nodes_at_location = AsyncMock(return_value=[])
    db_mod, conn = make_db_mod()
    cond_mut = MagicMock()
    cond_mut.save_player_conditions = AsyncMock()

    await _check_gather_impl(
        _ctx_with_bus(location_id="greyvale_wilderness_north"),
        "",
        queries=queries,
        mutations=mutations,
        content=content,
        gather_mutations=MagicMock(),
        db_mod=db_mod,
        conditions_mutations=cond_mut,
        rng=FixedRng(20),
    )

    cond_mut.save_player_conditions.assert_awaited_once()
    args, kwargs = cond_mut.save_player_conditions.call_args
    assert "inspired" not in [c["type"] for c in args[1]]
    # Atomic with node depletion + inventory grant: the consume runs on the gather tx connection.
    assert kwargs.get("conn") is conn


@pytest.mark.asyncio
async def test_gather_tool_no_condition_does_not_persist():
    from sample_fixtures import FixedRng, make_db_mod

    from gathering_tools import _check_gather_impl

    queries = MagicMock()
    queries.get_player = AsyncMock(return_value={**SAMPLE_PLAYER, "conditions": []})
    mutations = MagicMock()
    mutations.add_inventory_item = AsyncMock()
    content = MagicMock()
    content.get_location = AsyncMock(
        return_value={"id": "greyvale_wilderness_north", "region": "greyvale", "resource_table": {"common": ["herb"]}}
    )
    content.get_gathering_nodes_at_location = AsyncMock(return_value=[])
    db_mod, _ = make_db_mod()
    cond_mut = MagicMock()
    cond_mut.save_player_conditions = AsyncMock()

    await _check_gather_impl(
        _ctx_with_bus(location_id="greyvale_wilderness_north"),
        "",
        queries=queries,
        mutations=mutations,
        content=content,
        gather_mutations=MagicMock(),
        db_mod=db_mod,
        conditions_mutations=cond_mut,
        rng=FixedRng(20),
    )

    cond_mut.save_player_conditions.assert_not_awaited()


@pytest.mark.asyncio
@patch("check_discovery.publish_game_event", new_callable=AsyncMock)
async def test_discover_tool_consumes_and_persists_atomically(_evt):
    from sample_fixtures import make_db_mod

    from check_discovery import _check_discover_impl

    queries = MagicMock()
    queries.get_player = AsyncMock(return_value={**SAMPLE_PLAYER, "conditions": apply_condition([], "inspired")})
    content = MagicMock()
    content.get_location = AsyncMock(return_value=LOCATION_WITH_HIDDEN)
    mutations = MagicMock()
    mutations.set_player_flag = AsyncMock()
    db_mod, conn = make_db_mod()
    cond_mut = MagicMock()
    cond_mut.save_player_conditions = AsyncMock()

    with patch("check_resolution.dice_roll", return_value=_roll(15)):  # >= dc 12 -> discovered
        await _check_discover_impl(
            _make_context(location_id="test_location"),
            "perception",
            "bookshelf",
            content=content,
            queries=queries,
            mutations=mutations,
            db_mod=db_mod,
            conditions_mutations=cond_mut,
        )

    cond_mut.save_player_conditions.assert_awaited_once()
    args, kwargs = cond_mut.save_player_conditions.call_args
    assert "inspired" not in [c["type"] for c in args[1]]
    # Atomic with the success-only discovery flag write: both run on the transaction's connection.
    assert kwargs.get("conn") is conn
    flag_kwargs = mutations.set_player_flag.call_args.kwargs
    assert flag_kwargs.get("conn") is conn


@pytest.mark.asyncio
@patch("check_discovery.publish_game_event", new_callable=AsyncMock)
async def test_discover_tool_no_condition_does_not_persist(_evt):
    from sample_fixtures import make_db_mod

    from check_discovery import _check_discover_impl

    queries = MagicMock()
    queries.get_player = AsyncMock(return_value={**SAMPLE_PLAYER, "conditions": []})
    content = MagicMock()
    content.get_location = AsyncMock(return_value=LOCATION_WITH_HIDDEN)
    mutations = MagicMock()
    mutations.set_player_flag = AsyncMock()
    db_mod, _ = make_db_mod()
    cond_mut = MagicMock()
    cond_mut.save_player_conditions = AsyncMock()

    with patch("check_resolution.dice_roll", return_value=_roll(15)):
        await _check_discover_impl(
            _make_context(location_id="test_location"),
            "perception",
            "bookshelf",
            content=content,
            queries=queries,
            mutations=mutations,
            db_mod=db_mod,
            conditions_mutations=cond_mut,
        )

    cond_mut.save_player_conditions.assert_not_awaited()
    # No die to consume -> no tx is opened; the success flag write stays the plain (no-conn) path.
    mutations.set_player_flag.assert_awaited_once()
    assert mutations.set_player_flag.call_args.kwargs.get("conn") is None


def _social_consume_mocks(conditions: list) -> tuple[MagicMock, MagicMock, MagicMock]:
    queries = MagicMock()
    queries.get_player = AsyncMock(return_value={**SAMPLE_PLAYER, "conditions": conditions})
    queries.get_npc_disposition = AsyncMock(return_value="neutral")
    mutations = MagicMock()
    mutations.set_npc_disposition = AsyncMock()
    content = MagicMock()
    content.get_npc = AsyncMock(return_value={"id": "merchant_1", "default_disposition": "neutral"})
    return queries, mutations, content


@pytest.mark.asyncio
async def test_social_tool_consumes_and_persists_atomically():
    from sample_fixtures import FixedRng, make_db_mod

    from social_tools import _check_social_impl

    queries, mutations, content = _social_consume_mocks(apply_condition([], "inspired"))
    db_mod, conn = make_db_mod()
    cond_mut = MagicMock()
    cond_mut.save_player_conditions = AsyncMock()

    # FixedRng(18): persuasion success by 5+ shifts neutral -> friendly (a write fires).
    await _check_social_impl(
        _ctx_with_bus(),
        "merchant_1",
        "persuasion",
        "moderate",
        queries=queries,
        mutations=mutations,
        content=content,
        conditions_mutations=cond_mut,
        db_mod=db_mod,
        rng=FixedRng(18),
    )

    cond_mut.save_player_conditions.assert_awaited_once()
    args, kwargs = cond_mut.save_player_conditions.call_args
    assert "inspired" not in [c["type"] for c in args[1]]
    # Atomic with the disposition-shift write: both run on the transaction's connection.
    assert kwargs.get("conn") is conn
    assert mutations.set_npc_disposition.call_args.kwargs.get("conn") is conn


@pytest.mark.asyncio
async def test_social_tool_no_condition_does_not_persist():
    from sample_fixtures import FixedRng, make_db_mod

    from social_tools import _check_social_impl

    queries, mutations, content = _social_consume_mocks([])
    db_mod, _ = make_db_mod()
    cond_mut = MagicMock()
    cond_mut.save_player_conditions = AsyncMock()

    await _check_social_impl(
        _ctx_with_bus(),
        "merchant_1",
        "persuasion",
        "moderate",
        queries=queries,
        mutations=mutations,
        content=content,
        conditions_mutations=cond_mut,
        db_mod=db_mod,
        rng=FixedRng(18),
    )

    cond_mut.save_player_conditions.assert_not_awaited()
    # No die consumed -> no tx; the disposition shift stays the plain (no-conn) write.
    mutations.set_npc_disposition.assert_awaited_once()
    assert mutations.set_npc_disposition.call_args.kwargs.get("conn") is None
