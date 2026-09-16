"""Shared helpers for the combat-tools test suite."""

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from _combat_end_fixtures import combat_end_mutations
from sample_fixtures import make_context, make_db_mod

import combat_turn
import reaction_spend
from ability_tools import _request_ability_activation_impl
from check_resolution_attack import AttackResult
from session_data import CombatParticipant, CombatState


def _declarations():
    """The all-attack declaration payload matching _make_combat_state()'s two participants."""
    return {
        "player_1": {"type": "attack", "action": "Longsword", "target_id": "goblin_scout_1"},
        "goblin_scout_1": {"type": "attack", "action": "Scimitar", "target_id": "player_1"},
    }


def _fake_db_mod():
    """A db-module stand-in for resolve_phase unit tests: ``.transaction()`` is a no-op async
    context manager yielding a mock conn, so the per-phase transaction wrapper (story-010) runs
    without a real DB (the mocked mutations accept + ignore the conn kwarg). Delegates to the
    canonical sample_fixtures.make_db_mod so the transaction plumbing lives in one place."""
    db_mod, _conn = make_db_mod()
    return db_mod


def _make_combat_state(player_hp=25, player_fallen=False, enemy_hp=7, enemy_fallen=False):
    """Create a CombatState for testing."""
    return CombatState(
        combat_id="combat_test123",
        participants=[
            CombatParticipant(
                id="player_1",
                name="Kael",
                type="player",
                initiative=15,
                hp_current=player_hp,
                hp_max=25,
                ac=14,
                action_pool=[
                    {
                        "name": "Longsword",
                        "damage": "1d8",
                        "damage_type": "slashing",
                        "properties": [],
                    }
                ],
                is_fallen=player_fallen,
            ),
            CombatParticipant(
                id="goblin_scout_1",
                name="Goblin Scout",
                type="enemy",
                initiative=12,
                hp_current=enemy_hp,
                hp_max=7,
                ac=13,
                action_pool=[
                    {
                        "name": "Scimitar",
                        "damage": "1d6",
                        "damage_type": "slashing",
                        "properties": ["light"],
                    },
                ],
                xp_value=50,
                is_fallen=enemy_fallen,
            ),
        ],
        initiative_order=["player_1", "goblin_scout_1"],
        round_number=1,
        current_turn_index=0,
        location_id="accord_guild_hall",
    )


def _resolution_state(
    player_hp=25,
    enemy_hp=7,
    *,
    combat_id="combat_test123",
    player_id="player_1",
    enemy_id="goblin_scout_1",
    player_conditions=None,
    player_attributes=None,
    player_level=1,
):
    """A CombatState parked at the RESOLUTION beat with player+enemy declarations
    pending. The player carries a synthesized weapon action_pool (story-003 step 6
    builds this at init; constructed inline here).

    Keyword-only overrides let dev-DB tests pass unique ids (required for the
    shared :55432 fast lane under xdist) and pre-apply conditions / attributes
    without forking the fixture."""
    return CombatState(
        combat_id=combat_id,
        participants=[
            CombatParticipant(
                id=player_id,
                name="Kael",
                type="player",
                initiative=15,
                hp_current=player_hp,
                hp_max=25,
                ac=14,
                attributes=player_attributes if player_attributes is not None else {},
                level=player_level,
                action_pool=[{"name": "Longsword", "damage": "1d8", "damage_type": "slashing", "properties": []}],
                conditions=player_conditions or [],
            ),
            CombatParticipant(
                id=enemy_id,
                name="Goblin Scout",
                type="enemy",
                initiative=12,
                hp_current=enemy_hp,
                hp_max=7,
                ac=13,
                action_pool=[{"name": "Scimitar", "damage": "1d6", "damage_type": "slashing", "properties": ["light"]}],
                xp_value=50,
            ),
        ],
        initiative_order=[player_id, enemy_id],
        round_number=1,
        current_turn_index=0,
        location_id="accord_guild_hall",
        beat="resolution",
        pending_declarations={
            player_id: {"type": "attack", "action": "Longsword", "target_id": enemy_id},
            enemy_id: {"type": "attack", "action": "Scimitar", "target_id": player_id},
        },
    )


