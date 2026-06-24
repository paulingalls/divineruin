"""M4.8 story-003: consumer write-back — consume + persist the beneficial die.

The single-use +1d4 (Blessed/Inspired, story-001/002) is now made live: player-initiated rolls
consume it and persist the removal, while engine-auto saves (Beat-4 tick-clear, concentration-break)
suppress it via the new bonus_dice_eligible flag (customer decision 6102eca13319). In-combat the die
is consumed ONCE per multi-swing declaration. Grouped: A) eligibility flag + engine-auto suppression,
B) in-combat consume-once, C) out-of-combat persist."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sample_fixtures import FixedRng

from check_resolution_save import resolve_saving_throw
from conditions import apply_condition

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
