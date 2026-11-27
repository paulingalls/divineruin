"""Check or regenerate the documentation index and milestone counts."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

ENTRY = re.compile(r"^## ([\w./-]+\.md)(?: \([^\n]*\))?$", re.MULTILINE)
ROW = re.compile(r"^\| (.*?) \| (.*?) \| (.*?) \|$", re.MULTILINE)
LIST_DIRS = {"decisions", "ideas", "milestones", "mockups"}
HEADER = """# Documentation Index

Run `python3 scripts/doc_index.py --write` after editing docs. The commit hook
runs `python3 scripts/doc_index.py` to validate the index and milestone counts.
The index covers every regular `docs/**/*.md` file,
including nested directories; `docs/INDEX.md` is explicitly excluded. Non-Markdown
assets and source files are excluded. `decisions/`, `ideas/`, `milestones/` and
`mockups/` are listed by path and line count only; every other doc gets a section
table. A doc in a new top-level directory fails generation until it is given a group.
Detailed tables use `##` headings, or `###` headings when a document has one wrapping
`##`. Ranges are inclusive. Empty descriptions in detailed entries need a human summary.

Start with `product_overview.md` for the vision, `game_design_doc.md` for player
systems, and `milestones/README.md` for the implementation dependency graph.
"""


def discover(docs: Path) -> list[Path]:
    if not docs.is_dir():
        raise ValueError(f"missing docs directory: {docs}")
    paths = sorted(p for p in docs.rglob("*.md") if p.is_file() and p != docs / "INDEX.md")
    if not paths:
        raise ValueError("no documentation files found")
    return paths


def headings(path: Path) -> tuple[list[tuple[int, str]], list[tuple[int, str]]]:
    h2, h3 = [], []
    fence = None
    for number, line in enumerate(path.read_text().splitlines(), 1):
        match = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if match:
            marker = match.group(1)
            if fence is None:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence):
                fence = None
            continue
        if fence:
            continue
        match = re.match(r"^\s{0,3}(#{2,3})\s+(.+?)\s*#*\s*$", line)
        if match:
            (h2 if len(match.group(1)) == 2 else h3).append((number, match.group(2)))
    return h2, h3


def sections(path: Path) -> list[tuple[str, int, int]]:
    h2, h3 = headings(path)
    chosen = h3 if len(h2) == 1 and h3 else h2
    ends = h2 if chosen is h3 else []
    last = len(path.read_text().splitlines())
    result = []
    seen = set()
    for i, (start, title) in enumerate(chosen):
        if title in seen:
            raise ValueError(f"duplicate section title in {path}: {title}")
        seen.add(title)
        next_lines = [chosen[i + 1][0]] if i + 1 < len(chosen) else []
        next_lines += [line for line, _ in ends if line > start]
        result.append((title, start, min(next_lines) - 1 if next_lines else last))
    return result


def parse_authored(index: str) -> dict[str, tuple[str, dict[str, str]]]:
    entries = {}
    matches = list(ENTRY.finditer(index))
    for i, match in enumerate(matches):
        path = match.group(1)
        if path in entries:
            raise ValueError(f"duplicate index entry: {path}")
        body = index[match.end() : matches[i + 1].start() if i + 1 < len(matches) else len(index)]
        body = re.split(r"\n(?:---|# [^\n]+)\n", body, maxsplit=1)[0]
        prose = body.split("| Section | Lines | What's There |", 1)[0].strip()
        rows = {}
        for line in body.splitlines():
            if line.startswith("|") and not ROW.fullmatch(line) and line != "|---|---|---|":
                raise ValueError(f"malformed index row in {path}: {line}")
        for title, _range, description in ROW.findall(body):
            if title in {"Section", "---"}:
                continue
            title = title.replace("\\|", "|")
            if title in rows:
                raise ValueError(f"duplicate index section in {path}: {title}")
            rows[title] = description
        entries[path] = (prose, rows)
    return entries


def is_detail(relative: str) -> bool:
    return relative.split("/")[0] not in LIST_DIRS


def render(docs: Path, index: str) -> str:
    files = discover(docs)
    authored = parse_authored(index)
    paths = {p.relative_to(docs).as_posix() for p in files}
    missing = set(authored) - paths
    if missing:
        raise ValueError(f"missing doc for index entry: {', '.join(sorted(missing))}")
    groups = [
        ("Core design", lambda p: "/" not in p),
        ("Game mechanics", lambda p: p.startswith("game_mechanics/")),
        ("Prompts", lambda p: p.startswith("prompts/")),
        ("Operations", lambda p: p.startswith("ops/")),
        ("Decisions", lambda p: p.startswith("decisions/")),
        ("Milestones and audits", lambda p: p.startswith("milestones/")),
        ("Ideas", lambda p: p.startswith("ideas/")),
        ("Mockup notes", lambda p: p.startswith("mockups/")),
    ]
    ungrouped = [p for p in sorted(paths) if not any(predicate(p) for _, predicate in groups)]
    if ungrouped:
        raise ValueError(f"no index group for: {', '.join(ungrouped)}")
    output = [HEADER.rstrip(), ""]
    for group, predicate in groups:
        members = [p for p in files if predicate(p.relative_to(docs).as_posix())]
        if not members:
            continue
        output += [f"# {group}", ""]
        for path in members:
            rel = path.relative_to(docs).as_posix()
            prose, descriptions = authored.get(rel, ("", {}))
            output += [f"## {rel} ({len(path.read_text().splitlines())} lines)", ""]
            if prose:
                output += [prose, ""]
            if is_detail(rel):
                parts = sections(path)
                if parts:
                    output += ["| Section | Lines | What's There |", "|---|---|---|"]
                    for title, first, last in parts:
                        cell = title.replace("|", r"\|")
                        output.append(f"| {cell} | {first}-{last} | {descriptions.get(title, '')} |")
                    output.append("")
            output += ["---", ""]
    return "\n".join(output).rstrip() + "\n"


def validate_descriptions(index: str) -> None:
    for path, (prose, rows) in parse_authored(index).items():
        if is_detail(path) and not prose:
            raise ValueError(f"empty description for {path}")
        if is_detail(path):
            for title, description in rows.items():
                if not description.strip():
                    raise ValueError(f"empty description for {path}: {title}")


def phase_rows(source: str, heading: str, pattern: str) -> dict[int, re.Match[str]]:
    """Find the phase rows within one section, keeping their source offsets."""
    section = re.compile(rf"^## {re.escape(heading)}\n.*?(?=^## |\Z)", re.MULTILINE | re.DOTALL)
    sections = list(section.finditer(source))
    if len(sections) != 1:
        raise ValueError(f"expected one {heading} section, found {len(sections)}")
    row_pattern = re.compile(pattern)
    rows = {}
    for row in re.compile(r"^\|(?! Phase \||---\|)[^\n]+$", re.MULTILINE).finditer(source, *sections[0].span()):
        match = row_pattern.match(source, row.start(), row.end())
        if match is None or int(match["phase"]) in rows:
            raise ValueError(f"{heading}: malformed or duplicate phase row: {row[0]}")
        rows[int(match["phase"])] = match
    if not rows:
        raise ValueError(f"{heading}: no phase rows")
    return rows


def field_edit(
    source: str,
    pattern: str,
    field: str,
    expected: str,
) -> tuple[int, int, str, str]:
    matches = list(re.finditer(pattern, source, re.MULTILINE))
    if len(matches) != 1:
        raise ValueError(f"{field}: expected one field, found {len(matches)}")
    return value_edit(matches[0], field, expected)


def value_edit(match: re.Match[str], field: str, expected: str) -> tuple[int, int, str, str]:
    start, end = match.span("value")
    return start, end, expected, f"{field}: {match['value']!r} → {expected!r}"


def milestone_updates(docs: Path) -> tuple[dict[Path, str], list[str]]:
    readme_file = docs / "milestones/README.md"
    remaining_file = docs / "milestones/REMAINING.md"
    readme = readme_file.read_text()
    remaining = remaining_file.read_text()
    link = r"\[[^\]\n]+\]\((?P<file>\w[\w.-]*\.md)\)"
    inventory = phase_rows(readme, "Phase Files", rf"\| (?P<phase>\d+) \| {link} \| ")
    delivered = phase_rows(
        readme,
        "Phase Completion Status",
        rf"\| (?P<phase>\d+) · [^|]+ \| {link} \| [^|]+ \| (?P<value>[^|]*) \| ",
    )
    if set(inventory) != set(delivered):
        raise ValueError("README.md: phase numbers in Phase Files and Phase Completion Status differ")
    if len({row["file"] for row in inventory.values()}) != len(inventory):
        raise ValueError("README.md: duplicate phase file in Phase Files")

    counts = {}
    readme_edits = []
    for phase, row in inventory.items():
        if row["file"] != delivered[phase]["file"]:
            raise ValueError(f"README.md: Phase {phase} file differs between the phase tables")
        criteria = re.findall(
            r"^[ \t]*- \[([x ])\](?=[ \t]|$)",
            (readme_file.parent / row["file"]).read_text(),
            re.MULTILINE,
        )
        checked = criteria.count("x")
        counts[phase] = (checked, len(criteria))
        readme_edits.append(
            value_edit(
                delivered[phase],
                f"Phase {phase} Delivered",
                f"{checked}/{len(criteria)} ACs",
            )
        )
    checked = sum(done for done, _ in counts.values())
    total = sum(count for _, count in counts.values())
    if not total:
        raise ValueError("README.md: no acceptance criteria in the phase files")

    open_rows = phase_rows(
        remaining,
        "5. Incomplete implementation phases",
        r"\| \*\*(?P<phase>\d+) · [^|]+ \| [^|]+ \| (?P<value>[^|]*) \| ",
    )
    remaining_edits = []
    table_total = 0
    for phase, row in open_rows.items():
        if phase not in counts:
            raise ValueError(f"REMAINING.md: Phase {phase} is missing from README.md Phase Files")
        done, count = counts[phase]
        open_count = count - done
        table_total += open_count
        remaining_edits.append(value_edit(row, f"§5 Phase {phase} Open ACs", str(open_count)))
    fields = [
        (
            r"^\*\*Position: (?P<value>[^\n]+?)\*\*",
            "Position",
            f"{checked} / {total} acceptance criteria — {checked * 100 // total}%",
        ),
        (
            r"\*\*(?P<value>[^*\n]+) criteria remain unchecked\.\*\*",
            "unchecked count",
            str(total - checked),
        ),
        (
            r"^The table sums to (?P<value>[^\n]+?) open criteria are",
            "§5 table sum and other open count",
            f"{table_total}. The other {total - checked - table_total}",
        ),
    ]
    for pattern, field, expected in fields:
        remaining_edits.append(field_edit(remaining, pattern, field, expected))

    updates = {}
    differences = []
    for path, source, edits in [
        (readme_file, readme, readme_edits),
        (remaining_file, remaining, remaining_edits),
    ]:
        for start, end, expected, description in sorted(edits, reverse=True):
            if source[start:end] != expected:
                source = source[:start] + expected + source[end:]
                differences.append(f"docs/milestones/{path.name} {description}")
        updates[path] = source
    return updates, differences


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", action="store_true")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    docs = Path(__file__).resolve().parents[1] / "docs"
    if args.inventory:
        for path in discover(docs):
            print(f"{path.relative_to(docs)}\t{len(path.read_text().splitlines())}")
        return
    index_file = docs / "INDEX.md"
    current = index_file.read_text()
    try:
        updates, differences = milestone_updates(docs)
        result = render(docs, current)
    except (OSError, ValueError) as error:
        raise SystemExit(str(error)) from None
    # Milestone summary replacements preserve line counts, so the index can be rendered before writing.
    if args.write:
        for path, source in updates.items():
            path.write_text(source)
        index_file.write_text(result)
        return
    if result != current:
        differences.append("docs/INDEX.md differs")
    if differences:
        raise SystemExit("\n".join([*differences, "Run python3 scripts/doc_index.py --write"]))


if __name__ == "__main__":
    main()
