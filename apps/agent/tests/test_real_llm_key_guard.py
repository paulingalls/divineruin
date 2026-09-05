"""The real-LLM tier must fail loud, not absent itself (sprint-47 story-019 AC1).

`5 skipped` in the pre-push gate is a false green: the only tier that reaches the
Anthropic API certified nothing. The guard is opt-in via REQUIRE_REAL_LLM so the
GitHub CI job (ci.yml runs the whole suite with no key) keeps skipping — see the
sprint-047 note on adding the secret.

WHICH MODULES MUST CARRY THE MARKER IS DECIDED BY AN IMPORT-GRAPH WALK, NOT BY THE
MODULE'S OWN TEXT. The first version of this guard grepped each acceptance module for
`anthropic.LLM|ANTHROPIC_API_KEY`, and a scenario could leave that grep clean without
trying: the `AgentSession(llm=anthropic.LLM(...), max_tool_steps=5)` block is already
duplicated verbatim in the two scenarios, so factoring it into an
`acceptance/_agent_session.py` when Sprint 48 adds the third would take the last matching
literal out of the new module's text — and a module writing
`skipif(not os.environ.get(KEY_VAR))` against this package's own `_real_llm.KEY_VAR`
matches neither literal either, while skipping on a missing key exactly as before. Both are
DETECTION evasions, so detection follows every test-side import and asks the whole
reachable set.

The REQUIREMENTS stay literal-in-the-module: `pytest.mark.real_llm` (what actually arms the
conftest fixture) and `REQUIRE_REAL_LLM` (what keeps the skipif from firing first) must
appear in the scenario's own source. Strict there is safe in the way strict detection is
not — it can only ever cost a red, never green a scenario that skips.

The walk's bound, stated rather than implied: a helper OUTSIDE apps/agent/tests could hide
the construction. Nothing production-side can be used that way today — agent.py's
`_make_agent_session` is nested inside `dm_session` and is not importable — so the edge set
below is complete against the repo as it stands, and is where to extend it if that changes.
"""

import ast
from pathlib import Path

import pytest
from acceptance._real_llm import KEY_VAR, require_real_llm_key

_TESTS_DIR = Path(__file__).parent
_ACCEPTANCE_DIR = _TESTS_DIR / "acceptance"


def _resolve(base: Path, dotted: str) -> Path | None:
    """A dotted module name as a file under `base`, or None when it is not test-side."""
    if not dotted:
        return None
    parts = dotted.split(".")
    for candidate in (base.joinpath(*parts[:-1], f"{parts[-1]}.py"), base.joinpath(*parts, "__init__.py")):
        if candidate.is_file():
            return candidate
    return None


