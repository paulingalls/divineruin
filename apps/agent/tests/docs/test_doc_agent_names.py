"""Live documentation names classes defined in the agent application."""

import ast
import os
import re
from pathlib import Path

import pytest

from combat_agent import COMBAT_AGENT_TOOLS

ROOT = Path(__file__).resolve().parents[4]
DOCS = ROOT / "docs"
AGENT = ROOT / "apps/agent"
EXCLUDED = (Path("decisions"), Path("milestones/audit"))
RETIRED = {
    "CityAgent": "ExplorationAgent",
    "WildernessAgent": "ExplorationAgent",
    "DungeonAgent": "ExplorationAgent",
    "DungeonMasterAgent": "ExplorationAgent",
}
NAME = re.compile(r"(?<!\w)([A-Za-z_][A-Za-z0-9_]*Agent)\b")


def live_names(source=AGENT):
    names = set()
    for directory, dirs, files in os.walk(source):
        dirs[:] = [part for part in dirs if part not in {".venv", "venv", "__pycache__", ".tox"}]
        for file in files:
            if file.endswith(".py"):
                path = Path(directory) / file
                tree = ast.parse(path.read_text(), filename=str(path))
                names.update(
                    node.name
                    for node in ast.walk(tree)
                    if isinstance(node, ast.ClassDef) and node.name.endswith("Agent")
                )
    return names


def doc_paths(directory=DOCS):
    return sorted(
        path
        for path in directory.rglob("*.md")
        if not any(path.relative_to(directory).is_relative_to(part) for part in EXCLUDED)
    )


def scan_docs(directory, live, docs=None):
    docs = doc_paths(directory) if docs is None else docs
    assert docs, f"no docs under {directory}"
    mentions = 0
    errors = []
    for path in docs:
        for number, line in enumerate(path.read_text().splitlines(), 1):
            found = set(NAME.findall(line)) - {"Agent"}
            mentions += len(found & live)
            for name in sorted(found):
                if name in RETIRED and RETIRED[name] not in found:
                    errors.append(f"{path}:{number}: {name}: missing replacement {RETIRED[name]}")
                elif name not in live | RETIRED.keys():
                    errors.append(f"{path}:{number}: {name}: no class definition")
    assert mentions, f"zero live-agent mentions under {directory}\n" + "\n".join(errors)
    return errors


def test_doc_agent_names():
    live = live_names()
    assert "BaseGameAgent" in live
    assert "CityAgent" in RETIRED
    assert not live & RETIRED.keys()
    assert set(RETIRED.values()) <= live
    errors = scan_docs(DOCS, live)
    assert not errors, "\n".join(errors)


def test_bad_agent_lines_red_with_location(tmp_path):
    path = tmp_path / "bad.md"
    path.write_text(
        "CityAgent handles shops\nMarketAgent opens stalls\nunknownAgent appears\nExplorationAgent explores\n"
    )
    errors = scan_docs(tmp_path, live_names())
    assert f"{path}:1: CityAgent: missing replacement ExplorationAgent" in errors
    assert f"{path}:2: MarketAgent: no class definition" in errors
    assert f"{path}:3: unknownAgent: no class definition" in errors


def test_empty_corpus_and_zero_live_mentions_red(tmp_path):
    with pytest.raises(AssertionError, match="no docs"):
        scan_docs(tmp_path, live_names())
    (tmp_path / "empty.md").write_text("Nothing here\n")
    with pytest.raises(AssertionError, match="zero live-agent mentions"):
        scan_docs(tmp_path, live_names())


def test_renamed_live_class_reds_doc(tmp_path):
    source = tmp_path / "agent"
    source.mkdir()
    (source / "exploration.py").write_text("class RenamedAgent:\n    pass\n")
    docs = tmp_path / "docs"
    docs.mkdir()
    path = docs / "current.md"
    path.write_text("ExplorationAgent explores\nRenamedAgent exists\n")
    assert f"{path}:1: ExplorationAgent: no class definition" in scan_docs(docs, live_names(source))


def test_doc_walk_excludes_only_decisions_and_audit(tmp_path):
    for relative in ("live.md", "nested/live.md", "decisions/old.md", "milestones/audit/old.md"):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("ExplorationAgent\n")
    assert [p.relative_to(tmp_path).as_posix() for p in doc_paths(tmp_path)] == ["live.md", "nested/live.md"]


def test_combat_agent_tools_match_doc():
    page = (DOCS / "agent_handoffs_and_scenes.md").read_text()
    section = page.split("### CombatAgent\n", 1)[1].split("\n### ", 1)[0]
    listing = section.split("- **Tools:**", 1)[1].split("\n- **", 1)[0]
    names = re.findall(r"`([a-z][a-z0-9_]*)`", listing)
    assert names and len(names) == len(set(names))
    assert names == [tool.__name__ for tool in COMBAT_AGENT_TOOLS]
