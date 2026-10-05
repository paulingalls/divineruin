"""Use the real racial catalog and deterministic dice; self-inflicted zero HP must use the shared death path."""

import asyncio
import json
from unittest.mock import ANY, AsyncMock, MagicMock

import pytest
from combat._helpers import _call, _ctx_at_resolution, _resolve_deps
from livekit.agents.llm import ToolError
from sample_fixtures import make_context, make_db_mod, make_mock_room, published_payloads

import combat_death_save
import combat_phase
import combat_turn
import conditions
import event_types as E
import resonance as resonance_mod
from draethar_inner_fire import _inner_fire_impl
from session_data import CombatParticipant, CombatState
from tool_support import SOUND_HOLLOW_RISE, SOUND_PLAYER_FALLEN
from warm_prompts import format_combat_hot_line


def _hollowed(stage: int) -> list[dict]:
    conds: list[dict] = []
    for _ in range(stage):
        conds = conditions.apply_condition(conds, "hollowed")
    return conds


def _sounds(room) -> list[str]:
    """Sound names published to the mock room, in order (each rides a PLAY_SOUND payload)."""
    return [p["sound_name"] for p in published_payloads(room) if p["type"] == E.PLAY_SOUND]


def _player(race: str = "draethar", hp_current: int = 20) -> dict:
    return {
        "player_id": "player_1",
        "name": "Varr",
        "race": race,
        "class": "warden",
        "level": 5,
        "hp": {"current": hp_current, "max": 20},
    }


def _combat_ctx(*, resonance: int = 9, hp_current: int = 20, used: bool = False, room=None, player_conditions=None):
    ctx = make_context(room=room)
    session = ctx.userdata
    session.resonance.current = resonance
    session.party.primary.draethar_inner_fire_used = used
    session.combat_state = CombatState(
        combat_id="c1",
        participants=[
            CombatParticipant(
                id="player_1",
                name="Varr",
                type="player",
                initiative=14,
                hp_current=hp_current,
                hp_max=20,
                ac=14,
                conditions=player_conditions or [],
            ),
            CombatParticipant(id="goblin_1", name="Goblin", type="enemy", initiative=10, hp_current=7, hp_max=7, ac=13),
        ],
        initiative_order=["player_1", "goblin_1"],
    )
    return ctx


def _mocks(player: dict, *, roll_total: int = 4):
    mock_db, _conn = make_db_mod()
    queries = MagicMock()
    queries.get_player = AsyncMock(return_value=player)
    hp_mut = MagicMock()
    hp_mut.update_player_hp = AsyncMock()
    hp_mut.save_combat_state = AsyncMock()
    res_mut = MagicMock()
    res_mut.update_player_resonance = AsyncMock()
    res_events = MagicMock()
    res_events.publish_resonance_changed = AsyncMock()
    dice_mod = MagicMock()
    dice_mod.roll = MagicMock(return_value=MagicMock(total=roll_total))
    return mock_db, queries, hp_mut, res_mut, res_events, dice_mod


async def _invoke(ctx, mock_db, queries, hp_mut, res_mut, res_events, dice_mod):
    raw = await _inner_fire_impl(
        ctx,
        db_mod=mock_db,
        queries_mod=queries,
        hp_mutations_mod=hp_mut,
        resonance_mutations_mod=res_mut,
        resonance_events_mod=res_events,
        dice_mod=dice_mod,
    )
    return json.loads(raw)


