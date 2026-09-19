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


def _has_frozen_e2e_install(commands: list[str]) -> bool:
    return any("bun install --cwd e2e --frozen-lockfile" in command for command in commands)


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
    bun_installs = [command for command in runs if shlex.split(command)[:2] == ["bun", "install"]]
    uv_syncs = [command for command in runs if shlex.split(command)[:2] == ["uv", "sync"]]
    if not bun_installs or any("--frozen-lockfile" not in shlex.split(command) for command in bun_installs):
        raise ValueError("every CI Bun install must be a frozen Bun install")
    if not uv_syncs or any("--frozen" not in shlex.split(command) for command in uv_syncs):
        raise ValueError("every CI uv sync must be a frozen uv sync")
    required = {
        "root Bun": lambda command: command.startswith("bun install --frozen-lockfile"),
        "e2e Bun": lambda command: "bun install --cwd e2e --frozen-lockfile" in command,
        "agent uv": lambda command: "uv sync --project apps/agent --frozen" in command,
        "scripts uv": lambda command: "uv sync --project scripts --frozen" in command,
    }
    for graph, matches in required.items():
        if not any(matches(command) for command in runs):
            raise ValueError(f"CI does not install the {graph} lock")

    consumers = {
        "e2e environment tests": [
            name
            for name, commands in runs_by_job.items()
            if any(shlex.split(run) == ["bun", "test", "e2e/require-environment.test.ts"] for run in commands)
        ],
        "lint:e2e": [
            name for name, commands in runs_by_job.items() if any("bun run lint:e2e" in run for run in commands)
        ],
        "Python dependency report tests": [
            name for name, commands in runs_by_job.items() if any(_runs_python_report_tests(run) for run in commands)
        ],
    }
    for consumer, job_names in consumers.items():
        if not job_names:
            raise ValueError(f"CI {consumer} consumer corpus is empty")
        for job_name in job_names:
            if not _has_frozen_e2e_install(runs_by_job[job_name]):
                raise ValueError(f"CI job {job_name} runs {consumer} without a frozen e2e install")