def _test_side_imports(tree: ast.AST, module: Path, tests_root: Path) -> set[Path]:
    """Every module under `tests_root` that `module` imports, however it spells the import."""
    found: set[Path] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            candidates = [(tests_root, alias.name) for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            # `from . import x` / `from ._x import y` resolve against the module's own package.
            base = module.parents[node.level - 1] if node.level else tests_root
            prefix = f"{node.module}." if node.module else ""
            # Both spellings: `from acceptance import _real_llm` and `from acceptance._real_llm import KEY_VAR`.
            candidates = [(base, node.module or ""), *((base, f"{prefix}{a.name}") for a in node.names)]
        else:
            continue
        found.update(p for p in (_resolve(base, dotted) for base, dotted in candidates) if p is not None)
    return found


def _touches_anthropic(tree: ast.AST) -> bool:
    """Does this one module import the Anthropic plugin or name its key?"""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any("anthropic" in alias.name.split(".") for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            if "anthropic" in (node.module or "").split(".") or any(a.name == "anthropic" for a in node.names):
                return True
        elif isinstance(node, ast.Constant) and node.value == KEY_VAR:
            return True
    return False


def reaches_the_real_llm_tier(module: Path, tests_root: Path) -> bool:
    """Does `module`, or any test-side module it imports at any depth, reach the API?

    Over-flagging is the safe direction here and is deliberate: a helper that merely
    mentions the key makes every importer declare itself, which costs a red. Under-flagging
    is what puts a silent skip back in the pre-push gate.
    """
    seen: set[Path] = set()
    queue = [module]
    while queue:
        current = queue.pop()
        if current in seen:
            continue
        seen.add(current)
        tree = ast.parse(current.read_text())
        if _touches_anthropic(tree):
            return True
        queue.extend(_test_side_imports(tree, current, tests_root) - seen)
    return False


def _real_llm_modules() -> list[Path]:
    return [p for p in sorted(_ACCEPTANCE_DIR.rglob("test_*.py")) if reaches_the_real_llm_tier(p, _TESTS_DIR)]


def test_absent_opt_in_stays_silent():
    """No REQUIRE_REAL_LLM — CI's path. Today's skip is preserved, not converted to a failure."""
    require_real_llm_key({})
    require_real_llm_key({"ANTHROPIC_API_KEY": "sk-ant-real"})


def test_opt_in_without_a_key_raises_naming_the_var():
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        require_real_llm_key({"REQUIRE_REAL_LLM": "1"})


def test_opt_in_with_an_empty_key_raises():
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        require_real_llm_key({"REQUIRE_REAL_LLM": "1", "ANTHROPIC_API_KEY": ""})


def test_opt_in_with_the_env_example_placeholder_raises():
    """Every teammate worktree's .env carries .env.example's truthy `your-anthropic-api-key`.
    skipif does not fire on it, so without this branch the scenarios boot Docker and then 401."""
    with pytest.raises(RuntimeError, match="placeholder"):
        require_real_llm_key({"REQUIRE_REAL_LLM": "1", "ANTHROPIC_API_KEY": "your-anthropic-api-key"})


def test_opt_in_with_a_real_key_passes():
    require_real_llm_key({"REQUIRE_REAL_LLM": "1", "ANTHROPIC_API_KEY": "sk-ant-real"})


def test_every_real_llm_scenario_is_wired_into_the_guard():
    """The gate is only as good as the two marks a module has to carry BY HAND: the `real_llm`
    marker the conftest fixture keys on, and a skipif that knows about REQUIRE_REAL_LLM. A new
    scenario that carries neither skips exactly as before and the false green is back — and
    Sprint 48 owes a combat scenario, so this is a change that is already scheduled.
    """
    modules = _real_llm_modules()
    assert modules, "no acceptance module reaches the Anthropic API — the walk went vacuous"
    for path in modules:
        source = path.read_text()
        assert "pytest.mark.real_llm" in source, f"{path.name} reaches the API but carries no real_llm marker"
        assert "REQUIRE_REAL_LLM" in source, (
            f"{path.name}'s skipif does not know about REQUIRE_REAL_LLM — it would fire first and "
            "keep the silence the marker is there to break"
        )


def _write(root: Path, relative: str, source: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source)
    return path


class TestReachesTheRealLlmTier:
    """The detector, against the shapes a scenario can actually take.

    Every case here is a module whose OWN text the retired grep read as clean; the two
    middle ones are the evasions that made the grep worth replacing.
    """

    def test_a_module_that_touches_nothing_is_not_flagged(self, tmp_path):
        _write(tmp_path, "acceptance/seeds.py", "def seed_player():\n    pass\n")
        module = _write(
            tmp_path,
            "acceptance/test_plain.py",
            "import json\n\nfrom acceptance.seeds import seed_player\n\nimport db\n",
        )
        assert reaches_the_real_llm_tier(module, tmp_path) is False

    def test_direct_construction_is_flagged(self, tmp_path):
        module = _write(
            tmp_path,
            "acceptance/test_direct.py",
            "from livekit.plugins import anthropic\n\nllm = anthropic.LLM(model='m')\n",
        )
        assert reaches_the_real_llm_tier(module, tmp_path) is True

    def test_construction_behind_a_shared_helper_is_flagged(self, tmp_path):
        """The `_agent_session.py` factoring: the scenario's own text names neither literal."""
        _write(
            tmp_path,
            "acceptance/_agent_session.py",
            "from livekit.plugins import anthropic\n\n"
            "def make_session(model):\n    return anthropic.LLM(model=model)\n",
        )
        module = _write(
            tmp_path,
            "acceptance/test_helper.py",
            "from acceptance._agent_session import make_session\n\n"
            "def test_turn():\n    assert make_session('haiku')\n",
        )
        assert reaches_the_real_llm_tier(module, tmp_path) is True

    def test_a_skipif_on_the_packages_own_key_var_is_flagged(self, tmp_path):
        """The cheapest evasion of all — it reuses story-019's own helper to name the key."""
        _write(tmp_path, "acceptance/_real_llm.py", 'KEY_VAR = "ANTHROPIC_API_KEY"\n')
        module = _write(
            tmp_path,
            "acceptance/test_key_var.py",
            "import os\n\nimport pytest\nfrom acceptance._real_llm import KEY_VAR\n\n"
            "pytestmark = pytest.mark.skipif(not os.environ.get(KEY_VAR), reason='no key')\n",
        )
        assert reaches_the_real_llm_tier(module, tmp_path) is True

    def test_a_relative_import_two_hops_away_is_flagged(self, tmp_path):
        """Depth and spelling are both routes: `from . import x` resolves against the package."""
        _write(tmp_path, "acceptance/_deep.py", "import anthropic\n")
        _write(tmp_path, "acceptance/_middle.py", "from . import _deep\n")
        module = _write(tmp_path, "acceptance/test_deep.py", "from acceptance import _middle\n")
        assert reaches_the_real_llm_tier(module, tmp_path) is True

    def test_a_production_import_is_not_followed(self, tmp_path):
        """The stated bound. `import db` leaves tests/, so the walk stops — it does not silently
        chase the whole first-party graph, where importing `dispatch_agent` would flag every
        capstone that never builds a session."""
        module = _write(tmp_path, "acceptance/test_prod.py", "import db\nimport dispatch_agent\n")
        assert reaches_the_real_llm_tier(module, tmp_path) is False

    def test_an_import_cycle_terminates(self, tmp_path):
        _write(tmp_path, "acceptance/_a.py", "from acceptance import _b\n")
        _write(tmp_path, "acceptance/_b.py", "from acceptance import _a\n")
        module = _write(tmp_path, "acceptance/test_cycle.py", "from acceptance import _a\n")
        assert reaches_the_real_llm_tier(module, tmp_path) is False
