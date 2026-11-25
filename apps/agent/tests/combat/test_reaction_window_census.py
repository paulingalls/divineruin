"""Keep a literal independent classification: deriving expected reach from the implementation would agree with itself."""

import json
from collections import Counter
from pathlib import Path
from random import Random

from combat._helpers import _make_combat_state
from sample_fixtures import catalog_encounters

import abilities
import combat_melee_approach as melee
import combat_opportunity
import combat_spatial
import reaction_windows
from creature_combat import translate_creature
from encounter_builder import build_encounter

_CONTENT = Path(__file__).resolve().parents[4] / "content"

# The full classification of all 25 reaction rows. Every value is justified by the row's own
# effect prose, quoted where the reason is not the window label.
EXPECTED: dict[str, str] = {
    "bard_dissonant_whisper": "reachable",
    "mage_shield_spell": "reachable",
    "skirmisher_sidestep": "reachable",
    "whisper_thought_shield": "reachable",
    "bard_countercharm": "reachable",  # "ally targeted by fear/charm" — Hollow Shriek reaches it
    "cleric_shield_of_faith": "reachable",
    "diplomat_countercharm": "reachable",
    "marshal_interceding_order": "reachable",
    "oracle_shield_of_faith": "reachable",
    "paladin_shield_of_faith": "reachable",
    "druid_bark_skin": "reachable",
    "guardian_retaliating_shield": "reachable",
    "rogue_uncanny_dodge": "reachable",
    "warden_bark_skin": "reachable",
    "warrior_brace_for_impact": "reachable",
    "guardian_intercept": "reachable",
    "skirmisher_riposte": "reachable",
    "whisper_implant_doubt": "reachable",  # "when an enemy succeeds an attack or ability"
    "diplomat_objection": "reachable",  # any non-Hollow action, before it rolls
    "spy_plausible_deniability": "reachable",  # the Sergeant's accusation
    "marshal_countermand": "reachable",  # five authored commands
    "rogue_slippery": "reachable",
    "spy_slippery": "reachable",
    "warrior_opportunity_strike": "reachable",
    "mage_counterspell": "unproducible",  # on_spell_cast: no enemy casts (combat_ability.py:300)
}

_TOTALS = {"reachable": 24, "inapplicable": 0, "unproducible": 1}

# The measured window census of the 25 rows. Pinned literally so a content edit that RE-LABELS a
# row's window (rather than adding one) reds here instead of silently changing what is reachable.
_WINDOW_CENSUS = {
    "on_ally_targeted": 6,
    "on_hit": 5,
    "on_targeted": 4,
    "on_enemy_action": 4,
    "on_condition_imposed": 2,
    "on_ally_hit": 1,
    "on_enemy_miss": 1,
    "on_enemy_move": 1,
    "on_spell_cast": 1,
}

_GRAPPLE_CARRIERS = [("mawling_pack_adult", "Lunge"), ("generated_2", "Lunge")]
_RESTRAINT_CARRIERS = [("hollow_architect", "Entomb")]
_COMMAND_CARRIERS = [
    ("ashmark_patrol", "ashmark_sergeant", "Rally"),
    ("cult_cell", "cult_fanatic_1", "Bless"),
    ("hollow_corrupted_settlement", "hollowed_knight", "Command Lesser"),
    ("hollow_knight_boss", "hollowed_knight", "Command Lesser"),
]
_ACCUSATION_CARRIERS = [("ashmark_patrol", "ashmark_sergeant", "Accusation")]

_NO_PRODUCER = {"on_spell_cast"}


def _reaction_rows() -> list[dict]:
    rows = json.loads((_CONTENT / "archetype_abilities.json").read_text())
    return [r for r in rows if r.get("ability_type") == "reaction"]


def _templates():
    rows = json.loads((_CONTENT / "creatures.json").read_text())
    by_id = {row["id"]: row for row in rows}
    references = build_encounter(
        rows,
        2,
        [
            {"id": "player", "type": "player", "level": 5},
            {"id": "companion_kael", "type": "companion", "player_id": "player", "hp_factor": 0.75},
        ],
        {"region": "greyvale", "terrain": "forest"},
        "standard",
        Random(2),
    )
    generated = {
        "id": "generated_greyvale",
        "enemies": [
            translate_creature(
                by_id[ref["creature_id"]], encounter_id="generated_greyvale", enemy_id=ref["id"], role=ref["role"]
            )
            for ref in references
        ],
    }
    return [*catalog_encounters(), generated]


def _enemy_actions() -> list[dict]:
    return [action for tpl in _templates() for enemy in tpl["enemies"] for action in enemy["action_pool"]]


