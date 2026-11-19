"""Participant-anchored areas land through the phase transaction."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from acceptance._capstone_helpers import _d20, _enemy, _resolve_round
from combat.test_spell_damage_lands import declare_spell, load_combat, prepare_spell
from combat.test_spell_damage_lands import spell_fight as spell_fight
from voice_condition_fixtures import participant, place_actors


async def add_enemies(ctx, points):
    state = ctx.userdata.combat_state
    for name in points:
        if state.get_participant(name) is None:
            state.participants.append(_enemy(name, 100))
            state.initiative_order.append(name)
    place_actors(state)
    state.spatial["positions"][ctx.userdata.player_id] = {"x": -100, "y": 0, "z": 0}
    for name, (x, y, z) in points.items():
        state.spatial["positions"][name] = {"x": x, "y": y, "z": z}


async def resolve_cast(ctx):
    with (
        patch("check_resolution.dice_roll", return_value=_d20(1)),
        patch("dice.roll", return_value=SimpleNamespace(total=7)),
    ):
        result = await _resolve_round(ctx)
    return next(p["cast"] for p in result["packets"] if p["actor_id"] == ctx.userdata.player_id)


@pytest.mark.parametrize(
    "spell_id,points,anchors,covered",
    [
        (
            "arcane_elemental_burst",
            {"foe": (0, 0, 0), "edge": (0, 0, 15), "out": (0, 0, 15.01)},
            ["foe"],
            {"foe", "edge"},
        ),
        ("primal_ice_storm", {"foe": (0, 0, 0), "edge": (0, 20, 0), "out": (0, 20.01, 0)}, ["foe"], {"foe", "edge"}),
        (
            "divine_flame_strike",
            {"foe": (0, 0, 0), "edge": (10, 0, 40), "out": (0, 0, 40.01), "below": (0, 0, -0.01)},
            ["foe"],
            {"foe", "edge"},
        ),
        (
            "arcane_meteor_swarm",
            {"foe": (0, 0, 0), "second": (30, 0, 0), "overlap": (15, 0, 0), "out": (0, 21, 0)},
            ["foe", "second"],
            {"foe", "second", "overlap"},
        ),
        (
            "arcane_lightning_bolt",
            {
                "foe": (-80, 0, 0),
                "edge": (0, 2.5, 0),
                "out": (-50, 2.51, 0),
                "behind": (-101, 0, 0),
                "beyond": (0.01, 0, 0),
            },
            ["foe"],
            {"foe", "edge"},
        ),
    ],
)
async def test_authored_shapes_land_on_union_once(spell_fight, spell_id, points, anchors, covered):
    ctx = spell_fight
    await prepare_spell(ctx, spell_id)
    await add_enemies(ctx, points)
    caster_hp = participant(ctx.userdata.combat_state, ctx.userdata.player_id).hp_current
    await declare_spell(ctx, spell_id, "cold", anchors)
    cast = await resolve_cast(ctx)
    results = cast["damage_results"]
    assert {r["target_id"] for r in results} == covered
    assert len(results) == len(covered)
    saved = await load_combat(ctx.userdata.combat_state.combat_id)
    assert participant(saved, ctx.userdata.player_id).hp_current == caster_hp
    if spell_id == "arcane_meteor_swarm":
        assert "deferred" not in cast
    for name in points:
        damage = next((r["damage"] for r in results if r["target_id"] == name), 0)
        assert participant(saved, name).hp_current == 100 - damage
        assert bool(damage) == (name in covered)
    if spell_id == "arcane_elemental_burst":
        assert all(r["damage_type"] == "cold" for r in results)
    if spell_id in {"primal_ice_storm", "divine_flame_strike"}:
        assert all(r["damage"] == 14 for r in results)


@pytest.mark.parametrize("level,count", [(1, 3), (5, 4), (11, 5), (17, 6)])
async def test_assigned_darts_keep_multiplicity_and_scale(spell_fight, level, count):
    import db

    ctx = spell_fight
    spell = await prepare_spell(ctx, "arcane_magic_missile")
    pool = await db.get_pool()
    await pool.execute(
        "UPDATE players SET data=jsonb_set(data,'{level}',to_jsonb($2::int)) WHERE player_id=$1",
        ctx.userdata.player_id,
        level,
    )
    participant(ctx.userdata.combat_state, ctx.userdata.player_id).level = level
    await add_enemies(ctx, {"foe": (0, 0, 0), "other": (10, 0, 0)})
    await declare_spell(ctx, spell.id, targets=["foe", "other"] + ["foe"] * (count - 2))
    import resonance

    modifiers = resonance.get_state_modifiers
    rigged = patch("resonance.get_state_modifiers", side_effect=lambda s: {**modifiers(s), "damage_dice": 1})
    with rigged, patch("dice.roll", side_effect=[SimpleNamespace(total=i) for i in range(1, count + 1)]) as rolls:
        from check_resolution_save import roll_participant_save

        with patch("check_resolution_save.roll_participant_save", wraps=roll_participant_save) as saves:
            result = await _resolve_round(ctx)
    cast = next(p["cast"] for p in result["packets"] if p["actor_id"] == ctx.userdata.player_id)
    assert saves.call_count == 0 and rolls.call_count == count
    results = cast["damage_results"]
    assert [r["dart_indices"] for r in results] == [[0, *range(2, count)], [1]]
    saved = await load_combat(ctx.userdata.combat_state.combat_id)
    assert participant(saved, "foe").hp_current == 100 - (sum(range(1, count + 1)) - 2)
    assert participant(saved, "other").hp_current == 100 - 2
    assert rolls.call_args_list[0].args[0] == "2d4+1"
    assert all(c.args[0] == "1d4+1" for c in rolls.call_args_list[1:])


@pytest.mark.parametrize("explicit", [False, True])
async def test_chain_primary_range_cap_and_secondary_damage(spell_fight, explicit):
    ctx = spell_fight
    await prepare_spell(ctx, "arcane_chain_lightning")
    await add_enemies(
        ctx,
        {"foe": (0, 0, 0), "a": (20, 0, 0), "b": (30, 0, 0), "c": (0, 30, 0), "d": (0, 0, 30), "out": (30.01, 0, 0)},
    )
    targets = ["foe", "d", "b"] if explicit else ["foe"]
    await declare_spell(ctx, "arcane_chain_lightning", targets=targets)
    from combat.test_spell_damage_lands import minimum_roll

    with patch("check_resolution.dice_roll", return_value=_d20(1)), patch("dice.roll", side_effect=minimum_roll):
        result = await _resolve_round(ctx)
    cast = next(p["cast"] for p in result["packets"] if p["actor_id"] == ctx.userdata.player_id)
    results = cast["damage_results"]
    assert [r["target_id"] for r in results] == (targets if explicit else ["foe", "a", "b", "c"])
    adjustment = cast["resonance_modifiers"]["damage_dice"]
    assert [r["damage"] for r in results] == [4 + adjustment] + [2 + adjustment] * (len(results) - 1)
    saved = await load_combat(ctx.userdata.combat_state.combat_id)
    for r in results:
        assert participant(saved, r["target_id"]).hp_current == 100 - r["damage"]
    assert participant(saved, "out").hp_current == 100


@pytest.mark.parametrize(
    "spell_id,targets",
    [
        ("arcane_magic_missile", ["foe", "other"]),
        ("arcane_magic_missile", ["foe"] * 5),
        ("arcane_magic_missile", ["foe", "missing", "foe", "foe"]),
        ("arcane_chain_lightning", ["foe", "out"]),
        ("arcane_chain_lightning", ["foe", "other", "out", "a", "b"]),
        ("arcane_meteor_swarm", ["foe", "other", "out", "a", "b"]),
        ("arcane_lightning_bolt", ["same"]),
    ],
)
async def test_invalid_assignments_refuse_before_writes(spell_fight, spell_id, targets):
    from combat.test_spell_damage_lands import saved_player
    from livekit.agents.llm import ToolError

    ctx = spell_fight
    await prepare_spell(ctx, spell_id)
    await add_enemies(
        ctx,
        {
            "foe": (0, 0, 0),
            "other": (10, 0, 0),
            "out": (31, 0, 0),
            "a": (1, 0, 0),
            "b": (2, 0, 0),
            "same": (-100, 0, 0),
        },
    )
    state = ctx.userdata.combat_state.to_dict()
    player = await saved_player(ctx.userdata.player_id)
    with pytest.raises(ToolError):
        await declare_spell(ctx, spell_id, targets=targets)
    assert ctx.userdata.combat_state.to_dict() == state
    assert await saved_player(ctx.userdata.player_id) == player


@pytest.fixture
async def area_party(spell_fight, dev_db_pool):
    from acceptance.seeds import seed_player

    from party_state import PartyState

    ctx = spell_fight
    state = ctx.userdata.combat_state
    extra = [ctx.userdata.player_id + suffix for suffix in ("_ally", "_beside")]
    for name in extra:
        await seed_player(dev_db_pool, player_id=name)
        actor = _enemy(name, 28)
        actor.type = "player"
        state.participants.append(actor)
        state.initiative_order.append(name)
        ctx.userdata.party.members.extend(PartyState.solo(name).members)
    participant(state, ctx.userdata.player_id).hp_current = 28
    place_actors(state)
    try:
        yield ctx, extra
    finally:
        for name in extra:
            await dev_db_pool.execute("DELETE FROM players WHERE player_id=$1", name)


async def test_friendly_fire_saves_and_player_hp_persist(area_party):
    from combat.test_spell_damage_lands import saved_player

    import check_resolution_save

    ctx, (ally, beside) = area_party
    await prepare_spell(ctx, "arcane_fireball")
    state = ctx.userdata.combat_state
    state.participants.append(_enemy("second", 100))
    state.initiative_order.append("second")
    place_actors(state)
    points = {ctx.userdata.player_id: (0, 0), "foe": (40, 0), "second": (60, 0), ally: (40, 10), beside: (60.01, 0)}
    for name, (x, y) in points.items():
        state.spatial["positions"][name] = {"x": x, "y": y, "z": 0}
    original = check_resolution_save.roll_participant_save
    observed = []

    def save(target, *args, **kwargs):
        observed.append(target.id)
        with patch("check_resolution.dice_roll", return_value=_d20(20 if target.id == ally else 1)):
            return original(target, *args, **kwargs)

    await declare_spell(ctx, "arcane_fireball")
    with (
        patch("check_resolution_save.roll_participant_save", side_effect=save),
        patch("dice.roll", return_value=SimpleNamespace(total=7)),
    ):
        result = await _resolve_round(ctx)
    cast = next(p["cast"] for p in result["packets"] if p["actor_id"] == ctx.userdata.player_id)
    assert observed == ["foe", ally, "second"]
    assert [r["damage"] for r in cast["damage_results"]] == [7, 3, 7]
    saved = await load_combat(state.combat_id)
    assert participant(saved, ally).hp_current == (await saved_player(ally))["hp"]["current"] == 25
    assert participant(saved, beside).hp_current == 28
    assert participant(saved, "second").hp_current == 93
    assert (await saved_player(ctx.userdata.player_id))["focus"]["current"] == 100 - 5


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
            DefendDecl(kind="defend", actor_id=ctx.userdata.player_id),
            AttackDecl(
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


@pytest.mark.parametrize("center_on_ally", [False, True])
async def test_radius_can_center_on_ally_and_cover_caster(area_party, center_on_ally):
    ctx, (ally, beside) = area_party
    await prepare_spell(ctx, "arcane_fireball")
    state = ctx.userdata.combat_state
    for name, x in ((ctx.userdata.player_id, 0), (ally, 10), ("foe", 20), (beside, 31)):
        state.spatial["positions"][name] = {"x": x, "y": 0, "z": 0}
    await declare_spell(ctx, "arcane_fireball", targets=[ally if center_on_ally else "foe"])
    cast = await resolve_cast(ctx)
    assert {r["target_id"] for r in cast["damage_results"]} == {ctx.userdata.player_id, ally, "foe"} | (
        {beside} if not center_on_ally else set()
    )
    saved = await load_combat(state.combat_id)
    assert participant(saved, ctx.userdata.player_id).hp_current == 21
    assert participant(saved, ally).hp_current == 21


async def test_sacred_word_selects_only_nearby_undead_and_hollow(spell_fight):
    ctx = spell_fight
    await prepare_spell(ctx, "divine_sacred_word")
    await add_enemies(
        ctx, {"foe": (-90, 0, 0), "hollow": (-100, 0, 10), "living": (-99, 0, 0), "outside": (-89.99, 0, 0)}
    )
    state = ctx.userdata.combat_state
    participant(state, "foe").category = participant(state, "outside").category = "undead"
    from _hollow_resonance_fixtures import hollow

    participant(state, "hollow").hollow = hollow("hollow").hollow
    await declare_spell(ctx, "divine_sacred_word", targets=[])
    cast = await resolve_cast(ctx)
    assert {r["target_id"] for r in cast["damage_results"]} == {"foe", "hollow"}
    saved = await load_combat(state.combat_id)
    for name in ("foe", "hollow"):
        assert participant(saved, name).hp_current == 93
    assert participant(saved, "living").hp_current == participant(saved, "outside").hp_current == 100


@pytest.mark.parametrize("spell_id", ["arcane_fireball", "arcane_magic_missile", "arcane_chain_lightning"])
async def test_absorption_keeps_other_deliveries_without_refill(spell_fight, spell_id):
    from combat.test_spell_damage_lands import saved_player
    from creature_combat_helpers import catalog
    from creature_combat_helpers import participant as enemy_participant

    from creature_combat import translate_creature

    ctx = spell_fight
    await prepare_spell(ctx, spell_id)
    row = next(r for r in catalog() if r["id"] == "hollow_veilrender")
    boss = enemy_participant(translate_creature(row, encounter_id="absorb", enemy_id="foe", role="standard"))
    boss.hp_current = 70
    ctx.userdata.combat_state.participants[1] = boss
    await add_enemies(ctx, {"foe": (0, 0, 0), "other": (10, 0, 0)})
    targets = ["foe", "other", "foe", "other"] if spell_id == "arcane_magic_missile" else ["foe"]
    await declare_spell(ctx, spell_id, targets=targets)
    cast = await resolve_cast(ctx)
    assert [r["target_id"] for r in cast["damage_results"]] == ["other"]
    import spells

    assert cast["absorbed"][0]["healed"] == 3 * spells.get_spell(spell_id).focus_cost
    assert len(cast["absorbed"]) == 1
    if spell_id == "arcane_magic_missile":
        assert cast["damage_results"][0]["dart_indices"] == [1, 3]
        assert cast["damage_results"][0]["damage"] == 14
    saved = await load_combat(ctx.userdata.combat_state.combat_id)
    assert participant(saved, "other").hp_current == 100 - cast["damage_results"][0]["damage"]
    import spells

    assert (await saved_player(ctx.userdata.player_id))["focus"]["current"] == 100 - spells.get_spell(
        spell_id
    ).focus_cost


async def test_choir_redirect_does_not_recenter_the_blast(spell_fight):
    from creature_combat_helpers import catalog
    from creature_combat_helpers import participant as enemy_participant

    import check_resolution_save
    from creature_combat import translate_creature

    ctx = spell_fight
    await prepare_spell(ctx, "arcane_fireball")
    row = next(r for r in catalog() if r["id"] == "hollow_choir")
    ctx.userdata.combat_state.participants[1] = enemy_participant(
        translate_creature(row, encounter_id="shield", enemy_id="foe", role="standard")
    )
    await add_enemies(ctx, {"foe": (0, 0, 0), "other": (10, 0, 0), "outside": (-90, 0, 0)})
    await declare_spell(ctx, "arcane_fireball")
    original = check_resolution_save.roll_participant_save
    with (
        patch("check_resolution.dice_roll", return_value=_d20(1)),
        patch("check_resolution_save.roll_participant_save", wraps=original) as saves,
        patch("dice.roll", return_value=SimpleNamespace(total=7)),
    ):
        result = await _resolve_round(ctx)
    cast = next(p["cast"] for p in result["packets"] if p["actor_id"] == ctx.userdata.player_id)
    assert [r["target_id"] for r in cast["damage_results"]] == [ctx.userdata.player_id, "other"]
    assert sum(call.args[3] == "Harmonic Shield" for call in saves.call_args_list) == 1
    saved = await load_combat(ctx.userdata.combat_state.combat_id)
    assert participant(saved, "outside").hp_current == 100
    assert participant(saved, "other").hp_current == 93


async def test_mixed_component_area_preserves_death_affinities_and_concentration(area_party):
    from _hollow_resonance_fixtures import hollow
    from combat.test_spell_damage_lands import saved_player

    import db_mutations_concentration

    ctx, (ally, beside) = area_party
    await prepare_spell(ctx, "divine_flame_strike")
    state = ctx.userdata.combat_state
    await add_enemies(ctx, {"foe": (0, 0, 0), ally: (10, 0, 0), beside: (20, 0, 0), "survivor": (40, 0, 0)})
    victim = hollow("foe")
    victim.hp_current = 1
    state.participants[1] = victim
    participant(state, ally).damage_affinities = {"resistant": ["fire"], "vulnerable": ["radiant"]}
    ctx.userdata.member_state(ally).concentration.spell_id = "divine_bless"
    await db_mutations_concentration.update_player_concentration(ally, "divine_bless")
    participant(state, ally).conditions = [{"type": "blessed", "source": "divine_bless"}]
    await declare_spell(ctx, "divine_flame_strike")
    cast = await resolve_cast(ctx)
    results = cast["damage_results"]
    assert [r["target_id"] for r in results] == ["foe", ally]
    assert results[1]["damage"] == 17 and results[1]["concentration_broken"] == "divine_bless"
    saved = await load_combat(state.combat_id)
    assert participant(saved, "foe").is_dead and participant(saved, "foe").hollow_death_resolved
    assert participant(saved, ally).hp_current == (await saved_player(ally))["hp"]["current"] == 11
    assert ctx.userdata.member_state(ally).concentration.spell_id is None
    assert not participant(saved, ally).conditions


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
