"""What a spent reaction actually DOES to the held blow it answered (M29, story-018).

``game_mechanics_combat.md:187`` names three outcomes — Uncanny Dodge halves damage, Shield of
Faith causes a miss, Counterspell negates. Two ship here. COUNTERSPELL DOES NOT: its window is
``on_spell_cast`` and no enemy in content casts a spell, so the window has no producer (debt
08bc5548). ``test_reaction_catalog_reach.py`` — this file's other half, which holds the catalog /
window vocabulary census — pins it REFUSED at every window rather than certifying a vacuous guard.

Every test drives the real ``resolve_phase`` / ``activate`` implementations end to end, so a
reaction changes an outcome the same way the DM's own calls would produce it.
"""

import pytest
from archetype_abilities_config_fixture import load_fixture_config
from combat._helpers import (
    _ac_sensitive_resolver,
    _activate,
    _call,
    _ctx_at_resolution,
    _resolve_deps,
    _resolve_round,
)
from sample_fixtures import make_mock_room, published_payloads

import combat_reaction_effect
import event_types as E
import reaction_windows
from session_data import CombatParticipant, CombatState

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


INERT_REACTION = "skirmisher_sidestep"  # on_targeted — deliberately outside the wired set


def _reaction_packet(packets: list[dict]) -> dict:
    """The packet the closing window synthesized for the reaction itself.

    Synthesized, not read from a declaration: story-017 deleted DeclarationType.REACTION and the
    reaction branch in combat_packet, so a reaction produces no declaration packet at all.
    """
    found = [p for p in packets if p.get("declaration_type") == "reaction"]
    assert len(found) == 1, f"expected exactly one reaction packet, got {found}"
    return found[0]


@pytest.mark.asyncio
async def test_an_unwired_reaction_returns_a_packet_that_claims_no_effect():
    """AC3. Never a silent no-op — the packet exists and the DM can voice it — and never a claim
    of an effect it did not have: mechanical_effect is null and the blow lands untouched.

    This is note 0f3945fa(f) answered. ``resolved: true`` used to mean only that the resource was
    spent; the load-bearing field is now what the close actually DID.
    """
    ctx = _ctx_at_resolution()
    deps = _resolve_deps(damage=6)
    packets: list[dict] = []

    await _pause_at(ctx, deps, actor_id="goblin_scout_1", stage=reaction_windows.PRE_ROLL, packets=packets)
    await _activate(ctx, INERT_REACTION, player_class="skirmisher")
    await _drain(ctx, deps, packets)

    packet = _reaction_packet(packets)
    assert packet["ability_id"] == INERT_REACTION
    assert packet["mechanical_effect"] is None
    assert packet["narration_cue"]
    assert packet["against_actor_id"] == "goblin_scout_1"
    assert _enemy_blow(packets)["damage"] == 6
    assert ctx.userdata.combat_state.get_participant("player_1").hp_current == 19


@pytest.mark.asyncio
async def test_a_wired_reaction_names_the_effect_it_had():
    """The discriminating half: mechanical_effect is not constantly null, so the assertion above
    is a claim about this reaction rather than about the field always being absent."""
    ctx = _ctx_at_resolution()
    deps = _resolve_deps(damage=6)
    packets: list[dict] = []

    await _pause_at(ctx, deps, actor_id="goblin_scout_1", stage=reaction_windows.POST_ROLL, packets=packets)
    await _activate(ctx, UNCANNY_DODGE, player_class="rogue")
    await _drain(ctx, deps, packets)

    assert _reaction_packet(packets)["mechanical_effect"] == "damage_halved"

    ctx = _ctx_at_resolution(state=_guarded_ally_state())
    deps = {**_resolve_deps(), "resolver": _ac_sensitive_resolver(attack_total=14, damage=4)}
    packets = []
    await _pause_at(ctx, deps, actor_id="goblin_scout_1", stage=reaction_windows.PRE_ROLL, packets=packets)
    await _activate(ctx, SHIELD_OF_FAITH, player_class="cleric")
    await _drain(ctx, deps, packets)

    assert _reaction_packet(packets)["mechanical_effect"] == "target_ac_bonus"


@pytest.mark.asyncio
async def test_a_wired_ability_against_an_action_with_no_roll_claims_nothing():
    """The other half of "never a claim of an effect it did not have".

    Hollow Shriek carries applies_condition, so it resolves through the save-gated condition path
    and has no attack roll to modify — the pre-roll window is the only one it opens, and it is
    exactly how the countercharms reach a reaction. A shield-of-faith spent there changed no AC,
    so the packet must say so. A mechanical_effect keyed on the ability id ALONE would pass here
    while telling the DM a blow was turned aside that was never rolled.
    """
    state = _guarded_ally_state()
    shrieker = next(p for p in state.participants if p.id == "goblin_scout_1")
    shrieker.action_pool = [
        {
            "name": "Hollow Shriek",
            "damage": "0",
            "damage_type": "psychic",
            "properties": ["control"],
            "applies_condition": "frightened",
            "save": "wisdom",
            "dc": 12,
        }
    ]
    state.pending_declarations["goblin_scout_1"]["action"] = "Hollow Shriek"
    ctx = _ctx_at_resolution(state=state)
    deps = {**_resolve_deps(), "resolver": _ac_sensitive_resolver(attack_total=14, damage=4)}
    packets: list[dict] = []

    await _pause_at(ctx, deps, actor_id="goblin_scout_1", stage=reaction_windows.PRE_ROLL, packets=packets)
    await _activate(ctx, SHIELD_OF_FAITH, player_class="cleric")
    await _drain(ctx, deps, packets)

    assert _reaction_packet(packets)["mechanical_effect"] is None
