"""Every reaction the DM can be told about, against every window the engine can open.

story-017 made a reaction an INTERRUPT: the permission is the open Beat-3 window, not a Beat-1
declaration. So the contract to hold is between two producers that must share one vocabulary —
``query_tools._query_abilities_impl``, which surfaces each reaction's ``window`` to the DM, and
``reaction_windows``, which mints the ``triggers`` a held enemy action offers. A reaction whose
advertised window no producible window ever carries is a capability the DM can name and never
spend (constraint 6), so this walks the WHOLE catalog rather than one class's first reaction.

Two windows have no producer at all and are asserted REFUSED rather than papered over:
``on_enemy_move`` (no movement model — debt d3ff4ff4) and ``on_spell_cast`` (no enemy casting —
debt 08bc5548). Their reactions are unreachable by design until those land.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from archetype_abilities_config_fixture import load_fixture_config
from combat._helpers import (
    _ac_sensitive_resolver,
    _activate,
    _call,
    _ctx_at_resolution,
    _make_combat_state,
    _resolve_deps,
    _resolve_round,
)
from sample_fixtures import make_context, make_mock_room, published_payloads

import combat_reaction_effect
import event_types as E
import reaction_spend
import reaction_windows
from combat_phase import PhaseBeat, validate_reaction_activation
from query_tools import _query_abilities_impl
from session_data import CombatParticipant, CombatState

# The windows the real producer can emit, one entry per held-action shape it distinguishes.
# Built by calling reaction_windows, never transcribed: a trigger set copied into this file would
# certify the copy (constraint 9).
_PRODUCIBLE = {
    "pre_roll": reaction_windows.pre_roll_triggers({}),
    "post_roll_hit": reaction_windows.post_roll_triggers({}, hit=True),
    "post_roll_miss": reaction_windows.post_roll_triggers({}, hit=False),
    "post_roll_grapple": reaction_windows.post_roll_triggers(
        {"properties": [reaction_windows.GRAPPLE_PROPERTY]}, hit=True
    ),
}

NO_PRODUCER = {"on_enemy_move", "on_spell_cast"}


def _paused_state(triggers):
    state = _make_combat_state()
    state.beat = PhaseBeat.NARRATION
    state.open_window = reaction_windows.open_window_for(
        round_number=1,
        seq=0,
        stage="pre_roll",
        actor_id="goblin_scout_1",
        target_id="player_1",
        triggers=triggers,
    )
    state.reactions_available = {"player_1": reaction_spend.unspent()}
    return state


async def _queried_reactions():
    """Every reaction row the DM can be shown, for every archetype — the producer's own output."""
    context = make_context()
    queries = MagicMock()
    persistence = MagicMock()
    persistence.get_character_abilities = AsyncMock(return_value=[])
    persistence.get_active_variant = AsyncMock(return_value=None)

    catalog = load_fixture_config().values()
    rows = {}
    for player_class in sorted({ability.archetype_id for ability in catalog}):
        queries.get_player = AsyncMock(return_value={"class": player_class})
        payload = json.loads(await _query_abilities_impl(context, queries=queries, persistence=persistence))
        for row in payload["abilities"]:
            if row["ability_type"] == "reaction":
                rows[row["id"]] = row["window"]
    assert rows.keys() == {a.id for a in catalog if a.ability_type == "reaction"}
    return rows


@pytest.mark.asyncio
async def test_every_queried_reaction_window_is_answered_by_a_real_open_window():
    """The accept half, catalog-wide: each advertised window is one the engine actually opens.

    A gate that read a constant "on_hit" would still accept the reactions carrying that window,
    so the sweep has to name which producible window answered each id — and refuse to accept a
    reaction at a window that does not carry its trigger."""
    reachable = {}
    for ability_id, window in (await _queried_reactions()).items():
        if window in NO_PRODUCER:
            continue
        answered = [name for name, triggers in _PRODUCIBLE.items() if window in triggers]
        assert answered, f"{ability_id} advertises {window!r}, which no held action ever opens"
        for name in answered:
            state = _paused_state(_PRODUCIBLE[name])
            assert validate_reaction_activation(state, "player_1", ability_id) is None, (ability_id, name)
        reachable[ability_id] = window

    assert reachable, "the sweep walked no reactions — the query producer went silent"


@pytest.mark.asyncio
async def test_a_reaction_whose_window_has_no_producer_is_refused_at_every_window():
    """Stated honestly rather than skipped: warrior_opportunity_strike (on_enemy_move) and
    mage_counterspell (on_spell_cast) cannot be spent, at any stage, on any held action."""
    unreachable = {i: w for i, w in (await _queried_reactions()).items() if w in NO_PRODUCER}
    assert unreachable.keys() == {"warrior_opportunity_strike", "mage_counterspell"}

    for ability_id, window in unreachable.items():
        for triggers in _PRODUCIBLE.values():
            state = _paused_state(triggers)
            with pytest.raises(ValueError, match=window):
                validate_reaction_activation(state, "player_1", ability_id)


