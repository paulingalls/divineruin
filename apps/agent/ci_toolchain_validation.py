import json
import re
import shlex
import subprocess
from pathlib import Path


def _workflow_jobs(path: Path) -> dict[str, dict]:
    script = (
        "const workflow = Bun.YAML.parse(await Bun.file(process.argv[1]).text());"
        "console.log(JSON.stringify(workflow.jobs));"
    )
    result = subprocess.run(
        ["bun", "-e", script, str(path)],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise ValueError(f"Bun could not parse CI workflow: {result.stderr.strip()}")
    try:
        jobs = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise ValueError("Bun returned invalid JSON for CI workflow jobs") from error
    if not isinstance(jobs, dict) or not jobs:
        raise ValueError("CI workflow job corpus is empty")
    return jobs


CONTINUATION_RE = re.compile(r"\\\n")


def _shell_commands(run: str) -> list[str]:
    commands = []
    for line in CONTINUATION_RE.sub(" ", run).splitlines():
        lexer = shlex.shlex(line, posix=True, punctuation_chars=";&|")
        lexer.whitespace_split = True
        command: list[str] = []
        for token in lexer:
            if token and set(token) <= set(";&|"):
                if command:
                    commands.append(shlex.join(command))
                    command = []
            else:
                command.append(token)
        if command:
            commands.append(shlex.join(command))
    return commands


def _job_runs(job_name: str, job: dict) -> list[str]:
    steps = job.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ValueError(f"CI job has no steps: {job_name}")
    return [
        command
        for step in steps
        if isinstance(step, dict) and isinstance(step.get("run"), str)
        for command in _shell_commands(step["run"])
    ]


# `bun i` is Bun's own alias for `bun install`, so a guard that only recognises
# the long form waves through a mutable install.
BUN_INSTALL_SUBCOMMANDS = frozenset({"install", "i"})


def _flag_value(tokens: list[str], flag: str) -> str | None:
    if flag not in tokens:
        return None
    index = tokens.index(flag) + 1
    return tokens[index] if index < len(tokens) else None


def _subcommand_tokens(command: str, program: str, subcommands: frozenset[str]) -> list[str] | None:
    tokens = shlex.split(command)
    if len(tokens) < 2 or tokens[0] != program or tokens[1] not in subcommands:
        return None
    return tokens


def _is_frozen_bun_install(command: str) -> bool:
    tokens = _subcommand_tokens(command, "bun", BUN_INSTALL_SUBCOMMANDS)
    # --dry-run resolves the lock and writes no node_modules, so it installs nothing.
    return tokens is not None and "--frozen-lockfile" in tokens and "--dry-run" not in tokens


def _is_frozen_root_install(command: str) -> bool:
    return _is_frozen_bun_install(command) and _flag_value(shlex.split(command), "--cwd") is None


def _is_frozen_e2e_install(command: str) -> bool:
    return _is_frozen_bun_install(command) and _flag_value(shlex.split(command), "--cwd") == "e2e"


def _is_frozen_uv_sync(command: str, project: str) -> bool:
    tokens = _subcommand_tokens(command, "uv", frozenset({"sync"}))
    return tokens is not None and "--frozen" in tokens and _flag_value(tokens, "--project") == project


def _runs_playwright(command: str) -> bool:
    return shlex.split(command)[:2] == ["bunx", "playwright"]


def _runs_python_report_tests(command: str) -> bool:
    return bool(re.search(r"\bpytest\b", command)) and (
        "dependency_upgrade" in command or bool(re.search(r"(?:^|\s)tests/(?:\s|$)", command))
    )


def validate_ci_toolchain(root: Path, report: dict) -> None:
    workflow = root / ".github/workflows/ci.yml"
    if not workflow.is_file():
        raise ValueError("missing workflow: .github/workflows/ci.yml")
    package_manager = json.loads((root / "package.json").read_text()).get("packageManager", "")
    if not package_manager.startswith("bun@"):
        raise ValueError("packageManager must declare an exact Bun version")
    expected_bun = package_manager.removeprefix("bun@")
    expected_python = (root / ".python-version").read_text().strip()
    expected_uv = report["uv_version"]
    if expected_python != report["python_version"]:
        raise ValueError(f"repository Python {expected_python} differs from recorded Python {report['python_version']}")
    if expected_bun != report["bun_version"]:
        raise ValueError(f"declared Bun {expected_bun} differs from recorded Bun {report['bun_version']}")
    jobs = _workflow_jobs(workflow)
    runs_by_job = {name: _job_runs(name, job) for name, job in jobs.items()}
    steps = [step for job in jobs.values() for step in job.get("steps", []) if isinstance(step, dict)]
    bun_setups = [step for step in steps if str(step.get("uses", "")).startswith("oven-sh/setup-bun@")]
    uv_setups = [step for step in steps if str(step.get("uses", "")).startswith("astral-sh/setup-uv@")]
    if not bun_setups or any(str(step.get("with", {}).get("bun-version")) != expected_bun for step in bun_setups):
        raise ValueError(f"every CI setup-bun step must select {expected_bun}")
    if not uv_setups or any(str(step.get("with", {}).get("version")) != expected_uv for step in uv_setups):
        raise ValueError(f"every CI setup-uv step must select {expected_uv}")
    if any(str(step.get("with", {}).get("python-version")) != expected_python for step in uv_setups):
        raise ValueError(f"every CI setup-uv step must select Python {expected_python}")

    runs = [command for commands in runs_by_job.values() for command in commands]
    bun_installs = [command for command in runs if _subcommand_tokens(command, "bun", BUN_INSTALL_SUBCOMMANDS)]
    uv_syncs = [command for command in runs if _subcommand_tokens(command, "uv", frozenset({"sync"}))]
    if not bun_installs or not all(_is_frozen_bun_install(command) for command in bun_installs):
        raise ValueError("every CI Bun install must be a frozen Bun install that actually installs")
    if not uv_syncs or any("--frozen" not in shlex.split(command) for command in uv_syncs):
        raise ValueError("every CI uv sync must be a frozen uv sync")
    required = {
        "root Bun": _is_frozen_root_install,
        "e2e Bun": _is_frozen_e2e_install,
        "agent uv": lambda command: _is_frozen_uv_sync(command, "apps/agent"),
        "scripts uv": lambda command: _is_frozen_uv_sync(command, "scripts"),
    }
    for graph, matches in required.items():
        if not any(matches(command) for command in runs):
            raise ValueError(f"CI does not install the {graph} lock")

    consumers = (
        ("e2e environment tests", lambda c: shlex.split(c) == ["bun", "test", "e2e/require-environment.test.ts"]),
        ("lint:e2e", lambda c: "bun run lint:e2e" in c),
        ("Playwright", _runs_playwright),
        ("Python dependency report tests", _runs_python_report_tests),
    )
    for consumer, matches in consumers:
        consuming_jobs = 0
        for job_name, commands in runs_by_job.items():
            reached = next((index for index, command in enumerate(commands) if matches(command)), None)
            if reached is None:
                continue
            consuming_jobs += 1
            # Only an install the job runs BEFORE the consumer has populated e2e/node_modules.
            if not any(_is_frozen_e2e_install(command) for command in commands[:reached]):
                raise ValueError(f"CI job {job_name} runs {consumer} without a frozen e2e install")
        if not consuming_jobs:
            raise ValueError(f"CI {consumer} consumer corpus is empty")
