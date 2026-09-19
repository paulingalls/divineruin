import json
import shutil
from pathlib import Path

import pytest

from dependency_upgrade_report import validate_ci_toolchain

ROOT = Path(__file__).resolve().parents[4]


def _copy_scope(tmp_path: Path) -> Path:
    for relative in (
        ".github/workflows/ci.yml",
        ".python-version",
        "package.json",
        "docs/dependency_upgrade.json",
    ):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    return tmp_path


def _report(root: Path) -> dict:
    return json.loads((root / "docs/dependency_upgrade.json").read_text())


def test_ci_uses_declared_tools_and_all_four_frozen_locks(tmp_path):
    root = _copy_scope(tmp_path)
    validate_ci_toolchain(root, _report(root))


@pytest.mark.parametrize(
    ("original", "replacement", "diagnostic"),
    [
        ("bun-version: 1.4.2", "bun-version: 0.0.0", "setup-bun"),
        ("version: 0.10.6", "version: 0.0.0", "setup-uv"),
        ("python-version: 3.14.7", "python-version: 0.0.0", "Python"),
        ("bun install --frozen-lockfile", "bun install", "frozen Bun install"),
        ("uv sync --project apps/agent --frozen", "uv sync --project apps/agent", "frozen uv sync"),
        ("bun install --cwd e2e --frozen-lockfile", "bun install --cwd e2e", "frozen Bun install"),
        ("uv sync --project scripts --frozen", "uv sync --project scripts", "frozen uv sync"),
    ],
)
def test_ci_tool_or_lock_drift_fails(tmp_path, original, replacement, diagnostic):
    root = _copy_scope(tmp_path)
    path = root / ".github/workflows/ci.yml"
    text = path.read_text()
    assert original in text
    path.write_text(text.replace(original, replacement, 1))

    with pytest.raises(ValueError, match=diagnostic):
        validate_ci_toolchain(root, _report(root))


@pytest.mark.parametrize(
    ("original", "replacement", "diagnostic"),
    [
        (
            "- run: bun install --cwd e2e --frozen-lockfile",
            "- name: Install browser graph\n        run: bun install --cwd e2e",
            "frozen Bun install",
        ),
        (
            "- run: bun install --cwd e2e --frozen-lockfile",
            "- name: Install browser graph\n        run: |\n          bun install --cwd e2e",
            "frozen Bun install",
        ),
        (
            "- run: bun install --frozen-lockfile",
            "- name: Mixed installs\n        run: |\n          bun install --frozen-lockfile\n          bun install --cwd e2e",
            "frozen Bun install",
        ),
        (
            "- run: bun install --frozen-lockfile",
            "- run: |\n          bun install # --frozen-lockfile",
            "frozen Bun install",
        ),
        (
            "- run: bun install --frozen-lockfile",
            "- run: bun install --frozen-lockfile=false",
            "frozen Bun install",
        ),
        (
            "- run: bun install --frozen-lockfile",
            "- run: bun install --frozen-lockfile && bun install --cwd e2e",
            "frozen Bun install",
        ),
        (
            "- run: uv sync --project apps/agent --frozen",
            "- run: uv sync --project apps/agent --frozen && uv sync --project scripts",
            "frozen uv sync",
        ),
    ],
)
def test_named_and_multiline_mutable_installs_fail(tmp_path, original, replacement, diagnostic):
    root = _copy_scope(tmp_path)
    path = root / ".github/workflows/ci.yml"
    text = path.read_text()
    assert original in text
    path.write_text(text.replace(original, replacement, 1))

    with pytest.raises(ValueError, match=diagnostic):
        validate_ci_toolchain(root, _report(root))


@pytest.mark.parametrize(
    ("job_name", "consumer", "diagnostic"),
    [
        ("test-bun", "bun test e2e/require-environment.test.ts", "test-bun.*without a frozen e2e install"),
        ("lint-and-typecheck", "bun run lint:e2e", "lint-and-typecheck.*without a frozen e2e install"),
        ("test-python", "cd apps/agent && uv run pytest tests/ -q", "test-python.*without a frozen e2e install"),
    ],
)
def test_each_consumer_job_requires_its_own_e2e_install(tmp_path, job_name, consumer, diagnostic):
    root = _copy_scope(tmp_path)
    path = root / ".github/workflows/ci.yml"
    text = path.read_text()
    job_start = text.index(f"  {job_name}:")
    consumer_at = text.index(consumer, job_start)
    install = "      - run: bun install --cwd e2e --frozen-lockfile\n"
    install_at = text.rfind(install, job_start, consumer_at)
    assert install_at >= job_start
    path.write_text(text[:install_at] + text[install_at + len(install) :])

    with pytest.raises(ValueError, match=diagnostic):
        validate_ci_toolchain(root, _report(root))


