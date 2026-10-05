import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from _paid_tests import APPROVAL_VAR, PAID_MARKERS

_TESTS = Path(__file__).parent


def test_a_real_run_with_keys_present_skips_a_paid_module_before_any_request():
    env = {k: v for k, v in os.environ.items() if k not in {APPROVAL_VAR, "REQUIRE_REAL_LLM"}}
    env.update(ANTHROPIC_API_KEY="fake", OPENAI_API_KEY="fake", DEEPGRAM_API_KEY="fake")
    with TemporaryDirectory(prefix="approval_probe_", dir=_TESTS) as directory:
        module = Path(directory) / "test_probe.py"
        module.write_text(
            "import pytest\n"
            + "\n".join(
                f"@pytest.mark.{marker}\ndef test_{marker}():\n    pytest.fail('paid body executed')\n"
                for marker in sorted(PAID_MARKERS)
            )
        )
        result = subprocess.run(
            [sys.executable, "-m", "pytest", str(module), "-q", "-rs", "-p", "no:cacheprovider"],
            cwd=_TESTS.parent,
            env=env,
            capture_output=True,
            text=True,
            timeout=45,
        )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "3 skipped" in result.stdout, result.stdout
    assert APPROVAL_VAR in result.stdout, result.stdout
