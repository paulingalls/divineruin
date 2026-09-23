"""Design docs must describe the registered DM surface accurately."""

import re
from pathlib import Path

import pytest
from _doc_non_tools import NON_TOOLS
from _retired_tools import NEVER_BUILT_TOOLS, RETIRED_TOOL_REPLACEMENTS
from agent_tool_profiles import AGENT_TOOL_LISTS

DOCS = Path(__file__).resolve().parents[4] / "docs"
EXCLUDED = (Path("decisions"), Path("milestones/audit"))
BACKTICK = re.compile(r"`([a-z][a-z0-9_]*(?:\([^`]*\))?)`")
COMMENTS = re.compile(r"<!--.*?-->")
TOOL_CONTEXT = re.compile(r"\b(?:agent|DM) tools?\b|\btool surface\b|@function_tool", re.I)

# Agent tools that unbuilt phases (07-09) still specify. ADR 0007 folds them into verbs
# when those phases are planned; until then they are design intent, not DM surface.
PLANNED_TOOLS = frozenset(
    {
        "activate_patron_ability",
        "check_patron_tier",
        "query_patron_synergy",
        "query_creatures_by_region",
        "query_creature_by_id",
        "resolve_harvesting",
        "generate_encounter",
        "get_merchant_price",
        "resolve_combat_loot",
        "grant_reputation",
        "check_faction_service_available",
        "query_merchant_inventory",
        "purchase_item",
        "sell_item",
        "consign_item",
        "consume_item",
    }
)


def live_names():
    return {tool.__name__ for _, tools in AGENT_TOOL_LISTS for tool in tools}


def segments(line):
    visible = COMMENTS.sub("", line)
    return [visible, *COMMENTS.findall(line)]


def candidates(segment):
    for match in BACKTICK.finditer(segment):
        raw = match.group(1)
        name = raw.split("(", 1)[0]
        if (
            "(" in raw
            or name in RETIRED_TOOL_REPLACEMENTS
            or name in NEVER_BUILT_TOOLS
            or ("_" in name and TOOL_CONTEXT.search(segment))
        ):
            yield name


def violations(path, number, line, live):
    for segment in segments(line):
        tokens = set(candidates(segment))
        for name in tokens:
            reason = None
            if name in NEVER_BUILT_TOOLS:
                reason = "never built as a DM tool"
            elif name in RETIRED_TOOL_REPLACEMENTS:
                replacement = RETIRED_TOOL_REPLACEMENTS[name]
                if replacement is None:
                    outside = BACKTICK.sub("", segment)
                    if not re.search(r"\b(?:retired|removed|deleted|Resolve)\b", outside, re.I):
                        reason = "retired without a retirement or Resolve explanation"
                elif replacement not in live:
                    reason = f"replacement {replacement} is not registered"
                elif replacement not in {m.group(1).split("(", 1)[0] for m in BACKTICK.finditer(segment)}:
                    reason = f"retired without replacement `{replacement}` on this line"
            elif name not in live | NON_TOOLS | PLANNED_TOOLS:
                reason = "unclassified tool-shaped name"
            if reason:
                yield f"{path}:{number}: {name}: {reason}"


def doc_paths(directory, excluded=EXCLUDED):
    return sorted(
        path
        for path in directory.rglob("*.md")
        if not any(path.relative_to(directory).is_relative_to(part) for part in excluded)
    )


def require_corpus(directory, docs, excluded=EXCLUDED, minimum=61):
    assert set(excluded) == {Path("decisions"), Path("milestones/audit")}, "exemption widened"
    expected = {
        path
        for path in directory.rglob("*.md")
        if not (
            path.relative_to(directory).is_relative_to("decisions")
            or path.relative_to(directory).is_relative_to("milestones/audit")
        )
    }
    assert len(expected) >= minimum, "docs corpus shrank"
    assert set(docs) == expected, "docs walk omitted or included a path"


def scan_docs(directory, live, docs=None):
    docs = doc_paths(directory) if docs is None else docs
    assert docs, f"no docs under {directory}"
    return [
        error
        for path in docs
        for number, line in enumerate(path.read_text().splitlines(), 1)
        for error in violations(path, number, line, live)
    ]


def require_floor(selected, live):
    assert selected & live, "no registered tool names selected from docs"
    assert selected & RETIRED_TOOL_REPLACEMENTS.keys(), "no retired-name mentions selected from docs"


