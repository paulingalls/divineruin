"""Walk an emitted strict tool schema and report every shape Anthropic 400s on.

A hand-counted pin ("dispatch has 5 unions") goes stale the moment a story reshapes a
verb; a walk over the schema the plugin actually emits stays true. Findings carry the
JSON path to the offender so a failure names it.

Deliberately STRICTER than the API on one axis: Anthropic does not resolve `$ref`
before counting unions/nullables, so a pin here can red on a schema the API accepts
today. That is the point (ADR 0008 "Watch") — the day refs are resolved before
counting, every agent 400s at once, and this is the only thing that would have been
red first. Do not "fix" it by skipping refs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SchemaFacts:
    """Every strict-schema finding in one tool's input schema, each keyed by JSON path."""

    unions: list[str] = field(default_factory=list)
    nullable_by_object: dict[str, int] = field(default_factory=dict)
    additional_properties: list[str] = field(default_factory=list)
    enum_with_null: list[str] = field(default_factory=list)
    one_of: list[str] = field(default_factory=list)


def _is_union(node: dict) -> bool:
    return "anyOf" in node or "oneOf" in node or isinstance(node.get("type"), list)


def _is_nullable(node: dict) -> bool:
    return isinstance(node.get("type"), list) and "null" in node["type"]


def walk_tool_schema(input_schema: dict[str, Any]) -> SchemaFacts:
    """Collect union / nullable / additionalProperties / enum-null / oneOf findings."""
    facts = SchemaFacts()
    defs = input_schema.get("$defs", {})
    _walk(input_schema, "$", facts, defs, visited=frozenset())
    return facts


def _walk(node: Any, path: str, facts: SchemaFacts, defs: dict, visited: frozenset[str]) -> None:
    if not isinstance(node, dict):
        return

    ref = node.get("$ref")
    if isinstance(ref, str):
        if ref in visited:
            return
        name = ref.rsplit("/", 1)[-1]
        target = defs.get(name)
        if target is not None:
            _walk(target, path, facts, defs, visited | {ref})
        return

    if "oneOf" in node:
        facts.one_of.append(path)
    enum = node.get("enum")
    if isinstance(enum, list) and any(v is None for v in enum):
        facts.enum_with_null.append(path)
    extra = node.get("additionalProperties")
    if extra is not None and extra is not False:
        facts.additional_properties.append(path)

    for key in ("anyOf", "oneOf"):
        for i, branch in enumerate(node.get(key, []) or []):
            _walk(branch, f"{path}.{key}[{i}]", facts, defs, visited)

    properties = node.get("properties")
    if isinstance(properties, dict):
        nullable_here = 0
        for prop, sub in properties.items():
            sub_path = f"{path}.{prop}"
            if isinstance(sub, dict):
                if _is_union(sub):
                    facts.unions.append(sub_path)
                if _is_nullable(sub):
                    nullable_here += 1
            _walk(sub, sub_path, facts, defs, visited)
        facts.nullable_by_object[path] = nullable_here

    _walk(node.get("items"), f"{path}.items", facts, defs, visited)
