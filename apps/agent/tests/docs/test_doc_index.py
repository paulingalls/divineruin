import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
SPEC = importlib.util.spec_from_file_location("doc_index", ROOT / "scripts" / "doc_index.py")
assert SPEC is not None and SPEC.loader is not None
doc_index = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(doc_index)
discover = doc_index.discover
render = doc_index.render
sections = doc_index.sections
validate_descriptions = doc_index.validate_descriptions


def test_committed_index_matches_docs():
    docs = ROOT / "docs"
    current = (docs / "INDEX.md").read_text()
    assert current == render(docs, current)
    validate_descriptions(current)


def test_scope_is_nonempty_and_excludes_index():
    paths = [p.relative_to(ROOT / "docs").as_posix() for p in discover(ROOT / "docs")]
    assert paths
    assert "INDEX.md" not in paths
    assert len(paths) == len(set(paths))
    assert {"game_mechanics", "prompts", "ops", "decisions", "milestones", "ideas", "mockups"} <= {
        p.split("/")[0] for p in paths
    }


def test_ranges_are_inclusive_and_ignore_fenced_headings(tmp_path):
    doc = tmp_path / "sample.md"
    doc.write_text("# Sample\n## Alpha\na\n```md\n## Fake\n```\n## Beta\nb")
    assert sections(doc) == [("Alpha", 2, 6), ("Beta", 7, 8)]
    doc.write_text("# Sample\n## Wrapper\n### One\na\n### Two\nb")
    assert sections(doc) == [("One", 3, 4), ("Two", 5, 6)]


def test_regeneration_preserves_authored_prose_and_exposes_new_sections(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    doc = docs / "sample.md"
    doc.write_text("# Sample\n## Alpha\na\n## Beta\nb\n")
    authored = "## sample.md (5 lines)\n\nA blurb.\n\n| Section | Lines | What's There |\n|---|---|---|\n| Alpha | 2-3 | First description |\n| Beta | 4-5 | Second description |\n"
    doc.write_text(doc.read_text() + "extra\n## Gamma\nlast\n")
    output = render(docs, authored)
    assert "A blurb." in output
    assert "First description" in output
    assert "Second description" in output
    assert "| Gamma | 7-8 |  |" in output
    with pytest.raises(ValueError, match="empty description"):
        validate_descriptions(output)


def test_inventory_mutations_change_render(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    doc = docs / "sample.md"
    doc.write_text("## Alpha\na\n")
    (docs / "other.md").write_text("# Other\n")
    original = render(docs, "")
    doc.write_text(doc.read_text() + "new line\n")
    assert render(docs, original) != original
    doc.unlink()
    with pytest.raises(ValueError, match="missing doc"):
        render(docs, original)
    doc.write_text("## Alpha\na\n")
    (docs / "new.md").write_text("# New\n")
    assert render(docs, original) != original


def test_removed_section_drops_stale_row_and_self_entry_fails(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    doc = docs / "sample.md"
    doc.write_text("## Alpha\na\n## Beta\nb\n")
    original = render(docs, "")
    doc.write_text("## Alpha\na\n")
    assert "| Beta |" not in render(docs, original)
    with pytest.raises(ValueError, match="missing doc"):
        render(docs, original + "\n## INDEX.md (1 lines)\n")


def test_duplicate_index_entry_fails(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "sample.md").write_text("## Alpha\na\n")
    original = render(docs, "")
    with pytest.raises(ValueError, match="duplicate index entry"):
        render(docs, original + "\n## sample.md (2 lines)\n")


def test_malformed_authored_row_fails(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "sample.md").write_text("## Alpha\na\n")
    original = render(docs, "")
    malformed = original.replace("| Alpha | 1-2 |  |", "| Alpha | 1-2 | authored")
    with pytest.raises(ValueError, match="malformed index row"):
        render(docs, malformed)
