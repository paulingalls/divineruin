"""Falsifiers for the strict-schema walker, one per defect class Anthropic 400s on.

Each synthetic schema below is a live 400 per ADR 0008: >16 union-typed parameters,
`additionalProperties` on an object, `null` inside an `enum`, or `oneOf`. The walker
is what lets test_strict_tool_budget.py name the offending path instead of pinning a
hand-counted number that Sprint 48's reshapes would immediately falsify.
"""

from tool_schema_walk import walk_tool_schema


def _nullable(t: str = "string") -> dict:
    return {"type": [t, "null"]}


def _obj(props: dict, **extra) -> dict:
    return {"type": "object", "properties": props, **extra}


def test_flat_nullables_each_count_as_one_union():
    schema = _obj({f"p{i}": _nullable() for i in range(17)})
    facts = walk_tool_schema(schema)
    assert len(facts.unions) == 17
    assert facts.nullable_by_object["$"] == 17


def test_nullables_nested_in_an_object_property_still_count():
    schema = _obj({"params": _obj({"a": _nullable(), "b": _nullable()})})
    facts = walk_tool_schema(schema)
    assert len(facts.unions) == 2
    assert facts.nullable_by_object["$.params"] == 2


def test_nullables_inside_array_items_still_count():
    schema = _obj({"rows": {"type": "array", "items": _obj({"a": _nullable()})}})
    facts = walk_tool_schema(schema)
    assert len(facts.unions) == 1


def test_an_anyof_of_seventeen_variants_costs_one_union():
    """ADR 0008's whole mechanism: the same information as 17 optionals, at 1/17th the budget."""
    defs = {f"V{i}": _obj({"kind": {"const": f"k{i}"}, "value": {"type": "string"}}) for i in range(17)}
    schema = {
        "type": "object",
        "$defs": defs,
        "properties": {"payload": {"anyOf": [{"$ref": f"#/$defs/V{i}"} for i in range(17)]}},
    }
    facts = walk_tool_schema(schema)
    assert facts.unions == ["$.payload"]


def test_an_anyof_inside_array_items_still_costs_its_union():
    """The shape a `list[SumType]` parameter emits: the anyOf sits under `items`, not on
    the property. A walker that only inspects property nodes reports ZERO unions for it —
    and under-counting is the one direction this walk must not err in."""
    defs = {f"V{i}": _obj({"kind": {"const": f"k{i}"}}) for i in range(3)}
    schema = {
        "type": "object",
        "$defs": defs,
        "properties": {"rows": {"type": "array", "items": {"anyOf": [{"$ref": f"#/$defs/V{i}"} for i in range(3)]}}},
    }
    facts = walk_tool_schema(schema)
    assert facts.unions == ["$.rows.items"]


def test_nested_additional_properties_is_found():
    """Today's declare_phase emits it one level down, not on the parameter itself."""
    schema = _obj({"declarations": {"type": "object", "additionalProperties": {"type": "object"}}})
    facts = walk_tool_schema(schema)
    assert facts.additional_properties == ["$.declarations"]


def test_additional_properties_inside_a_ref_variant_is_found():
    """A walker that stops at $ref reports a clean schema the API rejects. Refs ARE traversed
    for additionalProperties/enum-null/oneOf, so the walk must resolve them."""
    schema = {
        "type": "object",
        "$defs": {"V": _obj({"bag": {"type": "object", "additionalProperties": True}})},
        "properties": {"payload": {"anyOf": [{"$ref": "#/$defs/V"}]}},
    }
    facts = walk_tool_schema(schema)
    assert facts.additional_properties == ["$.payload.anyOf[0].bag"]


def test_additional_properties_false_is_not_a_finding():
    schema = _obj({"a": {"type": "string"}}, additionalProperties=False)
    assert walk_tool_schema(schema).additional_properties == []


def test_enum_containing_null_is_found():
    schema = _obj({"mode": {"enum": ["a", None]}})
    assert walk_tool_schema(schema).enum_with_null == ["$.mode"]


def test_one_of_is_found():
    schema = _obj({"p": {"oneOf": [{"type": "string"}, {"type": "integer"}]}})
    facts = walk_tool_schema(schema)
    assert facts.one_of == ["$.p"]
    assert facts.unions == ["$.p"]


def test_nullables_are_counted_per_containing_object():
    schema = _obj({**{f"p{i}": _nullable() for i in range(14)}, "inner": _obj({"q": _nullable()})})
    facts = walk_tool_schema(schema)
    assert max(facts.nullable_by_object.values()) == 14


def test_a_self_referential_def_terminates():
    schema = {
        "type": "object",
        "$defs": {"Node": _obj({"child": {"$ref": "#/$defs/Node"}, "a": _nullable()})},
        "properties": {"root": {"$ref": "#/$defs/Node"}},
    }
    facts = walk_tool_schema(schema)
    assert len(facts.unions) == 1