async def test_inner_fire_drops_resonance_and_applies_fire_damage():
    ctx = _combat_ctx(resonance=9, hp_current=20)
    session = ctx.userdata
    mock_db, queries, hp_mut, res_mut, res_events, dice_mod = _mocks(_player(), roll_total=4)

    result = await _invoke(ctx, mock_db, queries, hp_mut, res_mut, res_events, dice_mod)

    res_mut.update_player_resonance.assert_awaited_once_with("player_1", 6, conn=ANY)
    assert session.resonance.current == 6
    res_events.publish_resonance_changed.assert_awaited_once()
    hp_mut.update_player_hp.assert_awaited_once_with("player_1", 16, conn=ANY)
    assert session.combat_state.get_participant("player_1").hp_current == 16
    assert session.party.primary.draethar_inner_fire_used is True
    assert result["resonance_reduced"] == 3
    assert result["fire_damage"] == 4
    assert result["hp_remaining"] == 16
    assert result["state"] == "flickering"  # 6 -> flickering (E2E: overreach dropped below 9)


async def test_inner_fire_state_matches_canonical_resonance_state():
    """The packet "state" derives from the post-cast Resonance. The impl reads the canonical
    session.resonance.state property; for a Draethar (flickering_bonus always 0) that equals
    resonance.get_resonance_state(new_resonance) — the pre-refactor expression. Locks that
    boundary so switching to .state can't silently diverge (review b760cbfcd9cd / 8cb769966bba)."""
    ctx = _combat_ctx(resonance=9, hp_current=20)
    mock_db, queries, hp_mut, res_mut, res_events, dice_mod = _mocks(_player(), roll_total=4)

    result = await _invoke(ctx, mock_db, queries, hp_mut, res_mut, res_events, dice_mod)

    new_resonance = 6  # 9 - 3 racial reduction
    assert ctx.userdata.resonance.flickering_bonus == 0  # the equivalence assumption, made explicit
    assert result["state"] == resonance_mod.get_resonance_state(new_resonance)


async def test_resonance_floors_at_zero():
    ctx = _combat_ctx(resonance=2)
    session = ctx.userdata
    mock_db, queries, hp_mut, res_mut, res_events, dice_mod = _mocks(_player(), roll_total=1)
    result = await _invoke(ctx, mock_db, queries, hp_mut, res_mut, res_events, dice_mod)
    res_mut.update_player_resonance.assert_awaited_once_with("player_1", 0, conn=ANY)
    assert session.resonance.current == 0
    assert result["resonance_reduced"] == 2  # only had 2 to give


async def test_hp_floors_at_zero():
    ctx = _combat_ctx(hp_current=3)
    session = ctx.userdata
    mock_db, queries, hp_mut, res_mut, res_events, dice_mod = _mocks(_player(hp_current=3), roll_total=6)
    result = await _invoke(ctx, mock_db, queries, hp_mut, res_mut, res_events, dice_mod)
    hp_mut.update_player_hp.assert_awaited_once_with("player_1", 0, conn=ANY)
    assert session.combat_state.get_participant("player_1").hp_current == 0
    assert result["hp_remaining"] == 0


async def test_burn_to_zero_falls_and_is_death_save_eligible():
    """Bug 16c5f8a0: the burn drove HP to 0 without knocking on _handle_hp_zero, so `is_fallen`
    stayed False and the Draethar was invisible to every consumer of that flag — un-downable AND
    un-stabilizable for the rest of the fight — while the hot line already read "fallen".

    The consumers are asserted against the state the burn REALLY produced, not a hand-built
    participant: building the 0-HP participant by hand is what let the bug's own recorded
    falsifier red both before and after the fix.
    """
    room = make_mock_room()
    ctx = _combat_ctx(hp_current=3, room=room)
    session = ctx.userdata
    mock_db, queries, hp_mut, res_mut, res_events, dice_mod = _mocks(_player(hp_current=3), roll_total=6)

    await _invoke(ctx, mock_db, queries, hp_mut, res_mut, res_events, dice_mod)

    p = session.combat_state.get_participant("player_1")
    assert p.is_fallen is True
    assert p.is_dead is False  # overkill 3 < hp_max 20 — a burn-out is not instant death
    assert SOUND_PLAYER_FALLEN in _sounds(room)
    assert "Varr(fallen)" in (format_combat_hot_line(session.combat_state) or "")
    assert combat_phase._wrap(session.combat_state).death_saves_due == ["player_1"]
    assert combat_death_save._resolve_faller(session.combat_state, None) is p
    assert combat_death_save._resolve_faller(session.combat_state, "player_1") is p


