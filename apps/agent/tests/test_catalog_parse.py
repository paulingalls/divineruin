"""catalog_parse — shared content-loader parse primitives (loader-dedup chore).

These primitives were copy-pasted across five content loaders (companion_profiles,
role_archetypes, settlement_templates, npcs, mentor_variants). The shared module is
the new primitive, so it carries its own behavior test — the loaders' suites exercise
it only indirectly through their own row shapes.
"""

import pytest

import catalog_parse as cp


class TestParseStr:
    def test_returns_string(self):
        assert cp.parse_str("hello", "ctx") == "hello"

    def test_rejects_non_string(self):
        with pytest.raises(ValueError, match="ctx is not a string"):
            cp.parse_str(7, "ctx")


class TestParseInt:
    def test_returns_int(self):
        assert cp.parse_int(5, "ctx") == 5

    def test_rejects_bool(self):
        # bool is an int subclass — must be rejected (parity with the TS loader guard).
        with pytest.raises(ValueError, match="ctx is not an int"):
            cp.parse_int(True, "ctx")

    def test_rejects_non_int(self):
        with pytest.raises(ValueError, match="ctx is not an int"):
            cp.parse_int("5", "ctx")


class TestParseNumber:
    def test_int_coerced_to_float(self):
        # Canonical choice: parse_number always returns a float (companion/role behavior).
        result = cp.parse_number(3, "ctx")
        assert result == 3.0
        assert isinstance(result, float)

    def test_float_passes(self):
        assert cp.parse_number(2.5, "ctx") == 2.5

    def test_rejects_bool(self):
        with pytest.raises(ValueError, match="ctx is not a number"):
            cp.parse_number(False, "ctx")

    def test_rejects_str(self):
        with pytest.raises(ValueError, match="ctx is not a number"):
            cp.parse_number("3", "ctx")


class TestParseStrTuple:
    def test_returns_tuple(self):
        result = cp.parse_str_tuple(["a", "b"], "ctx")
        assert result == ("a", "b")
        assert isinstance(result, tuple)

    def test_rejects_non_list(self):
        with pytest.raises(ValueError, match="ctx is not a list"):
            cp.parse_str_tuple("ab", "ctx")

    def test_element_failure_carries_index(self):
        with pytest.raises(ValueError, match=r"ctx\[1\] is not a string"):
            cp.parse_str_tuple(["a", 2], "ctx")


class TestParseStrList:
    def test_returns_list(self):
        result = cp.parse_str_list(["a", "b"], "ctx")
        assert result == ["a", "b"]
        assert isinstance(result, list)

    def test_rejects_non_list(self):
        with pytest.raises(ValueError, match="ctx is not a list"):
            cp.parse_str_list("ab", "ctx")

    def test_element_failure_carries_index(self):
        with pytest.raises(ValueError, match=r"ctx\[0\] is not a string"):
            cp.parse_str_list([5], "ctx")


class TestParseDict:
    def test_returns_dict(self):
        d = {"k": "v"}
        assert cp.parse_dict(d, "ctx") == d

    def test_rejects_non_dict(self):
        with pytest.raises(ValueError, match="ctx is not an object"):
            cp.parse_dict(["not", "a", "dict"], "ctx")


class TestParseAttributes:
    def test_parses_all_six(self):
        raw = {k: i for i, k in enumerate(cp.ATTRIBUTE_KEYS)}
        assert cp.parse_attributes(raw, "ctx") == raw

    def test_rejects_non_dict(self):
        with pytest.raises(ValueError, match="ctx is not an object"):
            cp.parse_attributes("nope", "ctx")

    def test_missing_key_fails_loud(self):
        raw = {k: 1 for k in cp.ATTRIBUTE_KEYS if k != "charisma"}
        with pytest.raises(KeyError):
            cp.parse_attributes(raw, "ctx")

    def test_non_int_attribute_value_fails_loud(self):
        raw: dict[str, object] = {k: 1 for k in cp.ATTRIBUTE_KEYS}
        raw["strength"] = "high"
        with pytest.raises(ValueError, match=r"ctx\.strength is not an int"):
            cp.parse_attributes(raw, "ctx")


class TestOptHelpers:
    def test_opt_str_passthrough_none(self):
        assert cp.opt_str(None, "ctx") is None

    def test_opt_str_parses_value(self):
        assert cp.opt_str("v", "ctx") == "v"

    def test_opt_str_rejects_non_string(self):
        with pytest.raises(ValueError, match="ctx is not a string"):
            cp.opt_str(7, "ctx")

    def test_opt_int_passthrough_none(self):
        assert cp.opt_int(None, "ctx") is None

    def test_opt_int_parses_value(self):
        assert cp.opt_int(3, "ctx") == 3

    def test_opt_int_rejects_bool(self):
        with pytest.raises(ValueError, match="ctx is not an int"):
            cp.opt_int(True, "ctx")


class TestAttributeKeys:
    def test_canonical_six_in_order(self):
        assert cp.ATTRIBUTE_KEYS == (
            "strength",
            "dexterity",
            "constitution",
            "intelligence",
            "wisdom",
            "charisma",
        )