def test_milestone_tool_names():
    live = live_names()
    assert len(RETIRED_TOOL_REPLACEMENTS) == 31
    assert not RETIRED_TOOL_REPLACEMENTS.keys() & live
    assert not NEVER_BUILT_TOOLS & live
    assert all(replacement in live for replacement in RETIRED_TOOL_REPLACEMENTS.values() if replacement)
    assert not (NON_TOOLS | PLANNED_TOOLS) & (live | RETIRED_TOOL_REPLACEMENTS.keys() | NEVER_BUILT_TOOLS)
    docs = doc_paths(DOCS)
    require_corpus(DOCS, docs)
    selected = {
        name
        for path in docs
        for line in path.read_text().splitlines()
        for segment in segments(line)
        for name in candidates(segment)
    }
    require_floor(selected, live)
    errors = scan_docs(DOCS, live, docs)
    assert not errors, "\n".join(errors)


@pytest.mark.parametrize(
    "line",
    [
        "Agent tool `learn_recipe`",
        "Agent tool `request_skill_check`",
        "Agent tool `activate_veil_ward`",
        "Agent tool `roll_dice` for a skill check",
        "`award_xp` agent tool <!-- `award_xp` deleted; Resolve -->",
        "Agent tool `request_parley`",
        "Agent tool `request_save`",
    ],
)
def test_bad_tool_line_reds(line):
    assert list(violations("fixture.md", 7, line, live_names()))


def test_empty_doc_walk_reds(tmp_path):
    with pytest.raises(AssertionError, match="no docs"):
        scan_docs(tmp_path, live_names())


def test_corpus_includes_nested_docs_and_exempts_only_allowed_subtrees(tmp_path):
    nested = tmp_path / "game_mechanics" / "nested.md"
    nested.parent.mkdir()
    nested.write_text("`check`\n")
    for name in ("decisions/old.md", "milestones/audit/old.md"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("Agent tool `request_attack`\n")
    docs = doc_paths(tmp_path)
    require_corpus(tmp_path, docs, minimum=1)
    assert docs == [nested]
    assert not scan_docs(tmp_path, live_names())
    with pytest.raises(AssertionError, match="omitted"):
        require_corpus(tmp_path, [], minimum=1)
    for excluded in ((Path("."), Path("milestones/audit")), (Path("decisions"), Path("milestones"))):
        with pytest.raises(AssertionError, match="exemption widened"):
            require_corpus(tmp_path, doc_paths(tmp_path, excluded), excluded, minimum=1)


def test_corpus_floor_reds_when_docs_disappear(tmp_path):
    with pytest.raises(AssertionError, match="corpus shrank"):
        require_corpus(tmp_path, [], minimum=1)


def test_walk_floor_reds_without_retired_or_live_names():
    live = live_names()
    require_floor({"learn_recipe", "learn"}, live)
    with pytest.raises(AssertionError, match="no retired-name mentions"):
        require_floor({"learn"}, live)
    with pytest.raises(AssertionError, match="no registered tool names"):
        require_floor({"learn_recipe"}, live)


def test_dropped_map_name_reds(monkeypatch):
    monkeypatch.delitem(RETIRED_TOOL_REPLACEMENTS, "learn_recipe")
    assert "unclassified" in " ".join(violations("fixture.md", 4, "Agent tool `learn_recipe`", live_names()))


def test_unregistered_replacement_reds(monkeypatch):
    monkeypatch.setitem(RETIRED_TOOL_REPLACEMENTS, "learn_recipe", "invented_verb")
    assert "not registered" in " ".join(violations("fixture.md", 4, "`learn_recipe`", live_names()))


def test_injected_doc_lines_red_with_location(tmp_path):
    path = tmp_path / "05_crafting.md"
    path.write_text("Agent tool `learn_recipe`\nAgent tool `request_parley`\n")
    errors = scan_docs(tmp_path, live_names())
    assert any("05_crafting.md:1: learn_recipe" in error for error in errors)
    assert any("05_crafting.md:2: request_parley" in error for error in errors)


@pytest.mark.parametrize(
    "name",
    [
        "query_training_programs",
        "query_recipe_requirements",
        "query_available_workspaces",
    ],
)
def test_retired_lookups_use_query_info(name):
    assert RETIRED_TOOL_REPLACEMENTS[name] == "query_info"
