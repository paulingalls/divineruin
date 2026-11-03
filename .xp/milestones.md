# Milestones

A user-facing goal is measured where users are.

Each Measure is one shell line run from the repository root. It prints the
remaining distance in one line: a cheap read over records or files, never a test
run.

## Run only the tests an edit could break
Goal: "set up proof for divineruin's tests so you only run the tests an edit could break" (human 2026-11-02, via the proof session).
Baseline (main fd77ddfa, 2026-11-02, host load ~20): `bun run test` 14s / 2049 tests; `test:python` 48s / 8836; `test:acceptance:nollm` 618s / 636.
Measure: python3 -c 'import json,subprocess; from pathlib import Path;  r=json.loads(subprocess.check_output(["bunx","proof","plan","--json"],text=True,stderr=subprocess.DEVNULL)); t={x["task"] for x in r}; t.update({"agent-acceptance"} if any(x.startswith("agent-acceptance:") for x in t) else set()); t.update("hook:"+n for n in ("pre-commit","pre-merge-commit","sprint") if "proof run" in (Path(".githooks")/n).read_text()); w="hook:pre-commit hook:pre-merge-commit hook:sprint bun-scripts bun-shared bun-design-tokens bun-server server-db server-locations-load server-terrain-startup server-invite-store bun-mobile bun-web agent-pytest agent-acceptance e2e".split(); m=[x for x in w if x not in t]; print("distance=%d undeclared: %s" % (len(m), " ".join(m)))'
Candidates: agent pytest task (uv sandbox venv cost); acceptance split per file; e2e Playwright; hooks call `proof run --set commit`; migrate remaining milestones from plan.md.
