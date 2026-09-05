"""Fixtures for driving a Beat-3 round that a reaction interrupts (M29, story-018).

Shared by ``test_reaction_resolution.py`` (the two wired outcomes) and
``test_reaction_effect_guards.py`` (the checks that decide which blow a spend may touch). They
live here rather than in one of those files because a test module importing another test module
makes the importer's collection depend on the importee's.
"""

from unittest.mock import AsyncMock, patch

from combat._helpers import _call, _resolve_deps, _resolve_round

import combat_support
from session_data import CombatParticipant, CombatState

SHIELD_ITEM = {"id": "shield_iron", "type": "shield", "durability_tier": "standard", "slot_info": {"equipped": True}}


def _enemy_blows(packets: list[dict]) -> dict[str, dict]:
    """Each held enemy attack's resolution summary, by attacker.

    Keyed on the ENEMY ids under test rather than by comprehending every packet's actor_id: a
    reaction packet carries the REACTING PLAYER's actor_id, so a blanket actor_id comprehension
    would collide with a player's own packet in a round where they both act and react.
    """
    blows = {p["actor_id"]: p for p in packets if p["actor_id"].startswith("goblin_") and "damage" in p}
    assert blows, f"no resolved enemy blow among {packets}"
    return blows


def _enemy_blow(packets: list[dict]) -> dict:
    """The one held goblin attack's summary — the blow the reaction was spent against."""
    blows = _enemy_blows(packets)
    assert len(blows) == 1, f"expected exactly one resolved enemy blow, got {blows}"
    return next(iter(blows.values()))


def _reaction_packet(packets: list[dict]) -> dict:
    """The packet the closing window synthesized for the reaction itself.

    Synthesized, not read from a declaration: story-017 deleted DeclarationType.REACTION and the
    reaction branch in combat_packet, so a reaction produces no declaration packet at all.
    """
    found = [p for p in packets if p.get("declaration_type") == "reaction"]
    assert len(found) == 1, f"expected exactly one reaction packet, got {found}"
    return found[0]


def _guarded_ally_state(*, enemy_ids=("goblin_scout_1",), target_id="player_2"):
    """A round whose enemy blows all fall on ``target_id``, with player_1 free to react.

    ``activate`` derives the reactor from ``session.player_id`` (note 0f3945fa(c)), so a test of a
    reaction that protects an ALLY has to make player_1 the reactor and someone else the target —
    and a test of one that may only protect the REACTOR passes ``target_id="player_1"``. Neither
    player declares: the ally band has nothing to resolve, so the enemies survive to swing and the
    round is exactly the held blows under test.
    """
    return CombatState(
        combat_id="combat_guard",
        participants=[
            CombatParticipant(
                id="player_1", name="Kael", type="player", initiative=20, hp_current=25, hp_max=25, ac=14
            ),
            CombatParticipant(
                id="player_2", name="Bram", type="player", initiative=18, hp_current=20, hp_max=20, ac=14
            ),
            *[
                CombatParticipant(
                    id=enemy_id,
                    name=f"Goblin {n + 1}",
                    type="enemy",
                    initiative=12 - n,
                    hp_current=7,
                    hp_max=7,
                    ac=13,
                    action_pool=[{"name": "Scimitar", "damage": "1d6", "damage_type": "slashing", "properties": []}],
                    xp_value=50,
                )
                for n, enemy_id in enumerate(enemy_ids)
            ],
        ],
        initiative_order=["player_1", "player_2", *enemy_ids],
        round_number=1,
        current_turn_index=0,
        location_id="accord_guild_hall",
        beat="resolution",
        pending_declarations={
            enemy_id: {"type": "attack", "action": "Scimitar", "target_id": target_id} for enemy_id in enemy_ids
        },
    )


async def _pause_at(ctx, deps, *, actor_id, stage, packets):
    """resolve_phase until the machine pauses on ``actor_id``'s blow at ``stage``.

    Matched on the window's own actor_id + stage, never on its id string: ``reaction_spend``
    refused to make the ``r<n>-<seq>-<stage>`` format a contract and a test must not re-grant it.
    """
    for _ in range(16):
        payload = await _call(ctx, deps)
        packets.extend(payload["packets"])
        window = payload["next"]["waiting_on"]
        if window is not None and window["actor_id"] == actor_id and window["stage"] == stage:
            return
    raise AssertionError(f"never paused on {actor_id}'s {stage} window")


async def _drain(ctx, deps, packets):
    """Run the rest of the round out, collecting every packet it produces."""
    payload = await _resolve_round(ctx, **deps)
    packets.extend(payload["packets"])
    return packets


def _shield_bearing_deps(damage: int = 6):
    """resolve_phase deps whose only equipped item is a shield — no armor, so the ONE durability
    accrual a run makes is the shield's, and ``assert_not_awaited`` is a statement about it."""
    deps = _resolve_deps(damage=damage)
    deps["queries"].get_player_inventory = AsyncMock(return_value=[SHIELD_ITEM])
    return deps


def _patched_accrual():
    """``_accrue_durability`` is imported into combat_support by name and takes no DI, so a test
    that lets it run reaches the real inventory mutations. Patched at the importing module."""
    return patch.object(
        combat_support,
        "_accrue_durability",
        AsyncMock(return_value={"broken": False, "penalty": {}, "current_hits": 9}),
    )
