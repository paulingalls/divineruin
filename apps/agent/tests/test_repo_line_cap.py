import os
from pathlib import Path

REPO_ROOT = Path(__file__).parents[3]
SOURCE_ROOTS = ("apps", "packages", "e2e", "scripts")
SOURCE_SUFFIXES = frozenset({".py", ".ts", ".tsx"})
MAX_LINES = 500
SKIPPED_DIRECTORY_NAMES = {
    "node_modules": "installed third-party dependencies",
    ".venv": "installed Python dependencies",
    "out": "generated build output",
    "dist": "generated distribution output",
    "coverage": "generated test coverage output",
    ".expo": "generated Expo metadata and types",
}
SKIPPED_DIRECTORY_PATHS = {
    "scripts/audio/.venv-sa3": "gitignored generated SFX Python environment",
}


def _code_files():
    files = []
    for source_root in SOURCE_ROOTS:
        found = []
        for directory, child_directories, filenames in os.walk(REPO_ROOT / source_root):
            directory_path = Path(directory)
            child_directories[:] = [
                name
                for name in child_directories
                if name not in SKIPPED_DIRECTORY_NAMES
                and (directory_path / name).relative_to(REPO_ROOT).as_posix() not in SKIPPED_DIRECTORY_PATHS
            ]
            found.extend(
                directory_path / filename for filename in filenames if Path(filename).suffix in SOURCE_SUFFIXES
            )
        assert found, (
            f"no code files under {REPO_ROOT / source_root} — os.walk yields nothing for a missing "
            "directory, so a wrong REPO_ROOT or a renamed source root leaves the cap green over an "
            "empty walk"
        )
        files.extend(found)
    return sorted(files)


def test_code_files_stay_within_hard_cap():
    lengths = {path.relative_to(REPO_ROOT).as_posix(): len(path.read_text().splitlines()) for path in _code_files()}

    assert {path: count for path, count in lengths.items() if count > MAX_LINES} == {}


def test_no_python_file_disables_the_formatter_at_module_level():
    """The cap counts formatted lines: a module-level `# fmt: off` let a 670-line test sit at 422."""
    python_files = [path for path in _code_files() if path.suffix == ".py"]
    assert python_files
    offenders = [
        path.relative_to(REPO_ROOT).as_posix()
        for path in python_files
        if any(line.startswith("# fmt: off") for line in path.read_text().splitlines())
    ]

    assert offenders == []


def test_line_cap_policy_is_exactly_the_recorded_code_boundary():
    assert SOURCE_ROOTS == ("apps", "packages", "e2e", "scripts")
    assert frozenset({".py", ".ts", ".tsx"}) == SOURCE_SUFFIXES
    assert MAX_LINES == 500
    assert SKIPPED_DIRECTORY_NAMES == {
        "node_modules": "installed third-party dependencies",
        ".venv": "installed Python dependencies",
        "out": "generated build output",
        "dist": "generated distribution output",
        "coverage": "generated test coverage output",
        ".expo": "generated Expo metadata and types",
    }
    assert SKIPPED_DIRECTORY_PATHS == {
        "scripts/audio/.venv-sa3": "gitignored generated SFX Python environment",
    }