def _damage_resolver(damage):
    """A resolve_attack mock that always hits for a fixed damage, computing the target's
    remaining HP from the call args so multiple packets resolve coherently."""

    def _resolve(attacker_data, action, target_ac, target_hp, attack_mod=0, damage_mult=1.0, target_conditions=()):
        # attack_mod/damage_mult are the M4.7 role-overlay params (story-001). This stub always
        # hits; it scales the fixed damage by damage_mult so role-modified packets stay coherent.
        scaled = max(0, int(damage * damage_mult))
        remaining = max(0, target_hp - scaled)
        return AttackResult(
            hit=True,
            roll=15,
            attack_modifier=3,
            attack_total=18,
            target_ac=target_ac,
            damage=scaled,
            damage_type="slashing",
            critical_success=False,
            critical_failure=False,
            target_hp_remaining=remaining,
            target_killed=remaining == 0,
            narrative_hint="A clean strike.",
        )

    r = MagicMock()
    r.resolve_attack = MagicMock(side_effect=_resolve)
    return r


def _resolve_deps(damage=3):
    """DI bundle for resolve_phase: a deterministic damage resolver plus the mutations/queries/
    concentration mocks the packet path touches, and a no-op db_mod so the per-phase transaction
    wrapper runs without a real connection."""
    queries = MagicMock()
    queries.get_player_inventory = AsyncMock(return_value=[])  # no equipped items
    # The ability Focus pre-validation fetches the player for_update; a sufficient-Focus default so
    # the happy-path ability tests pass the gate (the all-attacks tests never fetch — no ability).
    queries.get_player = AsyncMock(return_value={"player_id": "player_1", "focus": {"current": 10, "max": 10}})
    break_mod = MagicMock()
    break_mod.break_concentration_on_damage = AsyncMock(return_value=None)
    mutations = combat_end_mutations()
    mutations.save_combat_state = AsyncMock()
    mutations.update_player_hp = AsyncMock()
    return {
        "mutations": mutations,
        "queries": queries,
        "resolver": _damage_resolver(damage),
        "concentration_break_mod": break_mod,
        "db_mod": _fake_db_mod(),
    }


async def _resolve_round(ctx, *, max_calls: int = 64, **deps) -> Any:
    """Drive resolve_phase to the END of the round: allies, then every held enemy action, then
    the wrap (M29, story-016).

    Beat 3 holds the enemy blows behind reaction windows, so ONE resolve_phase call no longer
    resolves a whole phase — it resolves the ally band and then pauses once per window. A test
    that used to make one call and assert on the whole phase changes by one line: call this.

    ``max_calls`` bounds the loop rather than sizing it: a round costs one call for the ally band
    plus up to two per held enemy action plus one for the wrap, so a 10-enemy encounter is ~22.
    The bound exists to catch a pump that never terminates, not to predict the encounter.

    Typed ``Any`` rather than ``dict | tuple`` on purpose: which shape comes back is decided at
    RUNTIME by whether the round ended the fight, every caller disambiguates at its own call site
    (``isinstance(result, tuple)``), and a declared union would make ~60 correct subscripts a type
    error without catching a single real one.

    Returns the FINAL result — the loop-back JSON (as a dict) or the end-of-combat handoff tuple —
    with ``packets`` accumulated across every call, so whole-phase assertions still see every
    packet. Fails loud rather than returning a half-resolved round: never silently stops with a
    window still open, and never spins past ``max_calls``.
    """
    packets: list[dict] = []
    for _ in range(max_calls):
        result = await combat_turn._resolve_phase_impl(ctx, **deps)
        if isinstance(result, tuple):
            # End-of-combat handoff: the fight ended on this beat, so the round is over.
            return result
        payload = json.loads(result)
        packets.extend(payload.get("packets", []))
        if payload.get("next", {}).get("waiting_on") is None and payload["beat"] == "declaration":
            payload["packets"] = packets
            return payload
    state = ctx.userdata.combat_state
    raise AssertionError(
        f"the round did not terminate within {max_calls} resolve_phase calls "
        f"(beat={state.beat if state else None}, "
        f"held={[h['actor_id'] for h in state.held_actions] if state else None}, "
        f"open_window={state.open_window if state else None})"
    )


