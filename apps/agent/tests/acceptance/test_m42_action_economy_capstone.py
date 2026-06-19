"""Capstone: M4.2 Action Economy — full lifecycle end-to-end against a real Postgres testcontainer.

Milestone 2 shipped its pieces across stories 001-005/007: the typed 6-category declaration model
(002), declaration enhancers + 1d12 heavy weapons (003/004), transaction-integrity seams (005), and
in-combat ABILITY resolution through the phase loop (007). This capstone proves they COMPOSE against
ONE seeded testcontainer (auto-marked `acceptance` by tests/acceptance/conftest.py), exercising the
seams the mocked units can't: combat_init persistence, the declare/resolve loop driving all six
declaration categories, enhancer expansion persisted to combat_instances, the real cast path
deducting Focus in combat, and DB/in-memory agreement across a multi-phase fight.

Test 1 drives the fight with a fixed-damage resolver (the DI seam the unit TestPhaseLoopE2E uses) so
the multi-phase choreography is deterministic; the ABILITY phase runs the REAL cast (cast_resolver
defaults to spell_casting), so Focus deduction is exercised for real. Test 2 pins the 1d12 damage
CONTRACT (AC3) deterministically with a seeded RNG against the real resolve_attack — the exhaustive
formula coverage lives in tests/combat/test_weapon_damage.py; this is the capstone's AC3 anchor.

AC3 note: the story's original AC3 wording said "+ proficiency"; the shipped contract (story-003
decision, locked SMM constraint) adds the attribute modifier ONCE and NO proficiency to damage
(proficiency is the to-hit roll only). The story's AC3 was reworded to match; this test asserts the
shipped behavior.

Each test uses a distinct player_id since the testcontainer DB is shared.
"""

from __future__ import annotations

import json
import random

from acceptance.seeds import seed_player_with_pools
from combat._helpers import _damage_resolver
from sample_fixtures import make_context

import combat_init
import combat_turn
import db
import db_mutations
from check_resolution_attack import attack_modifier, resolve_attack, weapon_attribute_modifier
from dice import roll as dice_roll

# A 1d12 Heavy weapon (STR-governed: no finesse/ranged/override). combat_init synthesizes the
# player's action_pool from equipment entries carrying `damage`, so this becomes the "Greataxe"
# attack the player declares in combat.
_GREATAXE = {"name": "Greataxe", "damage": "1d12", "damage_type": "slashing", "properties": ["heavy", "two-handed"]}
_ABILITY_SPELL = "arcane_shield_spell"  # a real catalog spell: focus_cost 1, generates Resonance


async def _seed_capstone_player(pool, player_id: str) -> None:
    """Seed a player wielding the 1d12 greataxe with the extra_attack + cunning_action enhancer flags
    (combat_init reads players.data.flags), a Focus pool for the in-combat ability, and high HP so the
    player survives the multi-phase fight that cycles through every declaration category."""
    await seed_player_with_pools(pool, player_id=player_id, focus_current=10)
    await pool.execute(
        "UPDATE players SET data = jsonb_set("
        "  jsonb_set("
        "    jsonb_set(data, '{equipment}', $2::jsonb),"
        "  '{flags}', $3::jsonb),"
        "'{hp}', $4::jsonb) WHERE player_id = $1",
        player_id,
        json.dumps({"main_hand": _GREATAXE}),
        json.dumps({"extra_attack": True, "cunning_action": True}),
        json.dumps({"current": 100, "max": 100}),
    )


def _player_packet(raw: str, player_id: str) -> dict:
    """Pull the player's resolution summary out of a (combat-continues) resolve_phase JSON response."""
    packets = json.loads(raw)["packets"]
    return next(p for p in packets if p["actor_id"] == player_id)


