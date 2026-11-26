"""Cone aim and recipient delivery through the phase boundary."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from acceptance._capstone_helpers import _d20, _resolve_round
from combat.test_area_spell_recipients import area_party as area_party
from combat.test_spell_damage_lands import load_combat
from combat.test_spell_damage_lands import spell_fight as spell_fight
from voice_condition_fixtures import participant


@pytest.mark.parametrize("elevated", [False, True])
@pytest.mark.parametrize("outside", [(0, 20, 0), (-1, 0, 0), (30, 15.01, 0), (30.01, 0, 0), (20, 0, 10.01)])
async def test_corruption_wave_cone_commits_each_player_once(area_party, elevated, outside):
    from combat.test_spell_damage_lands import saved_player
    from creature_combat_helpers import catalog
    from creature_combat_helpers import participant as enemy_participant

    import check_resolution_save
    import combat_turn
    from creature_combat import translate_creature
    from declaration_payloads import AttackDecl, DefendDecl

    ctx, (ally, beside) = area_party
    state = ctx.userdata.combat_state
    row = next(r for r in catalog() if r["id"] == "hollow_veilrender")
    boss = enemy_participant(translate_creature(row, encounter_id="wave", enemy_id="foe", role="standard"))
    state.participants[1] = boss
    positions = state.spatial["positions"]
    positions[ctx.userdata.player_id] = {"x": 20, "y": 0, "z": 0}
    positions[ally] = {"x": 30, "y": 0 if elevated else 15, "z": 15 if elevated else 0}
    positions[beside] = dict(zip(("x", "y", "z"), outside, strict=True))
    original = check_resolution_save.roll_participant_save
    wave = []

    def save(target, key, dc, context, **kwargs):
        is_wave = context == "poisoned"
        if is_wave:
            wave.append((target.id, key, dc))
        with patch("check_resolution.dice_roll", return_value=_d20(1 if is_wave and target.id != ally else 20)):
            return original(target, key, dc, context, **kwargs)

    await combat_turn.declare_phase(
        ctx,
        [
            DefendDecl(reshape=[], kind="defend", actor_id=ctx.userdata.player_id),
            AttackDecl(
                quick_fingers_mode="",
                quick_fingers_item="",
                reshape=[],
                kind="attack",
                actor_id=boss.id,
                action="Corruption Wave",
                target_id=ctx.userdata.player_id,
                held_item_id="",
                rider="",
            ),
        ],
    )
    ctx.userdata.combat_state = await load_combat(state.combat_id)
    with (
        patch("check_resolution_save.roll_participant_save", side_effect=save),
        patch("combat_enemy_action.dice_roll", return_value=SimpleNamespace(total=7)),
    ):
        result = await _resolve_round(ctx)
    packet = next(p for p in result["packets"] if p["actor_id"] == boss.id and "targets" in p)
    assert wave == [(ctx.userdata.player_id, "CON", 16), (ally, "CON", 16)]
    assert [r["damage"] for r in packet["targets"]] == [7, 3]
    saved = await load_combat(state.combat_id)
    for name, damage in ((ctx.userdata.player_id, 7), (ally, 3), (beside, 0)):
        actor = participant(saved, name)
        assert actor.hp_current == (await saved_player(name))["hp"]["current"] == 28 - damage
        assert any(c["type"] == "poisoned" for c in actor.conditions) == (damage == 7)
    assert participant(saved, boss.id).hp_current == boss.hp_max


async def test_cone_refuses_coincident_aim_before_writes(area_party):
    from dataclasses import replace

    from combat.test_veilrender import boss_state
    from livekit.agents.llm import ToolError

    import combat_turn
    from declaration_payloads import AttackDecl

    ctx, _ = area_party
    state = ctx.userdata.combat_state
    _, boss, _ = boss_state()
    state.participants[1] = replace(boss, id="foe")
    before = state.to_dict()
    with pytest.raises(ToolError, match="aim must differ"):
        await combat_turn.declare_phase(
            ctx,
            [
                AttackDecl(
                    quick_fingers_mode="",
                    quick_fingers_item="",
                    reshape=[],
                    kind="attack",
                    actor_id="foe",
                    action="Corruption Wave",
                    target_id=ctx.userdata.player_id,
                    held_item_id="",
                    rider="",
                )
            ],
        )
    assert ctx.userdata.combat_state.to_dict() == before
