"""Capstone: M4.5 dramatic-dice signal end-to-end against a real Postgres testcontainer.

Stories 001-006/008 shipped the pieces: the pure evaluate_dramatic_context catalog (001),
dramatic+context on the result packets (002/003), combat + out-of-combat DICE_ROLL emission
(004/005), the client gate (006), and the resolver-file split (008). This capstone proves they
COMPOSE on ONE seeded testcontainer (auto-marked `acceptance` by tests/acceptance/conftest.py):
the REAL evaluator's verdict travels evaluator -> result packet -> DICE_ROLL event -> packet
summary for both combat and out-of-combat rolls, death saves are always dramatic, routine rolls
never are, and the scarcity bar holds across a representative multi-phase fight.

Determinism: every d20 (skill / save / attack) routes through check_resolution._roll_d20_check,
which reads the module-global check_resolution.dice_roll. Patching that one seam forces the d20
while the real resolvers and the real evaluate_dramatic_context run end to end (an honest chain,
not a hand-built verdict). Attack DAMAGE uses the separate check_resolution_attack.dice_roll
(left real); kill timing is controlled by setting a participant's hp_current directly. Each test
uses a distinct player_id / combat_id since the testcontainer DB is shared.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

from acceptance.seeds import seed_player
from sample_fixtures import make_context, make_mock_room

import combat_death_save
import combat_turn
import db
import db_mutations
import event_types as E
from session_data import CombatParticipant, CombatState

_PLAYER_WEAPON = {"name": "Longsword", "damage": "1d8", "damage_type": "slashing", "properties": []}
_ENEMY_ACTION = {"name": "Scimitar", "damage": "1d6", "damage_type": "slashing", "properties": ["light"]}


def _d20(face: int):
    """A check_resolution.dice_roll stand-in that forces every d20 to `face`.

    _roll_d20_check reads only `.total`; damage rolls go through the separate
    check_resolution_attack.dice_roll, which this does NOT touch.
    """
    return SimpleNamespace(total=face)


def _player(player_id: str, hp: int = 100) -> CombatParticipant:
    return CombatParticipant(
        id=player_id,
        name="Kael",
        type="player",
        initiative=15,  # acts before the enemies so its reveal lands first
        hp_current=hp,
        hp_max=hp,
        ac=14,
        action_pool=[_PLAYER_WEAPON],
    )


def _enemy(enemy_id: str, hp: int) -> CombatParticipant:
    return CombatParticipant(
        id=enemy_id,
        name=enemy_id.replace("_", " ").title(),
        type="enemy",
        initiative=12,
        hp_current=hp,
        hp_max=max(hp, 7),
        ac=10,  # low AC so a forced mid d20 reliably hits
        action_pool=[_ENEMY_ACTION],
        xp_value=50,
    )


def _build_state(combat_id: str, player_id: str, enemies: list[CombatParticipant], *, first_attack_resolved=False):
    """A declaration-beat CombatState with a player + N enemies, ready for declare/resolve."""
    participants = [_player(player_id), *enemies]
    return CombatState(
        combat_id=combat_id,
        participants=participants,
        initiative_order=[player_id, *[e.id for e in enemies]],
        round_number=1,
        current_turn_index=0,
        location_id="accord_guild_hall",
        beat="declaration",
        first_attack_resolved=first_attack_resolved,
    )


def _dice_events(room) -> list[dict]:
    out = []
    for call in room.local_participant.publish_data.call_args_list:
        payload = json.loads(call[0][0])
        if payload.get("type") == E.DICE_ROLL:
            out.append(payload)
    return out


def _player_attack_events(room) -> list[dict]:
    return [e for e in _dice_events(room) if e.get("roll_type") == "attack" and e.get("attacker") == "Kael"]


async def _start_combat(pool, player_id: str, combat_id: str, state: CombatState, ctx) -> None:
    """Seed the real player row + persist the hand-built combat SSOT, then wire the in-memory state."""
    await seed_player(pool, player_id=player_id, location_id="accord_guild_hall")
    await db_mutations.save_combat_state(combat_id, state.to_dict(), conn=pool)
    ctx.userdata.combat_state = state


async def _declare_attacks(ctx, player_id: str, target_id: str, enemy_ids: list[str]) -> None:
    decls = {player_id: {"type": "attack", "action": "Longsword", "target_id": target_id}}
    for eid in enemy_ids:
        decls[eid] = {"type": "attack", "action": "Scimitar", "target_id": player_id}
    await combat_turn._declare_phase_impl(ctx, decls)


# --- AC1 + AC4: combat DICE_ROLL dramatic chain (evaluator -> packet -> event -> summary) ---


async def test_combat_nat20_crit_is_dramatic_chain(reset_db_pool: str) -> None:
    """A natural-20 attack travels the real chain: the DICE_ROLL event AND the resolve packet
    summary both report dramatic=True with context 'natural_20'."""
    pool = await db.get_pool()
    player_id = "cap_m45_nat20"
    room = make_mock_room()
    ctx = make_context(player_id, room=room)
    state = _build_state("combat_cap_m45_nat20", player_id, [_enemy("goblin_a", hp=100)])
    try:
        await _start_combat(pool, player_id, state.combat_id, state, ctx)
        await _declare_attacks(ctx, player_id, "goblin_a", ["goblin_a"])
        with patch("check_resolution.dice_roll", return_value=_d20(20)):
            result = await combat_turn._resolve_phase_impl(ctx)

        # Event side of the chain.
        attacks = _player_attack_events(room)
        assert attacks, "the player's attack emitted a DICE_ROLL"
        assert attacks[0]["dramatic"] is True
        assert attacks[0]["context"] == "natural_20"
        # Summary side of the chain (DM-facing packet from resolve_phase).
        assert isinstance(result, str), "a non-lethal crit (enemy at 100 HP) loops the phase"
        summaries = json.loads(result)["packets"]
        dramatic_summaries = [p for p in summaries if p.get("dramatic") is True]
        assert dramatic_summaries, "the resolve packet summary carries the dramatic flag"
    finally:
        await db_mutations.delete_combat_state(state.combat_id, conn=pool)


async def test_combat_killing_blow_is_dramatic(reset_db_pool: str) -> None:
    """A non-crit hit that drops a (non-last) enemy reports dramatic=True context 'killing_blow' —
    the intrinsic killing-blow verdict outranks the first_attack/last_enemy promotions."""
    pool = await db.get_pool()
    player_id = "cap_m45_kill"
    room = make_mock_room()
    ctx = make_context(player_id, room=room)
    # Two enemies so the kill is NOT also the last enemy; target at 1 HP so a mid hit kills.
    state = _build_state("combat_cap_m45_kill", player_id, [_enemy("goblin_a", hp=1), _enemy("goblin_b", hp=100)])
    try:
        await _start_combat(pool, player_id, state.combat_id, state, ctx)
        await _declare_attacks(ctx, player_id, "goblin_a", ["goblin_a", "goblin_b"])
        with patch("check_resolution.dice_roll", return_value=_d20(11)):
            await combat_turn._resolve_phase_impl(ctx)

        attacks = _player_attack_events(room)
        assert attacks, "the player's attack emitted a DICE_ROLL"
        assert attacks[0]["dramatic"] is True
        assert attacks[0]["context"] == "killing_blow"
    finally:
        await db_mutations.delete_combat_state(state.combat_id, conn=pool)


async def test_combat_routine_hit_is_not_dramatic(reset_db_pool: str) -> None:
    """A non-crit, non-killing hit that is neither the first attack nor against the last enemy is
    NOT dramatic — the bulk of combat rolls earn no dice."""
    pool = await db.get_pool()
    player_id = "cap_m45_routine"
    room = make_mock_room()
    ctx = make_context(player_id, room=room)
    # first_attack already resolved + two healthy enemies => no first_attack/last_enemy promotion.
    state = _build_state(
        "combat_cap_m45_routine",
        player_id,
        [_enemy("goblin_a", hp=100), _enemy("goblin_b", hp=100)],
        first_attack_resolved=True,
    )
    try:
        await _start_combat(pool, player_id, state.combat_id, state, ctx)
        await _declare_attacks(ctx, player_id, "goblin_a", ["goblin_a", "goblin_b"])
        with patch("check_resolution.dice_roll", return_value=_d20(11)):
            await combat_turn._resolve_phase_impl(ctx)

        attacks = _player_attack_events(room)
        assert attacks, "the player's attack emitted a DICE_ROLL"
        assert attacks[0]["dramatic"] is False
        assert attacks[0]["context"] == ""
    finally:
        await db_mutations.delete_combat_state(state.combat_id, conn=pool)


# --- AC1: death saves are ALWAYS dramatic ---


async def test_death_save_is_always_dramatic(reset_db_pool: str) -> None:
    """Every death save reports dramatic=True context 'death_save', on the DICE_ROLL event and the
    tool response, regardless of the rolled value."""
    pool = await db.get_pool()
    player_id = "cap_m45_deathsave"
    room = make_mock_room()
    ctx = make_context(player_id, room=room)
    fallen = _player(player_id, hp=0)
    fallen.hp_current = 0
    fallen.is_fallen = True
    state = _build_state("combat_cap_m45_deathsave", player_id, [_enemy("goblin_a", hp=20)])
    state.participants[0] = fallen
    try:
        await _start_combat(pool, player_id, state.combat_id, state, ctx)
        response = json.loads(await combat_death_save._request_death_save_impl(ctx))

        assert response["dramatic"] is True
        assert response["context"] == "death_save"
        save_events = [e for e in _dice_events(room) if e.get("roll_type") == "death_save"]
        assert save_events, "the death save emitted a DICE_ROLL"
        assert save_events[0]["dramatic"] is True
        assert save_events[0]["context"] == "death_save"
    finally:
        await db_mutations.delete_combat_state(state.combat_id, conn=pool)


# --- AC2: out-of-combat skill check (nat-20 dramatic, routine not) ---


async def test_out_of_combat_skill_check_dramatic(reset_db_pool: str) -> None:
    """An out-of-combat nat-20 skill check emits a DICE_ROLL with dramatic=True context
    'natural_20'; a routine roll emits dramatic=False. Only crits fire out of combat."""
    import check_tools

    pool = await db.get_pool()
    player_id = "cap_m45_skill"
    await seed_player(pool, player_id=player_id, location_id="accord_guild_hall")

    room = make_mock_room()
    ctx = make_context(player_id, room=room)
    with patch("check_resolution.dice_roll", return_value=_d20(20)):
        await check_tools._check_skill_impl(ctx, "perception", "moderate", "scanning the hall")
    crit = next(e for e in _dice_events(room) if e.get("roll_type") == "skill_check")
    assert crit["dramatic"] is True
    assert crit["context"] == "natural_20"

    room2 = make_mock_room()
    ctx2 = make_context(player_id, room=room2)
    with patch("check_resolution.dice_roll", return_value=_d20(10)):
        await check_tools._check_skill_impl(ctx2, "perception", "moderate", "scanning the hall")
    routine = next(e for e in _dice_events(room2) if e.get("roll_type") == "skill_check")
    assert routine["dramatic"] is False
    assert routine["context"] == ""


# --- AC3: scarcity bar holds across a representative multi-phase fight ---


async def test_scarcity_bar_holds_over_representative_fight(reset_db_pool: str) -> None:
    """Across a representative 5-phase fight (two enemies, all d20s a forced mid 11), only a small
    number of attack rolls earn the dice: the first attack of the encounter, and the single
    killing blow forced on the final phase. The routine middle phases stay non-dramatic, so the
    dramatic-reveal count stays within the scarcity bar (0-2, death saves excluded)."""
    pool = await db.get_pool()
    player_id = "cap_m45_scarcity"
    room = make_mock_room()
    ctx = make_context(player_id, room=room)
    # goblin_a is whittled across the fight; goblin_b stays alive so goblin_a is never "last enemy".
    state = _build_state("combat_cap_m45_scarcity", player_id, [_enemy("goblin_a", hp=100), _enemy("goblin_b", hp=100)])
    try:
        await _start_combat(pool, player_id, state.combat_id, state, ctx)
        with patch("check_resolution.dice_roll", return_value=_d20(11)):
            for phase in range(5):
                cs = ctx.userdata.combat_state
                if cs is None:  # defensive: a forced kill could end combat early
                    break
                # Force the killing blow onto the final phase by dropping goblin_a to 1 HP.
                if phase == 4:
                    next(p for p in cs.participants if p.id == "goblin_a").hp_current = 1
                await _declare_attacks(ctx, player_id, "goblin_a", ["goblin_a", "goblin_b"])
                await combat_turn._resolve_phase_impl(ctx)

        player_attacks = _player_attack_events(room)
        assert len(player_attacks) >= 3, "the fight ran several phases of player attacks"
        dramatic_reveals = [e for e in player_attacks if e["dramatic"] is True]
        # Scarcity bar: at most two reveals (first_attack + the final killing_blow).
        assert 0 <= len(dramatic_reveals) <= 2, f"too many dramatic reveals: {[e['context'] for e in dramatic_reveals]}"
        # And the routine middle phases genuinely earned no dice.
        assert any(e["dramatic"] is False for e in player_attacks), "routine attacks stay non-dramatic"
    finally:
        await db_mutations.delete_combat_state(state.combat_id, conn=pool)
