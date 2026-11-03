# Milestones

A user-facing goal is measured where users are.

Each Measure is one shell line run from the repository root. It prints the
remaining distance in one line: a cheap read over records or files, never a test
run.

## Run only the tests an edit could break
Goal: "set up proof for divineruin's tests so you only run the tests an edit could break" (human 2026-11-02, via the proof session).
Baseline (main fd77ddfa, 2026-11-02, host load ~20): `bun run test` 14s / 2049 tests; `test:python` 48s / 8836; `test:acceptance:nollm` 618s / 636.
Measure: python3 -c 'import os,re; y=open("proof.yaml").read() if os.path.exists("proof.yaml") else ""; b=re.search(r"^tasks:\n(.*?)(?=^\S|\Z)",y,re.M|re.S); t=set(re.findall(r"^  ([\w:-]+):$",b.group(1) if b else "",re.M)); w="bun-scripts bun-shared bun-design-tokens bun-server server-db server-locations-load server-terrain-startup server-invite-store bun-mobile bun-web agent-pytest agent-acceptance e2e".split(); m=[x for x in w if x not in t]; print("distance=%d undeclared: %s" % (len(m), " ".join(m)))'
Candidates: agent pytest task (uv sandbox venv cost); acceptance split per file; e2e Playwright; hooks call `proof run --set commit`; migrate remaining milestones from plan.md.
