from __future__ import annotations

from collections import Counter

from _gods_content import load_gods

LEGACY_ACTIONS = {
    ("veythar", "positive", "discovered_lore"): 3,
    ("veythar", "positive", "solved_puzzle"): 5,
    ("veythar", "positive", "asked_questions"): 1,
    ("veythar", "positive", "preserved_artifact"): 4,
    ("veythar", "positive", "chose_investigation"): 2,
    ("veythar", "negative", "destroyed_knowledge"): -5,
    ("veythar", "negative", "ignored_mystery"): -2,
    ("veythar", "negative", "acted_recklessly"): -3,
    ("kaelen", "positive", "won_combat"): 2,
    ("kaelen", "positive", "defended_innocent"): 5,
    ("kaelen", "positive", "showed_courage"): 3,
    ("kaelen", "positive", "tactical_victory"): 4,
    ("kaelen", "positive", "trained_others"): 2,
    ("kaelen", "negative", "fled_combat"): -3,
    ("kaelen", "negative", "cruelty_in_victory"): -5,
    ("kaelen", "negative", "abandoned_ally"): -4,
    ("aelora", "positive", "crafted_item"): 2,
    ("aelora", "positive", "helped_community"): 4,
    ("aelora", "positive", "fair_trade"): 1,
    ("aelora", "positive", "built_fortifications"): 5,
    ("aelora", "positive", "reunited_people"): 3,
    ("aelora", "negative", "destroyed_infrastructure"): -4,
    ("aelora", "negative", "cheated_merchant"): -2,
    ("aelora", "negative", "abandoned_community"): -3,
    ("syrath", "positive", "uncovered_secret"): 5,
    ("syrath", "positive", "successful_stealth"): 2,
    ("syrath", "positive", "gathered_intelligence"): 3,
    ("syrath", "positive", "detected_lie"): 3,
    ("syrath", "positive", "kept_secret"): 2,
    ("syrath", "negative", "revealed_secret"): -3,
    ("syrath", "negative", "obvious_approach"): -1,
    ("syrath", "negative", "trusted_blindly"): -2,
}


def test_every_patron_has_complete_alignment_content():
    minimums = {
        "values": 5,
        "opposed_values": 4,
        "favor_actions.positive": 5,
        "favor_actions.negative": 3,
    }
    missing = []
    for patron in load_gods():
        counts = {
            "values": len(patron["values"]),
            "opposed_values": len(patron["opposed_values"]),
            "favor_actions.positive": len(patron["favor_actions"]["positive"]),
            "favor_actions.negative": len(patron["favor_actions"]["negative"]),
        }
        missing.extend(
            f"{patron['god_id']} {field}: {counts[field]} < {minimum}"
            for field, minimum in minimums.items()
            if counts[field] < minimum
        )

    assert not missing, "\n".join(missing)


def test_favor_action_rows_have_required_fields():
    for patron in load_gods():
        for row in patron["favor_actions"]["positive"]:
            assert row["action"], patron["god_id"]
            assert row["description"], f"{patron['god_id']} {row['action']}"
            assert isinstance(row["amount"], int), f"{patron['god_id']} {row['action']}"
        for row in patron["favor_actions"]["negative"]:
            assert row["action"], patron["god_id"]
            assert row["description"], f"{patron['god_id']} {row['action']}"
            assert isinstance(row["amount"], int), f"{patron['god_id']} {row['action']}"
            assert row["opposed_value"], f"{patron['god_id']} {row['action']}"


def test_negative_actions_reference_their_patron_opposed_values():
    for patron in load_gods():
        for row in patron["favor_actions"]["negative"]:
            assert row["opposed_value"] in patron["opposed_values"], (
                f"{patron['god_id']} {row['action']}: {row['opposed_value']!r}"
            )


def test_opposed_value_ids_belong_to_exactly_one_patron():
    """A shared id would let a negative row cite another patron's opposed value
    and still pass test_negative_actions_reference_their_patron_opposed_values."""
    opposed_ids = [opposed_value for patron in load_gods() for opposed_value in patron["opposed_values"]]
    shared = [opposed_value for opposed_value, count in Counter(opposed_ids).items() if count > 1]

    assert not shared, f"opposed_value IDs shared by several patrons: {shared}"


def test_action_ids_are_unique_across_all_patrons():
    action_ids = [
        row["action"]
        for patron in load_gods()
        for category in ("positive", "negative")
        for row in patron["favor_actions"][category]
    ]
    duplicates = [action for action, count in Counter(action_ids).items() if count > 1]

    assert not duplicates, f"duplicate favor action IDs: {duplicates}"


def test_action_amount_sign_matches_category():
    for patron in load_gods():
        for row in patron["favor_actions"]["positive"]:
            assert row["amount"] > 0, f"{patron['god_id']} {row['action']}"
        for row in patron["favor_actions"]["negative"]:
            assert row["amount"] < 0, f"{patron['god_id']} {row['action']}"


def test_preexisting_action_ids_and_amounts_are_unchanged():
    actual = {
        (patron["god_id"], category, row["action"]): row["amount"]
        for patron in load_gods()
        if patron["god_id"] in {"veythar", "kaelen", "aelora", "syrath"}
        for category in ("positive", "negative")
        for row in patron["favor_actions"][category]
    }

    assert actual == LEGACY_ACTIONS