async def test_burn_to_zero_raises_a_stage2_hollowed_draethar():
    """The door's other verdict, reached the same way: a Stage-2+ Hollowed player at 0 HP does NOT
    fall — their corpse rises as a hostile Temporary Hollowed combatant (M4.4 story-008). Flipping
    `type` off "player" is what suppresses the players.data HP write and the concentration break,
    exactly as it does on the attack path — the echo's HP is the monster's, not the player's.
    """
    room = make_mock_room()
    ctx = _combat_ctx(hp_current=3, room=room, player_conditions=_hollowed(2))
    session = ctx.userdata
    mock_db, queries, hp_mut, res_mut, res_events, dice_mod = _mocks(_player(hp_current=3), roll_total=6)
    break_mod = _break_mod(None)

    result = json.loads(
        await _inner_fire_impl(
            ctx,
            db_mod=mock_db,
            queries_mod=queries,
            hp_mutations_mod=hp_mut,
            resonance_mutations_mod=res_mut,
            resonance_events_mod=res_events,
            dice_mod=dice_mod,
            concentration_break_mod=break_mod,
        )
    )

    p = session.combat_state.get_participant("player_1")
    assert p.type == "temporary_hollowed"
    assert p.hp_current == 10  # max(1, hp_max // 2)
    assert any(c["type"] == "temporary_hollowed" for c in p.conditions)
    assert p.is_fallen is False
    assert result["rose_hollowed"] is True
    assert result["hp_remaining"] == 10  # the echo's HP, not the player's 0
    assert SOUND_HOLLOW_RISE in _sounds(room)
    hp_mut.update_player_hp.assert_not_awaited()
    break_mod.break_concentration_on_damage.assert_not_awaited()
    assert hp_mut.save_combat_state.await_args.args[1]["participants"][0]["type"] == "temporary_hollowed"


async def test_persists_combat_state_after_self_damage():
    # combat_turn always pairs update_player_hp with save_combat_state; otherwise a mid-encounter
    # crash restores stale participant HP from combat_instances (heal-by-crash). Pin the persist
    # with the post-damage state.
    ctx = _combat_ctx(resonance=9, hp_current=20)
    session = ctx.userdata
    mock_db, queries, hp_mut, res_mut, res_events, dice_mod = _mocks(_player(), roll_total=4)

    await _invoke(ctx, mock_db, queries, hp_mut, res_mut, res_events, dice_mod)

    hp_mut.save_combat_state.assert_awaited_once_with("c1", session.combat_state.to_dict(), conn=ANY)
    assert hp_mut.save_combat_state.await_args.args[1]["participants"][0]["hp_current"] == 16


def _break_mod(return_value):
    mod = MagicMock()
    mod.break_concentration_on_damage = AsyncMock(return_value=return_value)
    return mod


async def test_inner_fire_runs_concentration_break_on_self_damage():
    ctx = _combat_ctx(resonance=9, hp_current=20)
    session = ctx.userdata
    session.concentration.spell_id = "arcane_fly"
    mock_db, queries, hp_mut, res_mut, res_events, dice_mod = _mocks(_player(), roll_total=4)
    break_mod = _break_mod("arcane_fly")

    result = json.loads(
        await _inner_fire_impl(
            ctx,
            db_mod=mock_db,
            queries_mod=queries,
            hp_mutations_mod=hp_mut,
            resonance_mutations_mod=res_mut,
            resonance_events_mod=res_events,
            dice_mod=dice_mod,
            concentration_break_mod=break_mod,
        )
    )

    break_mod.break_concentration_on_damage.assert_awaited_once()
    args, kwargs = break_mod.break_concentration_on_damage.call_args
    assert args[0] is session
    assert args[1] == 4  # the 1d6 fire damage
    assert kwargs["incapacitated"] is False  # 20 - 4 = 16 HP remaining
    assert kwargs["damaged_player_id"] == "player_1"
    assert result["concentration_broken"] == "arcane_fly"


