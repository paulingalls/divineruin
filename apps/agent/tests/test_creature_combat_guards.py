import copy

import pytest
from creature_combat_helpers import catalog, row, selected

from creature_combat import translate_creature
from creature_schema import validate_creature_stat_block


def translate(source, **kwargs):
    return translate_creature(
        source, **{"encounter_id": "enc137", "enemy_id": "enemy137", "role": "standard", **kwargs}
    )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda r: r.update(id=""),
        lambda r: r.update(hp="ten"),
        lambda r: r.update(attacks=None),
        lambda r: r.update(actives=None),
        lambda r: r["attributes"].update(STR="strong"),
        lambda r: r.update(save_proficiencies=["BAD"]),
        lambda r: r["attacks"][0].update(to_hit="four"),
        lambda r: r["attacks"][0].update(damage="oops"),
        lambda r: r["attacks"][0].update(properties=["grapple"]),
        lambda r: r["attacks"][0].update(applies_condition="unknown", save="DEX", dc=12),
        lambda r: r["attacks"][0].update(recharge={"kind": "roll", "die": 6, "threshold": 7}),
    ],
)
def test_translation_rejects_invalid_identity_and_fields(mutation):
    source = row("bandit")
    mutation(source)
    with pytest.raises(ValueError, match=r"creature .*encounter .*enemy "):
        translate(source)


@pytest.mark.parametrize("kwargs", [{"enemy_id": ""}, {"encounter_id": None}, {"role": "custom"}, {"role": "named"}])
def test_translation_rejects_bad_boundary(kwargs):
    with pytest.raises(ValueError, match=r"creature .*encounter .*enemy "):
        translate(row("bandit"), **kwargs)


def test_translation_rejects_named_custom_and_unusable_pool():
    source = row("hollow_knight")
    source["hollow"]["class"] = "named"
    with pytest.raises(ValueError, match="Named/custom"):
        translate(source)
    source = row("bandit")
    source["category"] = "elemental"
    with pytest.raises(ValueError, match="unsupported category"):
        translate(source)
    for attacks in ([], [{**source["attacks"][0], "recharge": {"kind": "encounter", "uses": 1}}]):
        source = row("bandit")
        source["attacks"] = attacks
        source["actives"] = []
        with pytest.raises(ValueError, match="no usable damaging attack"):
            translate(source, role="minion")
    source = row("bandit")
    source["actives"].append({**source["actives"][0], "name": source["attacks"][0]["name"]})
    with pytest.raises(ValueError, match=r"Short Sword.*duplicate"):
        translate(source)


@pytest.mark.parametrize("carrier", ["grapple", "condition"])
def test_invalid_carriers_are_rejected_by_both_contracts(carrier):
    source = row("bandit")
    action = source["attacks"][0]
    if carrier == "grapple":
        action["properties"] = ["grapple"]
    else:
        action.update(applies_condition="unknown", save="DEX", dc=12)
    assert validate_creature_stat_block(source)
    with pytest.raises(ValueError, match=r"attacks\[0\]"):
        translate(source)


def test_selected_corpus_floor_faults():
    rows = catalog()
    for bad in ([], [*rows, row("bandit")], [r for r in rows if r["id"] != "bandit"]):
        with pytest.raises(AssertionError):
            selected(bad)
    with pytest.raises(AssertionError):
        selected(rows, validator=lambda r: None)


def test_structured_command_recharge_contract():
    source = row("ashmark_sergeant")
    source["actives"][0]["recharge"] = {"kind": "round", "uses": 1}
    assert validate_creature_stat_block(source) == []
    narrative = copy.deepcopy(source)
    del narrative["actives"][0]["kind"]
    assert validate_creature_stat_block(narrative)
    source["actives"][0]["recharge"]["uses"] = 0
    assert validate_creature_stat_block(source)


def test_special_text_does_not_drive_actions():
    source = row("hollow_mawling")
    before = translate(source)["action_pool"]
    changed = copy.deepcopy(source)
    for action in changed["attacks"]:
        action["special"] = "Everything explodes and heals."
    after = translate(changed)["action_pool"]
    for a, b in zip(before, after, strict=True):
        assert {k: v for k, v in a.items() if k != "special"} == {k: v for k, v in b.items() if k != "special"}


def test_unknown_attribute_fails_with_identity():
    source = row("bandit")
    source["attributes"]["LUCK"] = 10
    with pytest.raises(ValueError, match=r"bandit.*enc137.*enemy137.*attributes.*LUCK"):
        translate(source)


def test_zero_flat_damage_cannot_pass_usable_attack_floor():
    source = row("bandit")
    source["attacks"] = [{**source["attacks"][0], "damage": "00"}]
    source["actives"] = []
    with pytest.raises(ValueError, match=r"bandit.*enc137.*enemy137.*no usable damaging attack"):
        translate(source)
