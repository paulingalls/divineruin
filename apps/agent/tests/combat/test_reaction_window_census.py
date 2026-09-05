"""The AC5 census: every reaction row in content/archetype_abilities.json, classified against a
LITERAL table, walked against every enemy action shape in content/encounter_templates.json.

The table below is WRITTEN OUT, never recomputed from the derivation under test — a classification
derived from the thing it classifies agrees with itself and certifies nothing (constraint 1).

The three classes, and why the third exists: `reachable` means some held enemy action opens a
window this row's `window` names. `unproducible` means nothing in the combat engine can ever open
it. `inapplicable` is the honest middle — the window OPENS, but the row's EFFECT TEXT has nothing
to bite on, because all 68 action_pool entries are weapon-shaped. Counting those three as rescued
would be the defect: story-018's AC3 narrates such a spend as "resolved with no mechanical effect"
and the player burns the round's one reaction for nothing.
"""

import json
from collections import Counter
from pathlib import Path

import abilities
import reaction_windows

_CONTENT = Path(__file__).resolve().parents[4] / "content"

# The full classification of all 25 reaction rows. Every value is justified by the row's own
# effect prose, quoted where the reason is not the window label.
EXPECTED: dict[str, str] = {
    # --- pre-roll: on_targeted (4) ---
    "bard_dissonant_whisper": "reachable",
    "mage_shield_spell": "reachable",
    "skirmisher_sidestep": "reachable",
    "whisper_thought_shield": "reachable",
    # --- pre-roll: on_ally_targeted (6) ---
    "bard_countercharm": "reachable",  # "ally targeted by fear/charm" — Hollow Shriek reaches it
    "cleric_shield_of_faith": "reachable",
    "diplomat_countercharm": "reachable",
    "marshal_interceding_order": "reachable",
    "oracle_shield_of_faith": "reachable",
    "paladin_shield_of_faith": "reachable",
    # --- post-roll: on_hit (5) ---
    "druid_bark_skin": "reachable",
    "guardian_retaliating_shield": "reachable",
    "rogue_uncanny_dodge": "reachable",
    "warden_bark_skin": "reachable",
    "warrior_brace_for_impact": "reachable",
    # --- post-roll: on_ally_hit (1) / on_enemy_miss (1) ---
    "guardian_intercept": "reachable",
    "skirmisher_riposte": "reachable",
    # --- catch-all on_enemy_action (4): ONE applicable, three not ---
    "whisper_implant_doubt": "reachable",  # "when an enemy succeeds an attack or ability"
    "diplomat_objection": "inapplicable",  # "when an NPC is about to act against your wishes"
    "spy_plausible_deniability": "inapplicable",  # "when accused/confronted"
    "marshal_countermand": "inapplicable",  # "when an enemy uses a command/leadership ability"
    # --- on_condition_imposed (2), reached only via the `grapple` property branch ---
    "rogue_slippery": "reachable",
    "spy_slippery": "reachable",
    # --- no producer exists under ANY design (debt: on_enemy_move, on_spell_cast) ---
    "warrior_opportunity_strike": "unproducible",  # on_enemy_move: no movement in the engine
    "mage_counterspell": "unproducible",  # on_spell_cast: no enemy casts (combat_ability.py:300)
}

_TOTALS = {"reachable": 20, "inapplicable": 3, "unproducible": 2}

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

# The `grapple` branch hangs on two content rows that are the SAME action twice. A content edit
# dropping Seizing Grab strands rogue_slippery and spy_slippery with nothing going red anywhere
# else, so the carriers are pinned as a literal.
_GRAPPLE_CARRIERS = [("mawling_1", "Seizing Grab"), ("mawling_2", "Seizing Grab")]

_NO_PRODUCER = {"on_enemy_move", "on_spell_cast"}


def _reaction_rows() -> list[dict]:
    rows = json.loads((_CONTENT / "archetype_abilities.json").read_text())
    return [r for r in rows if r.get("ability_type") == "reaction"]


def _enemy_actions() -> list[dict]:
    """Every action_pool entry across all encounter templates — the whole enemy vocabulary."""
    templates = json.loads((_CONTENT / "encounter_templates.json").read_text())
    return [action for tpl in templates for enemy in tpl.get("enemies", []) for action in enemy.get("action_pool", [])]


def _grapple_carriers() -> list[tuple[str, str]]:
    templates = json.loads((_CONTENT / "encounter_templates.json").read_text())
    return [
        (enemy["id"], action["name"])
        for tpl in templates
        for enemy in tpl.get("enemies", [])
        for action in enemy.get("action_pool", [])
        if reaction_windows.GRAPPLE_PROPERTY in (action.get("properties") or [])
    ]


def _produced_windows() -> set[str]:
    """Every window the derivation opens over the whole enemy action vocabulary, both stages."""
    produced: set[str] = set()
    for action in _enemy_actions():
        produced.update(reaction_windows.pre_roll_triggers(action))
        produced.update(reaction_windows.post_roll_triggers(action, hit=True))
        produced.update(reaction_windows.post_roll_triggers(action, hit=False))
    return produced


def test_the_table_covers_exactly_the_reaction_rows_that_exist():
    """A new reaction row — or a deleted one — reds here rather than quietly joining the
    unclassified. The table is the contract; content is not allowed to outgrow it in silence."""
    assert set(EXPECTED) == {row["id"] for row in _reaction_rows()}


def test_the_totals_are_the_ones_the_card_settled():
    assert Counter(EXPECTED.values()) == _TOTALS
    assert sum(_TOTALS.values()) == 25


def test_the_window_census_of_the_content_is_unchanged():
    assert Counter(row["window"] for row in _reaction_rows()) == _WINDOW_CENSUS


def test_every_row_the_table_calls_producible_has_its_window_produced():
    """The walk. `reachable` and `inapplicable` both require the window to OPEN — they differ
    only in whether the row's effect text can bite on a weapon swing, which no code can decide.
    `unproducible` requires the opposite: the window is never opened at all."""
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
    """Deleting Seizing Grab from the content strands rogue_slippery and spy_slippery: the
    on_condition_imposed branch would still exist in code and reach nothing."""
    assert _grapple_carriers() == _GRAPPLE_CARRIERS, (
        "the only content carriers of the `grapple` property have changed — rogue_slippery and "
        "spy_slippery reach on_condition_imposed through these entries and nothing else"
    )


def test_every_produced_trigger_is_a_member_of_the_closed_vocabulary():
    assert _produced_windows() <= abilities.REACTION_WINDOWS


def test_the_two_unproducible_windows_are_never_opened():
    """on_enemy_move: there is no movement in the combat engine at all. on_spell_cast: no enemy
    casts a spell. Neither is invented here to make a count look better."""
    assert _produced_windows().isdisjoint(_NO_PRODUCER)