async def test_inner_fire_persists_combat_state_after_concentration_condition_drop():
    ctx = _combat_ctx(resonance=9, hp_current=20)
    session = ctx.userdata
    session.combat_state.get_participant("player_1").conditions = [
        {"type": "blessed", "duration": None, "source": "divine_bless", "stacks": 1}
    ]
    mock_db, queries, hp_mut, res_mut, res_events, dice_mod = _mocks(_player(), roll_total=4)

    async def _strip_blessed(sess, _damage, *, incapacitated, damaged_player_id, combat_state, conn):
        for p in combat_state.participants:
            p.conditions = [c for c in p.conditions if c["type"] != "blessed"]
        return "divine_bless"

    break_mod = MagicMock()
    break_mod.break_concentration_on_damage = AsyncMock(side_effect=_strip_blessed)

    await _inner_fire_impl(
        ctx,
        db_mod=mock_db,
        queries_mod=queries,
        hp_mutations_mod=hp_mut,
        resonance_mutations_mod=res_mut,
        resonance_events_mod=res_events,
        dice_mod=dice_mod,
        concentration_break_mod=break_mod,
    )

    last_state = hp_mut.save_combat_state.await_args.args[1]
    assert last_state["participants"][0]["conditions"] == []


async def test_inner_fire_self_damage_to_zero_passes_incapacitated():
    ctx = _combat_ctx(hp_current=3)
    mock_db, queries, hp_mut, res_mut, res_events, dice_mod = _mocks(_player(hp_current=3), roll_total=6)
    break_mod = _break_mod(None)

    await _inner_fire_impl(
        ctx,
        db_mod=mock_db,
        queries_mod=queries,
        hp_mutations_mod=hp_mut,
        resonance_mutations_mod=res_mut,
        resonance_events_mod=res_events,
        dice_mod=dice_mod,
        concentration_break_mod=break_mod,
    )

    _args, kwargs = break_mod.break_concentration_on_damage.call_args
    assert kwargs["incapacitated"] is True


async def test_non_draethar_rejected():
    ctx = _combat_ctx()
    session = ctx.userdata
    mock_db, queries, hp_mut, res_mut, res_events, dice_mod = _mocks(_player(race="human"))
    with pytest.raises(ToolError, match="Draethar"):
        await _invoke(ctx, mock_db, queries, hp_mut, res_mut, res_events, dice_mod)
    res_mut.update_player_resonance.assert_not_awaited()
    hp_mut.update_player_hp.assert_not_awaited()
    assert session.party.primary.draethar_inner_fire_used is False


async def test_already_used_this_encounter_rejected():
    ctx = _combat_ctx(used=True)
    mock_db, queries, hp_mut, res_mut, res_events, dice_mod = _mocks(_player())
    with pytest.raises(ToolError, match="already"):
        await _invoke(ctx, mock_db, queries, hp_mut, res_mut, res_events, dice_mod)
    res_mut.update_player_resonance.assert_not_awaited()
    hp_mut.update_player_hp.assert_not_awaited()


async def test_no_combat_rejected():
    ctx = make_context()
    ctx.userdata.resonance.current = 9
    mock_db, queries, hp_mut, res_mut, res_events, dice_mod = _mocks(_player())
    with pytest.raises(ToolError, match="combat"):
        await _invoke(ctx, mock_db, queries, hp_mut, res_mut, res_events, dice_mod)
    queries.get_player.assert_not_awaited()  # combat gate fires before the player fetch
    res_mut.update_player_resonance.assert_not_awaited()
    hp_mut.update_player_hp.assert_not_awaited()