@pytest.mark.asyncio
async def test_the_two_window_vocabularies_are_one():
    """reaction_windows emits nothing the ability catalog cannot consume, and the catalog
    advertises nothing outside abilities.REACTION_WINDOWS. Either drift ships a window the other
    side cannot read — the exact shape of the guess-among-nine defect constraint 6 names."""
    import abilities

    produced = {trigger for triggers in _PRODUCIBLE.values() for trigger in triggers}
    consumed = set((await _queried_reactions()).values())

    assert produced <= abilities.REACTION_WINDOWS
    assert produced == consumed - NO_PRODUCER


# --- the wired outcomes (story-018) ----------------------------------------------------------
#
# story-017 left a spend that named its ability and its blow and changed nothing. These are the
# two outcomes game_mechanics_combat.md:187 names and the tree did not have. The third
# (Counterspell) is NOT here: on_spell_cast has no producer (debt 08bc5548), and the sweep above
# pins it refused rather than shipping a vacuous guard for it.

UNCANNY_DODGE = "rogue_uncanny_dodge"


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


async def _to_post_roll_pause(ctx, deps) -> dict:
    """Drive the round to the POST-ROLL, pre-damage pause on the held goblin blow.

    Three calls: the ally band (which holds the enemy action), the pre-roll window, then the roll
    plus the post-roll window. Nothing is spent at the pre-roll pause, so the post-roll one opens.
    """
    await _call(ctx, deps)
    await _call(ctx, deps)
    paused = await _call(ctx, deps)
    assert paused["next"]["waiting_on"]["stage"] == reaction_windows.POST_ROLL
    return paused


@pytest.mark.asyncio
async def test_uncanny_dodge_halves_the_damage_of_the_blow_it_answers():
    """AC1. The SAME seeded blow, run twice: the only difference is the spend.

    Asserted from BOTH ends on purpose. ``apply_attack_result`` writes HP from the roll's
    ABSOLUTE ``target_hp_remaining`` (combat_support.py:286) and never derives it from ``damage``,
    so halving the reported damage alone leaves hp_current at the unhalved value — and recomputing
    HP without rewriting the roll leaves the DICE_ROLL, the event line and the packet all
    narrating the full number at a player who took half.
    """
    room = make_mock_room()
    ctx = _ctx_at_resolution(room=room)
    deps = _resolve_deps(damage=6)
    await _to_post_roll_pause(ctx, deps)
    await _activate(ctx, UNCANNY_DODGE, player_class="rogue")
    final = await _call(ctx, deps)

    assert ctx.userdata.combat_state.get_participant("player_1").hp_current == 22
    assert _enemy_blow(final["packets"])["damage"] == 3
    dice = [p for p in published_payloads(room) if p.get("type") == E.DICE_ROLL and p.get("attacker") == "Goblin Scout"]
    assert [d["damage"] for d in dice] == [3]
    assert "Goblin Scout attacks Kael: hit, 3 damage" in ctx.userdata.recent_events


@pytest.mark.asyncio
async def test_the_same_blow_unanswered_deals_its_whole_damage():
    """The baseline half of AC1's "half what the SAME seeded roll deals without the reaction".

    Without it the test above pins a number, not a difference: a resolver that happened to deal 3
    would pass it while the reaction did nothing.
    """
    room = make_mock_room()
    ctx = _ctx_at_resolution(room=room)
    deps = _resolve_deps(damage=6)
    await _to_post_roll_pause(ctx, deps)
    final = await _call(ctx, deps)

    assert ctx.userdata.combat_state.get_participant("player_1").hp_current == 19
    assert _enemy_blow(final["packets"])["damage"] == 6
    dice = [p for p in published_payloads(room) if p.get("type") == E.DICE_ROLL and p.get("attacker") == "Goblin Scout"]
    assert [d["damage"] for d in dice] == [6]


SHIELD_OF_FAITH = "cleric_shield_of_faith"
# The two on_ally_targeted reactions deliberately left unwired: they grant ADVANTAGE ON A SAVE
# against fear/charm, not +2 AC (reaction_windows' module docstring names both). Excluded by name
# so a SEVENTH row appearing in that window is a decision someone made, not an accident.
COUNTERCHARMS = frozenset({"bard_countercharm", "diplomat_countercharm"})