def _grapple_carriers() -> list[tuple[str, str]]:
    templates = _templates()
    return [
        (enemy["id"], action["name"])
        for tpl in templates
        for enemy in tpl.get("enemies", [])
        for action in enemy.get("action_pool", [])
        if reaction_windows.GRAPPLE_PROPERTY in (action.get("properties") or [])
    ]


def _kind_carriers(kind: str) -> list[tuple[str, str, str]]:
    templates = catalog_encounters()
    return sorted(
        (template["id"], enemy["id"], action["name"])
        for template in templates
        for enemy in template.get("enemies", [])
        for action in enemy.get("action_pool", [])
        if action.get("kind") == kind
    )


def movement_state():
    state = _make_combat_state()
    actor_id, reactor_id = "goblin_scout_1", "player_1"
    origin, endpoint, center = ({"x": x, "y": 0, "z": 0} for x in (3, 20, 0))
    action = next(action for action in _enemy_actions() if melee.is_melee(action))
    reactor = state.get_participant(reactor_id)
    assert reactor is not None
    weapon = reactor.action_pool[0]
    reach = melee.melee_reach(weapon)
    exits = combat_opportunity.reach_exits(origin, endpoint, {reactor_id: (center, reach)})
    (exit_point,) = exits
    combat_spatial.place(state, reactor_id, center)
    combat_spatial.place(state, actor_id, exit_point["point"])
    head = {"seq": 0, "actor_id": actor_id, "declaration": {"action": action["name"], "target_id": reactor_id}}
    state.held_actions = [head]
    state.open_window = combat_opportunity.movement_candidate(
        state, head, action, exit_point, {reactor_id: {"action": weapon, "reach": reach}}, 0
    )
    return state


def _produced_windows() -> set[str]:
    """Derive windows from authored encounters and a real generated adult encounter."""
    produced: set[str] = set()
    for action in _enemy_actions():
        produced.update(reaction_windows.pre_roll_triggers(action))
        produced.update(reaction_windows.post_roll_triggers(action, hit=True))
        produced.update(reaction_windows.post_roll_triggers(action, hit=False))
        produced.update(reaction_windows.condition_triggers(action, imposed=True))
        produced.update(reaction_windows.condition_triggers(action, imposed=False))
    window = movement_state().open_window
    assert window is not None
    produced.update(window["triggers"])
    return produced


def test_the_table_covers_exactly_the_reaction_rows_that_exist():
    assert set(EXPECTED) == {row["id"] for row in _reaction_rows()}


def test_the_totals_are_the_ones_the_card_settled():
    assert Counter(EXPECTED.values()) == Counter(_TOTALS)
    assert sum(_TOTALS.values()) == 25


def test_the_window_census_of_the_content_is_unchanged():
    assert Counter(row["window"] for row in _reaction_rows()) == _WINDOW_CENSUS


def test_every_row_the_table_calls_producible_has_its_window_produced():
    produced = _produced_windows()
    by_id = {row["id"]: row for row in _reaction_rows()}
    for ability_id, classification in EXPECTED.items():
        window = by_id[ability_id]["window"]
        if classification == "unproducible":
            assert window not in produced, (
                f"{ability_id} is classified unproducible but the derivation opens {window!r} — "
                "the table and the code disagree"
            )
        else:
            assert window in produced, (
                f"{ability_id} is classified {classification} but nothing opens {window!r} — "
                "a held enemy action can never reach it"
            )


def test_the_grapple_branch_carriers_are_pinned():
    assert _grapple_carriers() == _GRAPPLE_CARRIERS, (
        "authored encounters and the generated adult example must retain a grapple producer"
    )


def test_only_imposed_restraint_carriers_open_the_condition_window():
    carriers = []
    for template in _templates():
        for enemy in template["enemies"]:
            for action in enemy["action_pool"]:
                assert reaction_windows.condition_triggers(action, imposed=False) == ()
                triggers = reaction_windows.condition_triggers(action, imposed=True)
                if action.get("applies_condition") == "restrained":
                    carriers.append((template["id"], action["name"]))
                    assert triggers == ("on_condition_imposed",)
                else:
                    assert triggers == ()
    assert carriers == _RESTRAINT_CARRIERS


def test_social_subject_carriers_are_pinned():
    assert _kind_carriers("command") == _COMMAND_CARRIERS
    assert _kind_carriers("accusation") == _ACCUSATION_CARRIERS


def test_every_produced_trigger_is_a_member_of_the_closed_vocabulary():
    assert _produced_windows() <= abilities.REACTION_WINDOWS


def test_unproducible_window_is_never_opened():
    assert _produced_windows().isdisjoint(_NO_PRODUCER)