async def test_full_action_economy_lifecycle_on_real_pg(reset_db_pool: str) -> None:
    """AC1/AC2/AC4 + tx-integrity: a real multi-phase fight where the player cycles through all six
    declaration categories, an enhancer expands an Attack and persists, the real cast path deducts
    Focus in combat, and the DB stays consistent with in-memory — driven to victory and cleanup."""
    pool = await db.get_pool()
    player_id = "cap_m42_lifecycle"
    await _seed_capstone_player(pool, player_id)

    ctx = make_context(player_id)
    raw = await combat_init._start_combat_impl(ctx, "hollow_wisp", "A hollow wisp coalesces from the murk.")
    assert isinstance(raw, tuple), "a hostile encounter hands off (combat agent, json)"

    cs = ctx.userdata.combat_state
    assert cs is not None and cs.beat == "declaration"
    combat_id = cs.combat_id
    enemy = next(p for p in cs.participants if p.type == "enemy")
    enemy_attack = {"type": "attack", "action": enemy.action_pool[0]["name"], "target_id": player_id}

    # The greataxe is wielded: combat_init synthesized it into the player's action_pool, and the
    # extra_attack flag became a CombatParticipant enhancer (persisted in combat_instances.data).
    player_part = cs.get_participant(player_id)
    assert player_part is not None
    assert any(a["name"] == "Greataxe" for a in player_part.action_pool)
    assert "extra_attack" in player_part.enhancers

    async def _run_phase(player_decl: dict) -> str:
        await combat_turn._declare_phase_impl(ctx, {player_id: player_decl, enemy.id: enemy_attack})
        out = await combat_turn._resolve_phase_impl(ctx, resolver=_damage_resolver(2))
        assert isinstance(out, str), "the enemy survives these phases, so combat continues (JSON, not a handoff)"
        return out

    try:
        # --- AC1: each of the six declaration categories resolves with the correct typed outcome ---
        # DEFEND — mechanical: no attack, +2 AC for the phase.
        defend_pkt = _player_packet(await _run_phase({"type": "defend"}), player_id)
        assert defend_pkt["resolved"] is True and defend_pkt["declaration_type"] == "defend"
        assert defend_pkt["ac_bonus"] == 2

        # tx-integrity: after a resolved phase the DB SSOT equals in-memory (combat_instances.data
        # round-trips to the live combat_state; player HP in players.data matches the participant).
        live = ctx.userdata.combat_state
        assert live is not None
        loaded = await db_mutations.load_combat_state(combat_id, conn=pool)
        assert loaded is not None
        assert loaded.to_dict() == live.to_dict()
        live_player = live.get_participant(player_id)
        assert live_player is not None
        hp_row = await pool.fetchrow(
            "SELECT (data->'hp'->>'current')::int AS hp FROM players WHERE player_id = $1", player_id
        )
        assert hp_row["hp"] == live_player.hp_current

        # INTERACT / MANEUVER / RETREAT — modelled + initiative-ordered, narrated-only today (wasted
        # but typed: resolved=False carries the declaration_type so the DM re-prompts, never crashes).
        for decl, dtype in (
            ({"type": "interact", "action": "torch"}, "interact"),
            ({"type": "maneuver", "target_id": enemy.id}, "maneuver"),
            ({"type": "retreat"}, "retreat"),
        ):
            pkt = _player_packet(await _run_phase(decl), player_id)
            assert pkt["resolved"] is False and pkt["declaration_type"] == dtype

        # ABILITY — mechanical (story-007): the real cast resolves in the phase tx, deducting Focus.
        ability_pkt = _player_packet(await _run_phase({"type": "ability", "action": _ABILITY_SPELL}), player_id)
        assert ability_pkt["resolved"] is True and ability_pkt["declaration_type"] == "ability"
        assert ability_pkt["cast"]["resonance_generated"] > 0  # the cast generated Resonance
        focus_row = await pool.fetchrow(
            "SELECT (data->'focus'->>'current')::int AS f FROM players WHERE player_id = $1", player_id
        )
        assert focus_row["f"] == 9, "the in-combat cast deducted the spell's Focus cost (10 -> 9)"

        # ATTACK — mechanical, and AC2: the extra_attack enhancer EXPANDS one declaration into two
        # swings (never a second declaration), with a narrated Cunning Action rider. The wisp (22 HP)
        # survives two 2-damage swings, so the phase loops and the summary is observable.
        attack_pkt = _player_packet(
            await _run_phase({"type": "attack", "action": "Greataxe", "target_id": enemy.id, "rider": "disengage"}),
            player_id,
        )
        assert attack_pkt["resolved"] is True
        assert len(attack_pkt["attacks"]) == 2, "extra_attack expands the Attack to two swings"
        assert attack_pkt["damage"] == 4, "two 2-damage swings aggregate"
        assert any("cunning_action" in r for r in attack_pkt.get("riders", [])), "Cunning Action rider narrated"

        # AC2 persistence: the enhancers round-trip through the combat_instances JSONB SSOT.
        reloaded = await db_mutations.load_combat_state(combat_id, conn=pool)
        assert reloaded is not None
        reloaded_player = reloaded.get_participant(player_id)
        assert reloaded_player is not None
        assert "extra_attack" in reloaded_player.enhancers

        # --- AC4: drive the fight to victory; end_combat clears state + deletes the SSOT row in-tx. ---
        result: str | tuple = ""
        for _ in range(12):  # safety bound; wisp ~18 HP at 8/phase (4 x 2 swings) -> a few rounds
            await combat_turn._declare_phase_impl(
                ctx,
                {player_id: {"type": "attack", "action": "Greataxe", "target_id": enemy.id}, enemy.id: enemy_attack},
            )
            result = await combat_turn._resolve_phase_impl(ctx, resolver=_damage_resolver(4))
            if isinstance(result, tuple):
                break
        assert isinstance(result, tuple), "the winning wrap fires end_combat and hands back"
        payload = json.loads(result[1])
        assert payload["outcome"] == "victory"
        assert ctx.userdata.combat_state is None
        assert await pool.fetchrow("SELECT 1 FROM combat_instances WHERE combat_id = $1", combat_id) is None
    finally:
        await db_mutations.delete_combat_state(combat_id, conn=pool)


