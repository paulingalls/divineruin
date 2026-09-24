from collections import Counter

import pytest

from _gods_content import load_gods

EXPECTED_GIFTS = {
    "veythar": ("short_rest", "awaits_rest"),
    "kaelen": ("per_encounter", "awaits_binding"),
    "aelora": ("always", "active"),
    "syrath": ("short_rest", "awaits_rest"),
    "mortaen": ("always", "narrated"),
    "thyra": ("always", "awaits_terrain"),
    "valdris": ("short_rest", "awaits_rest"),
    "nythera": ("always", "narrated"),
    "orenthel": ("always", "awaits_healing"),
    "zhael": ("long_rest", "awaits_rest"),
}
GIFT_FIELDS = {"id", "name", "effect", "trigger", "recharge", "status"}
RECHARGES = {"always", "per_encounter", "short_rest", "long_rest", "on_event"}
STATUSES = {
    "active",
    "awaits_binding",
    "awaits_rest",
    "awaits_terrain",
    "awaits_healing",
    "narrated",
}


def validate_gifts(rows):
    ids = [row["god_id"] for row in rows]
    assert set(ids) == set(EXPECTED_GIFTS)
    assert all(count == 1 for count in Counter(ids).values())
    gift_ids = []
    for row in rows:
        assert "layer_1_gift" in row, row["god_id"]
        gift = row["layer_1_gift"]
        assert isinstance(gift, dict), row["god_id"]
        expected_fields = GIFT_FIELDS | ({"mechanics"} if row["god_id"] == "aelora" else set())
        assert set(gift) == expected_fields, row["god_id"]
        assert all(isinstance(gift[field], str) and gift[field].strip() for field in GIFT_FIELDS), row["god_id"]
        if row["god_id"] == "aelora":
            assert gift["mechanics"] == {"kind": "skill_check_bonus", "amount": 1, "requires": "ally_present"}
        assert (gift["recharge"], gift["status"]) == EXPECTED_GIFTS[row["god_id"]]
        gift_ids.append(gift["id"])
    assert len(gift_ids) == len(set(gift_ids))


def test_expected_gift_table_uses_only_the_enums():
    # validate_gifts pins each row to this table, so content is in the enums only if the table is.
    assert {recharge for recharge, _ in EXPECTED_GIFTS.values()} <= RECHARGES
    assert {status for _, status in EXPECTED_GIFTS.values()} <= STATUSES


def test_every_patron_has_authored_layer_1_gift():
    validate_gifts(load_gods())


@pytest.mark.parametrize(
    "defect",
    [
        "empty",
        "missing",
        "duplicate",
        "missing_gift",
        "missing_field",
        "blank",
        "recharge",
        "status",
        "assigned_recharge",
        "assignment",
        "gift_id",
        "missing_mechanics",
        "wrong_kind",
        "wrong_amount",
        "wrong_requires",
        "extra_mechanics",
    ],
)
def test_gift_validator_rejects_defects(defect):
    rows = [{**row, "layer_1_gift": dict(row["layer_1_gift"])} for row in load_gods()]
    if defect == "empty":
        rows = []
    elif defect == "missing":
        rows.pop()
    elif defect == "duplicate":
        rows.append(rows[0])
    elif defect == "missing_gift":
        del rows[0]["layer_1_gift"]
    elif defect == "missing_field":
        del rows[0]["layer_1_gift"]["effect"]
    elif defect == "blank":
        rows[0]["layer_1_gift"]["name"] = " "
    elif defect == "recharge":
        rows[0]["layer_1_gift"]["recharge"] = "daily"
    elif defect == "status":
        rows[0]["layer_1_gift"]["status"] = "pending"
    elif defect == "assigned_recharge":
        rows[0]["layer_1_gift"]["recharge"] = "long_rest"
    elif defect == "assignment":
        rows[0]["layer_1_gift"]["status"] = "active"
    elif defect == "gift_id":
        rows[0]["layer_1_gift"]["id"] = rows[1]["layer_1_gift"]["id"]
    elif defect == "missing_mechanics":
        del next(row for row in rows if row["god_id"] == "aelora")["layer_1_gift"]["mechanics"]
    elif defect in {"wrong_kind", "wrong_amount", "wrong_requires"}:
        mechanics = next(row for row in rows if row["god_id"] == "aelora")["layer_1_gift"]["mechanics"]
        mechanics[{"wrong_kind": "kind", "wrong_amount": "amount", "wrong_requires": "requires"}[defect]] = "wrong"
    elif defect == "extra_mechanics":
        rows[0]["layer_1_gift"]["mechanics"] = {"kind": "skill_check_bonus", "amount": 1, "requires": "ally_present"}
    with pytest.raises(AssertionError):
        validate_gifts(rows)
