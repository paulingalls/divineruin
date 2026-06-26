"""M4.8 story-007: multi-target Bless — OOC cast path + max_targets cap.

The single-target Bless producer (story-004) lands `blessed` on ONE target. Bless is specced
"up to three allies"; this story extends the OUT-OF-COMBAT cast (`_resolve_cast`, gated on not
session.in_combat) to apply + persist `blessed` to EACH named ally's players.data, capped by the
spell's `max_targets` (reject >cap with a ToolError, before any write). The shared foundation
(`Spell.max_targets`, `spells.validate_target_count`) is reused by the in-combat path (story-012).
The single-target path stays unchanged when `target_ids` is absent.
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from combat.test_bless_producer import _caster  # reuse the OOC caster-dict builder
from livekit.agents.llm import ToolError
from sample_fixtures import make_context, make_db_mod

import combat_ability
import conditions
import spell_casting
import spells
from combat_ability import AbilityCastOutcome, _resolve_ability_packet
from declarations import Declaration, DeclarationType, resolve_declaration
from session_data import CombatParticipant, CombatState
from spell_casting import _UNCHANGED, CastResult
from spells import Spell


def _bless3(applies_condition: str | None = "blessed") -> Spell:
    """A divine Bless (resonance 0, focus 0) capped at 3 targets — clears the gates with only the
    multi-target producer hook active."""
    return Spell(
        id="divine_bless",
        name="Bless",
        source="divine",
        spell_tier="minor",
        focus_cost=0,
        mechanics="Up to three allies gain +1d4.",
        narration_cue="Warmth settling into bones.",
        audio_cue="",
        resonance_by_source={"divine": 0},
        terrain_effects={},
        concentration=False,
        applies_condition=applies_condition,
        max_targets=3,
    )


async def _cast_ooc_multi(spell, *, caster, target_id=None, target_ids=None, rows=None):
    """Drive _cast_spell_impl out of combat with target_ids. Returns (packet, cond_mut, get_player)."""
    ctx = make_context(player_id=caster["player_id"])
    mock_db, _conn = make_db_mod()
    table = {caster["player_id"]: caster, **(rows or {})}

    async def _get_player(pid, *, conn=None, for_update=False):
        return table.get(pid)

    queries = MagicMock(get_player=AsyncMock(side_effect=_get_player))
    persistence = MagicMock(update_player_resources=AsyncMock())
    res_mut = MagicMock(update_player_resonance=AsyncMock())
    events = MagicMock(publish_resonance_changed=AsyncMock())
    # Wire the REAL targeting validators into the mocked catalog so the gate paths exercise real logic.
    spells_mod = MagicMock(
        get_spell=MagicMock(return_value=spell),
        validate_target_count=spells.validate_target_count,
        normalize_target_list=spells.normalize_target_list,
    )
    cond_mut = MagicMock(save_player_conditions=AsyncMock())
    raw = await spell_casting._cast_spell_impl(
        ctx,
        spell.id,
        target_id=target_id,
        target_ids=target_ids,
        db_mod=mock_db,
        queries_mod=queries,
        persistence_mod=persistence,
        resonance_mutations_mod=res_mut,
        resonance_events_mod=events,
        spells_mod=spells_mod,
        conditions_mod=conditions,
        conditions_mutations_mod=cond_mut,
    )
    return json.loads(raw), cond_mut, queries.get_player


@pytest.mark.asyncio
async def test_ooc_three_allies_each_get_blessed():
    # AC1: name three allies -> each ally's players.data gets blessed persisted.
    rows = {f"ally_{i}": _caster(f"ally_{i}", conditions_list=[]) for i in (1, 2, 3)}
    packet, cond_mut, _gp = await _cast_ooc_multi(
        _bless3(), caster=_caster(), target_ids=["ally_1", "ally_2", "ally_3"], rows=rows
    )

    assert packet["condition_applied"] == "blessed"
    assert cond_mut.save_player_conditions.await_count == 3
    persisted_ids = {call.args[0] for call in cond_mut.save_player_conditions.await_args_list}
    assert persisted_ids == {"ally_1", "ally_2", "ally_3"}
    for call in cond_mut.save_player_conditions.await_args_list:
        assert "blessed" in [c["type"] for c in call.args[1]]


@pytest.mark.asyncio
async def test_ooc_over_cap_rejects_before_write():
    # AC2: more than max_targets (3) is rejected with a ToolError and deducts/persists nothing.
    rows = {f"ally_{i}": _caster(f"ally_{i}", conditions_list=[]) for i in (1, 2, 3, 4)}
    with pytest.raises(ToolError, match="at most 3"):
        await _cast_ooc_multi(
            _bless3(), caster=_caster(), target_ids=["ally_1", "ally_2", "ally_3", "ally_4"], rows=rows
        )


@pytest.mark.asyncio
async def test_ooc_single_target_path_unchanged():
    # AC3: a single-target cast (target_id, no target_ids) still persists to exactly the one target.
    ally = _caster("ally_2", conditions_list=[])
    packet, cond_mut, _gp = await _cast_ooc_multi(
        _bless3(), caster=_caster(), target_id="ally_2", rows={"ally_2": ally}
    )

    assert packet["condition_applied"] == "blessed"
    cond_mut.save_player_conditions.assert_awaited_once()
    assert cond_mut.save_player_conditions.await_args.args[0] == "ally_2"


@pytest.mark.asyncio
async def test_ooc_mix_nonplayer_narrates_player_persists():
    # AC4: a non-player ally (absent from the table) narrates without a write; player allies persist.
    rows = {"ally_1": _caster("ally_1", conditions_list=[])}  # "kael" intentionally absent (non-player)
    packet, cond_mut, _gp = await _cast_ooc_multi(_bless3(), caster=_caster(), target_ids=["ally_1", "kael"], rows=rows)

    assert packet["condition_applied"] == "blessed"  # landed on >=1 target
    cond_mut.save_player_conditions.assert_awaited_once()  # only the player ally persisted
    assert cond_mut.save_player_conditions.await_args.args[0] == "ally_1"


@pytest.mark.asyncio
async def test_ooc_multi_target_packet_names_voiced_allies():
    # Per-target identity: the multi-target packet lists the blessed ally ids so the DM names each one.
    rows = {f"ally_{i}": _caster(f"ally_{i}", conditions_list=[]) for i in (1, 2, 3)}
    packet, _cm, _gp = await _cast_ooc_multi(
        _bless3(), caster=_caster(), target_ids=["ally_1", "ally_2", "ally_3"], rows=rows
    )
    assert packet["condition_targets"] == ["ally_1", "ally_2", "ally_3"]


@pytest.mark.asyncio
async def test_ooc_single_target_has_no_condition_targets_key():
    # The single-target path keeps its shape — condition_targets is multi-target-only.
    ally = _caster("ally_2", conditions_list=[])
    packet, _cm, _gp = await _cast_ooc_multi(_bless3(), caster=_caster(), target_id="ally_2", rows={"ally_2": ally})
    assert "condition_targets" not in packet
    assert packet["target_id"] == "ally_2"


@pytest.mark.asyncio
async def test_ooc_both_target_args_rejected():
    # Ambiguous both-args -> ToolError before any write (gate-first), nothing persisted.
    ally = _caster("ally_1", conditions_list=[])
    with pytest.raises(ToolError, match="not both"):
        await _cast_ooc_multi(
            _bless3(), caster=_caster(), target_id="ally_1", target_ids=["ally_1"], rows={"ally_1": ally}
        )


@pytest.mark.asyncio
async def test_ooc_empty_target_ids_rejected_no_self_cast():
    # target_ids=[] must NOT silently self-cast — it raises (name at least one ally).
    with pytest.raises(ToolError, match="at least one ally"):
        await _cast_ooc_multi(_bless3(), caster=_caster(), target_ids=[])


@pytest.mark.asyncio
async def test_ooc_all_duplicate_targets_collapsing_to_one_persist():
    # Dedup is order-preserving and runs before the apply loop: 3 dupes -> ONE write, not three.
    rows = {"ally_1": _caster("ally_1", conditions_list=[])}
    packet, cond_mut, _gp = await _cast_ooc_multi(
        _bless3(), caster=_caster(), target_ids=["ally_1", "ally_1", "ally_1"], rows=rows
    )
    assert packet["condition_applied"] == "blessed"
    cond_mut.save_player_conditions.assert_awaited_once()  # deduped to a single target
    assert packet["condition_targets"] == ["ally_1"]


@pytest.mark.asyncio
async def test_ooc_dupes_do_not_consume_the_cap():
    # Dedup happens BEFORE the cap check: 4 ids that dedup to 3 must pass a cap of 3.
    rows = {f"ally_{i}": _caster(f"ally_{i}", conditions_list=[]) for i in (1, 2, 3)}
    packet, cond_mut, _gp = await _cast_ooc_multi(
        _bless3(), caster=_caster(), target_ids=["ally_1", "ally_2", "ally_3", "ally_1"], rows=rows
    )
    assert packet["condition_targets"] == ["ally_1", "ally_2", "ally_3"]
    assert cond_mut.save_player_conditions.await_count == 3


@pytest.mark.asyncio
async def test_ooc_target_ids_on_uncapped_spell_rejected():
    # A spell with no max_targets is single-target only: target_ids is refused (closes the revival
    # Hollow-gate bypass — revival spells have no max_targets, so multi-target on them is rejected).
    uncapped = Spell(
        id="divine_revivify",
        name="Revivify",
        source="divine",
        spell_tier="minor",
        focus_cost=0,
        mechanics="Restore a fallen ally.",
        narration_cue="Breath returns.",
        audio_cue="",
        resonance_by_source={"divine": 0},
        terrain_effects={},
        concentration=False,
        applies_condition="blessed",
        max_targets=None,
    )
    with pytest.raises(ToolError, match="does not support multiple targets"):
        await _cast_ooc_multi(uncapped, caster=_caster(), target_ids=["ally_1"], rows={"ally_1": _caster("ally_1")})


# --- In-combat multi-target (M4.8 story-012): land blessed on each ally participant ---


def _combat_state_with_allies() -> CombatState:
    return CombatState(
        combat_id="c_mt",
        participants=[
            CombatParticipant(
                id="caster", name="Cleric", type="player", initiative=15, hp_current=25, hp_max=25, ac=14
            ),
            CombatParticipant(id="ally_1", name="A1", type="companion", initiative=10, hp_current=20, hp_max=20, ac=13),
            CombatParticipant(id="ally_2", name="A2", type="companion", initiative=9, hp_current=20, hp_max=20, ac=13),
            CombatParticipant(id="ally_3", name="A3", type="companion", initiative=8, hp_current=20, hp_max=20, ac=13),
        ],
        initiative_order=["caster", "ally_1", "ally_2", "ally_3"],
    )


def _ability_decl(*, target_id=None, target_ids=None) -> Declaration:
    return Declaration(type=DeclarationType.ABILITY, action="divine_bless", target_id=target_id, target_ids=target_ids)


def _p(state: CombatState, pid: str) -> CombatParticipant:
    p = state.get_participant(pid)
    assert p is not None
    return p


def test_resolve_declaration_parses_target_ids():
    decl = resolve_declaration({"type": "ability", "action": "divine_bless", "target_ids": ["ally_1", "ally_2"]})
    assert decl.target_ids == ["ally_1", "ally_2"]
    # Absent -> None (single-target declarations unchanged).
    assert resolve_declaration({"type": "ability", "action": "divine_bless", "target_id": "ally_1"}).target_ids is None


def test_land_condition_on_participants_blesses_each():
    state = _combat_state_with_allies()
    caster = _p(state, "caster")
    voiced = combat_ability.land_condition_on_participants(
        state, caster, _ability_decl(target_ids=["ally_1", "ally_2", "ally_3"]), "blessed", source="divine_bless"
    )
    assert voiced == ["ally_1", "ally_2", "ally_3"]
    for aid in ("ally_1", "ally_2", "ally_3"):
        assert "blessed" in [c["type"] for c in _p(state, aid).conditions]
    assert "blessed" not in [c["type"] for c in caster.conditions]  # caster not targeted


def test_land_condition_on_participants_dedups_and_drops_off_state():
    state = _combat_state_with_allies()
    caster = _p(state, "caster")
    voiced = combat_ability.land_condition_on_participants(
        state, caster, _ability_decl(target_ids=["ally_1", "ally_1", "ghost"]), "blessed", source="x"
    )
    assert voiced == ["ally_1"]  # dedup (one ally_1) + "ghost" not on state is dropped


def test_land_condition_on_participants_single_and_self():
    state = _combat_state_with_allies()
    caster = _p(state, "caster")
    # single target_id (no target_ids) — back-compat with the singular path
    assert combat_ability.land_condition_on_participants(
        state, caster, _ability_decl(target_id="ally_1"), "blessed", source="x"
    ) == ["ally_1"]
    # no target -> self-cast voices the caster
    assert combat_ability.land_condition_on_participants(state, caster, _ability_decl(), "blessed", source="x") == [
        "caster"
    ]


# --- In-combat resolution wiring (_resolve_ability_packet) + declare-gate (_prevalidate_ability_focus) ---


def _cast_resolver_returning(packet: dict) -> MagicMock:
    mod = MagicMock()
    mod._resolve_cast = AsyncMock(
        return_value=CastResult(
            packet=dict(packet), new_resonance=None, concentration_spell_id=_UNCHANGED, generated=0, events=[]
        )
    )
    return mod


@pytest.mark.asyncio
async def test_incombat_resolve_blesses_each_and_names_them():
    # _resolve_ability_packet with a multi-target Bless declaration lands blessed on EACH target
    # participant and surfaces the voiced ids in the packet for the DM.
    state = _combat_state_with_allies()
    caster = _p(state, "caster")
    cast_resolver = _cast_resolver_returning({"condition_applied": "blessed"})
    summary = await _resolve_ability_packet(
        make_context(player_id="caster").userdata,
        caster,
        _ability_decl(target_ids=["ally_1", "ally_2", "ally_3"]),
        state=state,
        cast_resolver=cast_resolver,
        conn=object(),
        player={"player_id": "caster"},
        cast_outcome=AbilityCastOutcome(),
    )
    assert summary["cast"]["condition_applied"] == "blessed"
    assert summary["cast"]["condition_targets"] == ["ally_1", "ally_2", "ally_3"]
    for aid in ("ally_1", "ally_2", "ally_3"):
        assert "blessed" in [c["type"] for c in _p(state, aid).conditions]


@pytest.mark.asyncio
async def test_incombat_resolve_drops_signal_when_none_land():
    # All target_ids off the working state -> nothing lands -> condition_applied dropped, no targets key.
    state = _combat_state_with_allies()
    caster = _p(state, "caster")
    cast_resolver = _cast_resolver_returning({"condition_applied": "blessed"})
    summary = await _resolve_ability_packet(
        make_context(player_id="caster").userdata,
        caster,
        _ability_decl(target_ids=["ghost_1", "ghost_2"]),
        state=state,
        cast_resolver=cast_resolver,
        conn=object(),
        player={"player_id": "caster"},
        cast_outcome=AbilityCastOutcome(),
    )
    assert "condition_applied" not in summary["cast"]
    assert "condition_targets" not in summary["cast"]


@pytest.mark.asyncio
async def test_declare_gate_rejects_over_cap_multitarget():
    # The declare-time spell-aware gate rejects an over-cap multi-target Bless (reuses the SSOT
    # normalize_target_list) BEFORE the resolution loop — a ToolError, no state write.
    import combat_packet

    decl = _ability_decl(target_ids=["a", "b", "c", "d"])  # 4 > max_targets 3
    adv = SimpleNamespace(packets=[SimpleNamespace(declaration=decl, actor_id="caster")])
    state = _combat_state_with_allies()
    session = make_context(player_id="caster").userdata
    queries = MagicMock(get_player=AsyncMock(return_value={"player_id": "caster", "focus": {"current": 10, "max": 10}}))
    cast_resolver = MagicMock(_gate_spell=MagicMock(return_value=_bless3()))

    with pytest.raises(ToolError, match="at most 3"):
        await combat_packet._prevalidate_ability_focus(
            session, state, adv, conn=object(), queries=queries, cast_resolver=cast_resolver
        )
