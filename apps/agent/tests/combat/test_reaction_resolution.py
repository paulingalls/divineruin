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
from combat._helpers import _ac_sensitive_resolver, _activate, _call, _ctx_at_resolution, _resolve_deps
from combat._reaction_helpers import (
    _drain,
    _enemy_blow,
    _enemy_blows,
    _guarded_ally_state,
    _patched_accrual,
    _pause_at,
    _reaction_packet,
    _shield_bearing_deps,
)
from sample_fixtures import make_mock_room, published_payloads

import combat_reaction_effect
import event_types as E
import reaction_windows

UNCANNY_DODGE = "rogue_uncanny_dodge"


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

    The DICE_ROLL announces the as-rolled blow at the POST_ROLL pause. The later packet, HP, and
    event line pin the reaction's halving without publishing a second, corrected roll.
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
    assert [d["damage"] for d in dice] == [6]
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
UNWIRED_ON_HIT = frozenset({"druid_bark_skin", "warden_bark_skin", "warrior_brace_for_impact"})


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
    wired = (
        combat_reaction_effect.HALVES_DAMAGE
        | combat_reaction_effect.SHIELD_BEARING
        | set(combat_reaction_effect.AC_BONUS)
    )
    for ability_id in wired:
        assert catalog[ability_id].ability_type == "reaction", ability_id

    assert {catalog[i].window for i in combat_reaction_effect.HALVES_DAMAGE} == {"on_hit"}
    assert {catalog[i].window for i in combat_reaction_effect.SHIELD_BEARING} == {"on_hit"}
    assert {catalog[i].window for i in combat_reaction_effect.AC_BONUS} == {"on_ally_targeted"}

    guarding = {a.id for a in catalog.values() if a.ability_type == "reaction" and a.window == "on_ally_targeted"}
    assert guarding - COUNTERCHARMS == set(combat_reaction_effect.AC_BONUS)

    on_hit = {a.id for a in catalog.values() if a.ability_type == "reaction" and a.window == "on_hit"}
    wired_on_hit = combat_reaction_effect.HALVES_DAMAGE | combat_reaction_effect.SHIELD_BEARING
    assert not (wired_on_hit & UNWIRED_ON_HIT)
    assert on_hit == wired_on_hit | UNWIRED_ON_HIT


INERT_REACTION = "skirmisher_sidestep"  # on_targeted — deliberately outside the wired set


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


RETALIATING_SHIELD = "guardian_retaliating_shield"  # on_hit, effect ends "Requires shield."


@pytest.mark.asyncio
async def test_a_shield_bearing_reaction_accrues_a_shield_hit_through_the_pump():
    """AC4, through the LIVE path. ``_resolve_attack_packet``'s ``shield_reaction`` parameter was
    reachable only by a test calling the helper directly — a six-line branch whose sole exercise
    certified itself (note 0f3945fa(h), constraint 1). The reaction the DM spends reaches it now.

    The retaliation damage (1d6 + STR) is NOT wired and is not claimed: what ships is the wear the
    shield takes for being interposed.
    """
    ctx = _ctx_at_resolution()
    deps = _shield_bearing_deps()
    packets: list[dict] = []

    with _patched_accrual() as accrue:
        await _pause_at(ctx, deps, actor_id="goblin_scout_1", stage=reaction_windows.POST_ROLL, packets=packets)
        await _activate(ctx, RETALIATING_SHIELD, player_class="guardian")
        await _drain(ctx, deps, packets)

    assert "shield" in _enemy_blow(packets)["durability"]
    assert accrue.await_args is not None
    assert accrue.await_args.args[2]["id"] == "shield_iron" and accrue.await_args.args[3] == 1
    assert _reaction_packet(packets)["mechanical_effect"] == "shield_durability"


@pytest.mark.asyncio
async def test_the_same_blow_unanswered_wears_no_shield():
    """AC4's baseline: the shield is equipped either way, so only the reaction explains the hit."""
    ctx = _ctx_at_resolution()
    deps = _shield_bearing_deps()
    packets: list[dict] = []

    with _patched_accrual() as accrue:
        await _drain(ctx, deps, packets)

    assert "shield" not in _enemy_blow(packets)["durability"]
    accrue.assert_not_awaited()
