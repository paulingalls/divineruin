from collections import Counter

from _gods_content import load_gods

EXPECTED_GIFTS = {
    "veythar": ("short_rest", "awaits_rest"),
    "kaelen": ("per_encounter", "active"),
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
EXPECTED_MECHANICS = {
    "aelora": {"kind": "skill_check_bonus", "amount": 1, "requires": "ally_present"},
    "kaelen": {"kind": "low_hp_surge", "threshold": 0.25, "amount": 2, "duration_phases": 2},
}
MECHANICS_KINDS = {mechanics["kind"] for mechanics in EXPECTED_MECHANICS.values()}


def validate_gifts(rows):
    ids = [row["god_id"] for row in rows]
    assert set(ids) == set(EXPECTED_GIFTS)
    assert all(count == 1 for count in Counter(ids).values())
    gift_ids = []
    for row in rows:
        assert "layer_1_gift" in row, row["god_id"]
        gift = row["layer_1_gift"]
        assert isinstance(gift, dict), row["god_id"]
        expected_fields = GIFT_FIELDS | ({"mechanics"} if row["god_id"] in EXPECTED_MECHANICS else set())
        assert set(gift) == expected_fields, row["god_id"]
        assert all(isinstance(gift[field], str) and gift[field].strip() for field in GIFT_FIELDS), row["god_id"]
        if row["god_id"] in EXPECTED_MECHANICS:
            assert gift["mechanics"] == EXPECTED_MECHANICS[row["god_id"]]
        assert (gift["recharge"], gift["status"]) == EXPECTED_GIFTS[row["god_id"]]
        gift_ids.append(gift["id"])
    assert len(gift_ids) == len(set(gift_ids))


def test_every_patron_has_authored_layer_1_gift():
    validate_gifts(load_gods())