def _guarded_ally_state(*, enemy_ids=("goblin_scout_1",)):
    """A round whose enemy blows all fall on player_2, with player_1 free to guard them.

    ``activate`` derives the reactor from ``session.player_id`` (note 0f3945fa(c)), so a test of a
    reaction that protects an ALLY has to make player_1 the reactor and someone else the target.
    Neither player declares: the ally band has nothing to resolve, so the enemies survive to swing
    and the round is exactly the held blows under test.
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
            enemy_id: {"type": "attack", "action": "Scimitar", "target_id": "player_2"} for enemy_id in enemy_ids
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


@pytest.mark.asyncio
async def test_shield_of_faith_turns_a_hit_into_a_miss_on_the_ally_it_guards():
    """AC2. A seeded roll that HITS at the ally's base AC and MISSES at +2, so the reaction is
    provably what caused the miss — a resolver that always hits would report the same landed blow
    at either AC and certify nothing."""
    ctx = _ctx_at_resolution(state=_guarded_ally_state())
    deps = {**_resolve_deps(), "resolver": _ac_sensitive_resolver(attack_total=14, damage=4)}
    packets: list[dict] = []

    await _pause_at(ctx, deps, actor_id="goblin_scout_1", stage=reaction_windows.PRE_ROLL, packets=packets)
    await _activate(ctx, SHIELD_OF_FAITH, player_class="cleric")
    await _drain(ctx, deps, packets)

    blow = _enemy_blows(packets)["goblin_scout_1"]
    assert blow["hit"] is False
    assert blow["target_ac"] == 16
    assert ctx.userdata.combat_state.get_participant("player_2").hp_current == 20


@pytest.mark.asyncio
async def test_the_same_blow_unguarded_lands_at_the_allys_base_ac():
    """AC2's baseline. Without it the test above pins an AC, not a difference."""
    ctx = _ctx_at_resolution(state=_guarded_ally_state())
    deps = {**_resolve_deps(), "resolver": _ac_sensitive_resolver(attack_total=14, damage=4)}
    packets: list[dict] = []

    await _drain(ctx, deps, packets)

    blow = _enemy_blows(packets)["goblin_scout_1"]
    assert blow["hit"] is True
    assert blow["target_ac"] == 14
    assert ctx.userdata.combat_state.get_participant("player_2").hp_current == 16


@pytest.mark.asyncio
async def test_the_reaction_changes_only_the_blow_it_was_spent_against():
    """AC5. Two held blows on the same ally, one reaction, spent at the FIRST one's window.

    ``held_seq`` is what selects the blow. Applying the bonus to every held attack — the obvious
    shape, and what ``state.ac_modifiers`` would give since it is per-participant and phase-scoped
    — reds here on the second goblin missing a blow it must land.
    """
    ctx = _ctx_at_resolution(state=_guarded_ally_state(enemy_ids=("goblin_scout_1", "goblin_scout_2")))
    deps = {**_resolve_deps(), "resolver": _ac_sensitive_resolver(attack_total=14, damage=4)}
    packets: list[dict] = []

    await _pause_at(ctx, deps, actor_id="goblin_scout_1", stage=reaction_windows.PRE_ROLL, packets=packets)
    await _activate(ctx, SHIELD_OF_FAITH, player_class="cleric")
    await _drain(ctx, deps, packets)

    blows = _enemy_blows(packets)
    assert (blows["goblin_scout_1"]["hit"], blows["goblin_scout_1"]["target_ac"]) == (False, 14 + 2)
    assert (blows["goblin_scout_2"]["hit"], blows["goblin_scout_2"]["target_ac"]) == (True, 14)
    assert ctx.userdata.combat_state.get_participant("player_2").hp_current == 16


def test_the_wired_sets_name_real_catalog_rows_at_the_right_window():
    """The three id sets are transcribed from content/archetype_abilities.json and nothing else
    enforces that. A renamed or rewindowed row would leave a reaction silently unwired — the
    player pays and the blow lands unchanged, which is the exact defect this story fixes.

    The closure half is what makes this more than a restatement of the constants: every
    on_ally_targeted reaction in content is either wired for +2 AC or named as a countercharm, so
    a new row in that window reds here instead of shipping unspendable.
    """
    catalog = load_fixture_config()
    wired = combat_reaction_effect.HALVES_DAMAGE | set(combat_reaction_effect.AC_BONUS)
    for ability_id in wired:
        assert catalog[ability_id].ability_type == "reaction", ability_id

    assert {catalog[i].window for i in combat_reaction_effect.HALVES_DAMAGE} == {"on_hit"}
    assert {catalog[i].window for i in combat_reaction_effect.AC_BONUS} == {"on_ally_targeted"}

    guarding = {a.id for a in catalog.values() if a.ability_type == "reaction" and a.window == "on_ally_targeted"}
    assert guarding - COUNTERCHARMS == set(combat_reaction_effect.AC_BONUS)
