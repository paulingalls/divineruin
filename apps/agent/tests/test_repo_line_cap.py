import re
import subprocess
import tokenize
from io import StringIO
from pathlib import Path

REPO_ROOT = Path(__file__).parents[3]
SOURCE_ROOTS = ("apps", "packages", "e2e", "scripts")
SOURCE_SUFFIXES = frozenset({".py", ".ts", ".tsx"})
MAX_LINES = 500


def _code_files():
    # Tracked files only: tests write transient modules under apps/ (test_paid_test_gate), and a
    # parallel walk that lists one can read it after it is deleted (bug fd71c364).
    files = []
    for source_root in SOURCE_ROOTS:
        listed = subprocess.run(
            ["git", "ls-files", "-z", "--", source_root], cwd=REPO_ROOT, check=True, capture_output=True, text=True
        ).stdout
        found = [REPO_ROOT / name for name in listed.split("\0") if Path(name).suffix in SOURCE_SUFFIXES]
        files.extend(found)
    return sorted(files)


def test_code_files_stay_within_hard_cap():
    lengths = {path.relative_to(REPO_ROOT).as_posix(): len(path.read_text().splitlines()) for path in _code_files()}

    assert {path: count for path, count in lengths.items() if count > MAX_LINES} == {}


def _has_format_off(source: str) -> bool:
    return any(
        token.type == tokenize.COMMENT and re.search(r"#\s*fmt\s*:\s*off\b", token.string)
        for token in tokenize.generate_tokens(StringIO(source).readline)
    )


def test_no_python_file_disables_the_formatter_at_module_level():
    """The cap counts formatted lines: a module-level formatter disable hid a 670-line test."""
    python_files = [path for path in _code_files() if path.suffix == ".py"]
    offenders = [path.relative_to(REPO_ROOT).as_posix() for path in python_files if _has_format_off(path.read_text())]

    assert offenders == []