def _ctx_at_resolution(*, player_hp=25, enemy_hp=7, state=None, room=None):
    """A context parked at the RESOLUTION beat with the round's reaction unspent.

    The interrupt loop's entry point: resolve_phase from here holds the enemy blow and pauses on
    its windows, which is the only state in which ``_activate`` below is legal.
    """
    ctx = make_context(room=room) if room is not None else make_context()
    state = state if state is not None else _resolution_state(player_hp=player_hp, enemy_hp=enemy_hp)
    state.reactions_available = {p.id: reaction_spend.unspent() for p in state.participants if p.type == "player"}
    ctx.userdata.combat_state = state
    return ctx


async def _call(ctx, deps) -> dict:
    """One resolve_phase step, decoded. Fails loud if the fight ended when it should not have."""
    result = await combat_turn._resolve_phase_impl(ctx, **deps)
    assert not isinstance(result, tuple), "combat ended unexpectedly"
    return json.loads(result)


async def _activate(ctx, ability_id: str, *, player_class: str, stamina: int = 10, focus: int = 10):
    """Drive the REAL activate impl, so the gate, the resource write and the spend all run.

    The reactor is always ``session.player_id`` — activation is single-player (note 0f3945fa(c)) —
    so a test of a reaction that guards an ALLY must make player_1 the REACTOR and retarget the
    enemy at someone else.
    """
    db_mod, _conn = make_db_mod()
    queries = MagicMock()
    queries.get_players_for_update = AsyncMock(
        return_value={
            "player_1": {
                "player_id": "player_1",
                "name": "Kael",
                "class": player_class,
                "level": 5,
                "stamina": {"current": stamina, "max": 10},
                "focus": {"current": focus, "max": 10},
            }
        }
    )
    persistence = MagicMock()
    persistence.update_player_resources = AsyncMock()
    persistence.get_active_variant = AsyncMock(return_value=None)
    persistence.owns_elective = AsyncMock(return_value=False)
    return await _request_ability_activation_impl(
        ctx, ability_id, db_mod=db_mod, queries_mod=queries, persistence_mod=persistence
    )


def _ac_sensitive_resolver(attack_total, damage):
    """A resolve_attack mock that HITS iff ``attack_total`` reaches the effective AC it is handed.

    ``_damage_resolver`` always hits, so it reports the same landed blow at AC 14 and at AC 16 and
    can certify nothing about an AC modifier. This is the only resolver on which a reaction's +2
    can be shown to be what turned the blow aside.
    """

    def _resolve(attacker_data, action, target_ac, target_hp, attack_mod=0, damage_mult=1.0, target_conditions=()):
        hit = attack_total + attack_mod >= target_ac
        dealt = max(0, int(damage * damage_mult)) if hit else 0
        remaining = max(0, target_hp - dealt)
        return AttackResult(
            hit=hit,
            roll=attack_total - 3,
            attack_modifier=3,
            attack_total=attack_total + attack_mod,
            target_ac=target_ac,
            damage=dealt,
            damage_type="slashing",
            critical_success=False,
            critical_failure=False,
            target_hp_remaining=remaining,
            target_killed=hit and remaining == 0,
            narrative_hint="A clean strike." if hit else "The blade skids wide.",
        )

    r = MagicMock()
    r.resolve_attack = MagicMock(side_effect=_resolve)
    return r