def _expected_die_total(seed: int, notation: str, *, crit: bool) -> int:
    """Replay the RNG resolve_attack consumes (d20 first, then the damage die, twice on a crit) so the
    exact damage dice are predictable — the technique from tests/combat/test_weapon_damage.py.

    Duplicated (not imported) on purpose: test_weapon_damage lives in the fast `tests/combat/` lane,
    which isn't on the acceptance run's import path — the lanes are isolated by rootdir."""
    rng = random.Random(seed)
    rng.randint(1, 20)  # the attack d20
    total = dice_roll(notation, rng=rng).total
    if crit:
        total += dice_roll(notation, rng=rng).total
    return total


def test_heavy_weapon_damage_contract() -> None:
    """AC3 (capstone anchor): a wielded 1d12 heavy weapon deals weapon die + attribute modifier
    (added ONCE, even on a crit; a crit doubles the DICE), and NO proficiency reaches damage —
    proficiency is the to-hit roll only. Exhaustive formula coverage is in test_weapon_damage.py;
    this pins the contract the capstone fight relies on, deterministically via a seeded RNG."""
    attacker = {"level": 5, "attributes": {"strength": 16}}  # STR 16 -> +3 mod
    str_mod = weapon_attribute_modifier(attacker, _GREATAXE)
    assert str_mod == 3
    # Proficiency is in the to-hit modifier but must NOT be in damage. Derive it from the engine
    # (the bonus curve is the engine's, not assumed) and assert it is a positive term — so its
    # absence from the damage assertions below is observable, not vacuous.
    prof = attack_modifier(attacker, _GREATAXE) - str_mod
    assert prof >= 1, "proficiency must be a positive to-hit term for the no-proficiency-in-damage check to bite"

    # Normal hit: damage = one 1d12 + STR mod, no proficiency. (target_ac 2 -> any non-1 d20 hits.)
    for seed in range(2000):
        if not 1 < random.Random(seed).randint(1, 20) < 20:  # skip nat-1 (miss) and nat-20 (crit)
            continue
        result = resolve_attack(attacker, _GREATAXE, 2, 100, rng=random.Random(seed))
        if not result.hit or result.critical_success:
            continue
        assert result.damage == _expected_die_total(seed, "1d12", crit=False) + str_mod
        assert result.attack_total == result.roll + str_mod + prof  # to-hit DID include proficiency
        break
    else:
        raise AssertionError("no normal-hit seed found")

    # Critical hit: damage = two 1d12 + STR mod ONCE (dice doubled, modifier not).
    for seed in range(2000):
        if random.Random(seed).randint(1, 20) != 20:
            continue
        result = resolve_attack(attacker, _GREATAXE, 2, 100, rng=random.Random(seed))
        assert result.critical_success is True
        assert result.damage == _expected_die_total(seed, "1d12", crit=True) + str_mod
        break
    else:
        raise AssertionError("no nat-20 seed found")