async def test_inner_fire_at_a_pause_is_not_undone_by_the_held_blow():
    """Both halves real: the REAL Beat-3 hold, paused on a REAL rolled-but-unapplied enemy blow,
    with the REAL Inner Fire tool burning HP in the gap.

    This is the seam the two stories left between them. story-016 holds the enemy's blow with an
    absolute ``target_hp_remaining`` captured at roll time; story-026 routed the burn through the
    zero-HP door but it still writes ``hp_current`` on the live participant; and the combat prompt
    tells the DM that Inner Fire is one of exactly three things it may activate mid-fight. Neither
    story's own tests can see it — 016's never spend a resource at the pause, and 026's never hold
    a blow — so it needed a test that drives both.
    """
    ctx = _ctx_at_resolution(player_hp=20, enemy_hp=20, reaction_ids=("skirmisher_sidestep", "rogue_uncanny_dodge"))
    deps = _resolve_deps(damage=3)
    deps["resonance_mutations"] = MagicMock(update_player_resonance=AsyncMock())
    session = ctx.userdata
    session.resonance.current = 9

    await _call(ctx, deps)  # the ally commit; the enemy blow is held
    await _call(ctx, deps)  # the pre-roll window
    await _call(ctx, deps)  # the roll lands in the held action; the damage does not
    assert session.combat_state.open_window["stage"] == "post_roll"
    assert session.combat_state.get_participant("player_1").hp_current == 20

    mock_db, queries, hp_mut, res_mut, res_events, dice_mod = _mocks(_player(), roll_total=6)
    burn = await _invoke(ctx, mock_db, queries, hp_mut, res_mut, res_events, dice_mod)
    assert burn["hp_remaining"] == 14

    await _call(ctx, deps)  # the window closes and the held blow finally lands

    assert session.combat_state.get_participant("player_1").hp_current == 11


async def test_inner_fire_serialises_against_the_phase_loop():
    """Inner Fire writes the LIVE participant, and resolve_phase ADOPTS a deep copy — so the two
    have to serialise on ``session.combat_state_lock`` or the burn is silently undone.

    resolve_phase copies ``combat_state``, works the copy through its transaction, and rebinds
    ``session.combat_state`` to it post-commit. An unlocked writer that lands in that gap has
    everything it wrote erased on adoption. That was one ``hp_current`` assignment until
    story-026, which routed the burn through ``_handle_hp_zero`` and so widened the loss to
    ``is_fallen``/``is_dead``/``type``/``conditions`` — a Draethar who burned themselves down and
    FELL is stood back up with the round's once-per-encounter spend already gone.

    The gate suspends the phase AFTER its deep copy (the copy is taken inside the transaction,
    before this write), which is the only ordering in which the defect exists: gating the
    transaction's entry instead lets the burn land before the copy, where it survives for the
    wrong reason and the guard certifies nothing.
    """
    ctx = _ctx_at_resolution(player_hp=4, enemy_hp=20, room=make_mock_room())
    deps = _resolve_deps(damage=3)
    deps["resonance_mutations"] = MagicMock(update_player_resonance=AsyncMock())

    entered, release = asyncio.Event(), asyncio.Event()

    async def gated_save(*args, **kwargs):
        entered.set()
        await release.wait()

    deps["mutations"].save_combat_state = AsyncMock(side_effect=gated_save)

    phase = asyncio.create_task(combat_turn._resolve_phase_impl(ctx, **deps))
    await entered.wait()

    burn = asyncio.create_task(_invoke(ctx, *_mocks(_player(hp_current=4), roll_total=6)))
    await asyncio.sleep(0)
    release.set()
    await phase
    await burn

    burned = ctx.userdata.combat_state.get_participant("player_1")
    assert burned.hp_current == 0, "the phase adopted a copy taken before the burn and healed it away"
    assert burned.is_fallen is True, "story-026's fall went with it — nothing owes this player a death save"
    assert ctx.userdata.party.primary.draethar_inner_fire_used is True
