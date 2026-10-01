"""AST-based absence walk, including every non-generated Python/TypeScript corpus."""

import ast
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PRIVATE = {"_validate_enemy_action_shapes", "_validate_enemy_resistance_tags"}
EXCLUDED = {"node_modules", ".venv", "__pycache__", "dist", ".next", ".expo", ".git", ".pytest_cache", ".ruff_cache"}
LANES = {
    ("agent", "py", False),
    ("agent", "py", True),
    ("apps", "ts", False),
    ("apps", "ts", True),
    ("apps", "tsx", False),
    ("apps", "tsx", True),
    ("shared", "ts", False),
    ("shared", "ts", True),
    ("packages", "ts", False),
    ("packages", "ts", True),
    ("scripts", "py", False),
    ("scripts", "ts", False),
    ("scripts", "ts", True),
    ("e2e", "ts", True),
}


def source_files(root):
    files = []
    for directory, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if d not in EXCLUDED and not (Path(directory) / d / "pyvenv.cfg").is_file()]
        files.extend(Path(directory) / name for name in names if Path(name).suffix in {".py", ".ts", ".tsx"})
    return files


def lane(path):
    relative = path.relative_to(ROOT)
    parts = relative.parts
    assert parts[0] in {"apps", "packages", "scripts", "e2e"}, relative
    corpus = parts[0]
    if parts[:2] == ("apps", "agent"):
        corpus = "agent"
    elif parts[:3] == ("packages", "shared", "src"):
        corpus = "shared"
    test = (
        parts[0] == "e2e"
        or "tests" in parts
        or "__tests__" in parts
        or path.name.startswith("test_")
        or ".test." in path.name
        or ".spec." in path.name
    )
    return corpus, path.suffix[1:], test


def assert_corpora(files, root=ROOT):
    for path in ("apps/agent", "apps", "packages/shared/src", "packages", "scripts", "e2e"):
        assert (root / path).is_dir(), path
    assert files
    lanes = {key: [] for key in LANES}
    for path in files:
        key = lane(path)
        assert key in lanes, (path, key)
        lanes[key].append(path)
    assert all(lanes.values()), {key: len(paths) for key, paths in lanes.items()}
    return lanes


def assert_public_python(text, path):
    for node in ast.walk(ast.parse(text, filename=str(path))):
        if isinstance(node, ast.Name):
            assert node.id not in PRIVATE, path
        elif isinstance(node, ast.Attribute):
            assert node.attr not in PRIVATE, path
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert node.name not in PRIVATE, path
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                assert not PRIVATE.intersection(alias.name.split(".")), path
                assert alias.asname not in PRIVATE, path
                if isinstance(node, ast.ImportFrom) and node.module in {"combat_init", "combat_init_validation"}:
                    assert alias.name != "*", path


TS_IDENTIFIERS = """
import ts from "typescript";
let input = "";
for await (const chunk of Bun.stdin.stream()) input += new TextDecoder().decode(chunk);
const invalid = [];
for (const [path, text] of JSON.parse(input)) {
  const file = ts.createSourceFile(path, text, ts.ScriptTarget.Latest, true,
    path.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
  function visit(node) {
    if (ts.isIdentifier(node) && ["_validate_enemy_action_shapes", "_validate_enemy_resistance_tags"].includes(node.text)) invalid.push(path);
    ts.forEachChild(node, visit);
  }
  visit(file);
}
process.stdout.write(JSON.stringify(invalid));
"""


def assert_public_typescript(sources):
    assert sources
    result = subprocess.run(
        ["bun", "-e", TS_IDENTIFIERS], input=json.dumps(sources), text=True, capture_output=True, cwd=ROOT, check=True
    )
    assert json.loads(result.stdout) == [], result.stdout


def assert_public_validator_walk(files):
    assert_corpora(files)
    for path in files:
        if path.suffix == ".py":
            assert_public_python(path.read_text(), path)
    assert_public_typescript([(str(path), path.read_text()) for path in files if path.suffix in {".ts", ".tsx"}])
