"""Regenerate the human-readable documentation catalog from docs/**/*.md."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

ENTRY = re.compile(r"^## ([\w./-]+\.md)(?: \([^\n]*\))?$", re.M)
ROW = re.compile(r"^\| (.*?) \| (.*?) \| (.*?) \|$", re.M)
LIST_DIRS = {"decisions", "ideas", "milestones", "mockups"}
HEADER = """# Documentation Index

Run `uv run python scripts/doc_index.py --write` after editing docs. The test compares
this file with the regenerated result. Scope: every regular `docs/**/*.md` file,
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
    result = render(docs, current)
    if args.write:
        index_file.write_text(result)
    elif result != current:
        raise SystemExit("docs/INDEX.md differs; run --write")


if __name__ == "__main__":
    main()