@pytest.mark.parametrize(
    ("consumer", "diagnostic"),
    [
        ("      - run: bun test e2e/require-environment.test.ts\n", "e2e environment tests consumer corpus is empty"),
        ("      - run: bun run lint:e2e\n", "lint:e2e consumer corpus is empty"),
        (
            "      - run: cd apps/agent && uv run pytest tests/ -q\n",
            "Python dependency report tests consumer corpus is empty",
        ),
    ],
)
def test_consumer_walks_require_a_nonempty_floor(tmp_path, consumer, diagnostic):
    root = _copy_scope(tmp_path)
    path = root / ".github/workflows/ci.yml"
    text = path.read_text()
    assert consumer in text
    path.write_text(text.replace(consumer, "", 1))

    with pytest.raises(ValueError, match=diagnostic):
        validate_ci_toolchain(root, _report(root))


@pytest.mark.parametrize(
    ("original", "replacement", "diagnostic"),
    [
        (
            "      - run: bun run lint:e2e\n",
            '      - run: echo "bun run lint:e2e"\n',
            "lint:e2e consumer corpus is empty",
        ),
        (
            "      - run: cd apps/agent && uv run pytest tests/ -q\n",
            '      - run: echo "uv run pytest tests/ -q"\n',
            "Python dependency report tests consumer corpus is empty",
        ),
    ],
)
def test_echoed_consumers_do_not_fill_their_floor(tmp_path, original, replacement, diagnostic):
    root = _copy_scope(tmp_path)
    path = root / ".github/workflows/ci.yml"
    text = path.read_text()
    assert original in text
    path.write_text(text.replace(original, replacement, 1))

    with pytest.raises(ValueError, match=diagnostic):
        validate_ci_toolchain(root, _report(root))


def test_workflow_requires_jobs_and_job_steps(tmp_path):
    root = _copy_scope(tmp_path)
    path = root / ".github/workflows/ci.yml"
    path.write_text("name: CI\njobs: {}\n")
    with pytest.raises(ValueError, match="job corpus is empty"):
        validate_ci_toolchain(root, _report(root))

    path.write_text("name: CI\njobs:\n  empty:\n    runs-on: ubuntu-latest\n    steps: []\n")
    with pytest.raises(ValueError, match="job has no steps: empty"):
        validate_ci_toolchain(root, _report(root))


@pytest.mark.parametrize(
    ("relative", "mutate", "diagnostic"),
    [
        (".python-version", lambda text: "3.13.0\n", "repository Python"),
        ("package.json", lambda text: text.replace('"bun@1.4.2"', '"bun@0.0.0"', 1), "declared Bun"),
    ],
)
def test_repository_tool_pins_must_match_the_measured_report(tmp_path, relative, mutate, diagnostic):
    root = _copy_scope(tmp_path)
    path = root / relative
    path.write_text(mutate(path.read_text()))

    with pytest.raises(ValueError, match=diagnostic):
        validate_ci_toolchain(root, _report(root))


E2E_CONSUMER = (
    "      - run: bun install --cwd e2e --frozen-lockfile\n      - run: bun test e2e/require-environment.test.ts\n"
)


@pytest.mark.parametrize(
    ("original", "replacement", "diagnostic"),
    [
        (
            "      - run: bun install --frozen-lockfile\n      - run: bun install --cwd e2e --frozen-lockfile\n",
            "      - run: bun i\n      - run: bun install --cwd e2e --frozen-lockfile\n",
            "frozen Bun install",
        ),
        (
            E2E_CONSUMER,
            "      - run: bun install --cwd e2e --frozen-lockfile --dry-run\n"
            "      - run: bun test e2e/require-environment.test.ts\n",
            "frozen Bun install",
        ),
        (
            E2E_CONSUMER,
            '      - run: echo "bun install --cwd e2e --frozen-lockfile"\n'
            "      - run: bun test e2e/require-environment.test.ts\n",
            "without a frozen e2e install",
        ),
        (
            E2E_CONSUMER,
            "      - run: bun test e2e/require-environment.test.ts\n"
            "      - run: bun install --cwd e2e --frozen-lockfile\n",
            "without a frozen e2e install",
        ),
        (
            "      - run: bun install --cwd e2e --frozen-lockfile\n      - run: cd e2e && bunx playwright install",
            "      - run: cd e2e && bunx playwright install",
            "test-e2e.*without a frozen e2e install",
        ),
    ],
)
def test_only_a_real_preceding_frozen_install_certifies_a_graph(tmp_path, original, replacement, diagnostic):
    root = _copy_scope(tmp_path)
    path = root / ".github/workflows/ci.yml"
    text = path.read_text()
    assert original in text
    path.write_text(text.replace(original, replacement, 1))

    with pytest.raises(ValueError, match=diagnostic):
        validate_ci_toolchain(root, _report(root))


def test_playwright_consumer_walk_requires_a_nonempty_floor(tmp_path):
    root = _copy_scope(tmp_path)
    path = root / ".github/workflows/ci.yml"
    text = path.read_text()
    for consumer in (
        "      - run: cd e2e && bunx playwright install --with-deps chromium\n",
        "      - run: cd e2e && bunx playwright test\n",
    ):
        assert consumer in text
        text = text.replace(consumer, "", 1)
    path.write_text(text)

    with pytest.raises(ValueError, match="Playwright consumer corpus is empty"):
        validate_ci_toolchain(root, _report(root))
