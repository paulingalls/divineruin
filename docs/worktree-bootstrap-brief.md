# Brief: provisioning divineruin worktrees (`stack.worktree_bootstrap`)

**Audience:** whoever (human or agent) sets this up in divineruin.
**Status:** measured 2026-07-16 from outside this repo. Every claim below names the command that
produced it and the exit code observed. Where something was not measured, it says so.
**Source:** `xp-agents` spike-005 (`docs/spikes/005-worktree-bootstrap-provisioning.md` in that repo).

---

## 1. What this is for

The xp-agents plugin can run a project-declared setup command inside a freshly created teammate
worktree. The project declares it once, as a single string:

```
system_context.json → stack.worktree_bootstrap
```

`git worktree add` materializes only **tracked** files, so everything gitignored — `node_modules`,
`.venv`, generated types, local env — is missing. Without a declared command, every teammate
worktree in this repo starts broken.

**This repo currently declares nothing.** Its SMM is
`~/.claude/plugins/data/xp-agents-xp-agents/cf77350916c2/smm`, and `stack.worktree_bootstrap` is
unset.

---

## 2. What is already true here — read this before writing anything

Three things already exist. Do not reinvent them.

### 2.1 The pre-commit hook already gives up in worktrees

`.githooks/pre-commit` (reached via `core.hooksPath=.githooks`):

> "A fresh git worktree — a teammate checkout — has no node_modules, which previously forced
> `git commit --no-verify`. Skip the suite there with a clear notice instead."

So this repo **already hit** the bare-worktree problem and chose to **degrade**: skip the lint
suite rather than block. That is a legitimate choice, and it has a consequence worth knowing —
**a teammate committing in a divineruin worktree currently gets no lint enforcement from this
repo's own hook.**

**Recommendation: change nothing in the hook. The skip is already self-clearing.** The guard is

```bash
if [ ! -d node_modules ]; then ... exit 0; fi
```

which keys on `node_modules` **absence**, not on "is this a worktree." Provision the worktree and
the guard is simply false — the suite runs, and commit-time lint enforcement comes back on its own.
That is good design and needs no edit.

**Measured, because the obvious worry turns out to be wrong.** `node_modules` is a *proxy* for
"deps installed", while the suite's last step is `bun run lint:python` =
`cd apps/agent && uv run ruff check . && uv run ruff format --check . && uv run pyright` — the uv
side. So a `bun install`-only bootstrap looks like it would re-arm the guard and then fail on
Python, leaving the teammate blocked again — *worse* than not provisioning at all. **It does not.**
In a worktree with `bun install` run and `apps/agent/.venv` **absent**, `bun run lint:python`
exits **0 in 8s**: `uv run` self-bootstraps its environment on first use. There is no
partial-bootstrap trap here.

**And note what this decouples.** The hook's suite has **no database step** (verified: zero
references to `ensure-db`/docker/`DATABASE_URL` in `.githooks/pre-commit`). So §3.3's container
problem does **not** gate the hook. Restoring commit-time lint in worktrees costs only
`bun install` — you can have that today, without resolving §4's DB decision at all. The DB
decision is only needed for the *declared test command* (`bun run test:all`). Two different bars;
don't let the harder one hold up the cheaper one.

A caveat the hook itself raises: its skip notice justifies degrading by saying "the pre-push gate
(run from a deps-installed checkout) re-runs the full typecheck + tests, so nothing reaches a
shared branch unchecked." Once worktrees are provisioned, that fallback stops being load-bearing at
commit time — which is the point.

### 2.2 This repo already knows how to isolate containers per run

`scripts/test-env.sh`:

```bash
_te_id="divineruin-test-$$"                                  # PID-keyed
docker run -d --name "${_te_id}-pg" -p 127.0.0.1:0:5432 ...  # ephemeral port
docker run -d --name "${_te_id}-redis" -p 127.0.0.1:0:6379 ...
```

PID-keyed names and port `0` (kernel-assigned). `scripts/sweep-test-containers.sh` reaps orphans
from killed runs. **This is the pattern that solves §3.3 — it already lives in this repo.**

### 2.3 `ensure-db.ts` reuses a reachable database

`scripts/ensure-db.ts:76` — `if (await isReachable(host, port)) return false;` — it only runs
`docker compose up` when nothing answers at `DATABASE_URL`'s host:port. So a worktree *can* simply
use the primary's already-running stack. See §4 for why that is a real decision, not a free win.

---

## 3. The measured blockers

Baseline: in the **primary** checkout, `bun run test:all` → **exit 0** (all suites pass, including
`cd apps/agent && uv run pytest`).

### 3.1 `node_modules` — the easy half

Bare worktree → `bun run typecheck` fails (TS2307 etc.). After `bun install` (exit 0, 1871
packages) → **typecheck exits 0**. Closed.

### 3.2 `.venv` — `bun install` does not touch it

`apps/agent` is a **uv** project (`apps/agent/pyproject.toml`; `stack.package_manager` is recorded
as "Bun workspaces + uv (apps/agent)"). In the bare worktree after `bun install`, `apps/agent/.venv`
is **ABSENT** — `uv sync` never ran. The declared gate `bun run test:all` ends with
`cd apps/agent && uv run pytest`, so this half must be provisioned too.

> This is the single most important finding: **`bun install` alone is NOT the answer.** Measured —
> after `bun install`, `bun run test:all` still exits **1**. A one-line `bun install` declaration
> would look right and leave the real gate broken.

### 3.3 Docker container names are global — the design problem

`docker-compose.yml` sets explicit names:

```yaml
postgres:  container_name: divineruin-postgres   ports: ["127.0.0.1:55432:5432"]
valkey:    container_name: divineruin-valkey     ports: ["127.0.0.1:56379:6379"]
```

An explicit `container_name:` **defeats compose's per-project namespacing.** A worktree is a
different directory → a different compose project → compose tries to *create* containers → and the
hardcoded global names collide with the primary's:

```
Error response from daemon: Conflict. The container name "/divineruin-valkey"
is already in use by container "54fd90e43fa8...".
```

Measured, and note the sharp edge: the primary's containers were **stopped** (`Exited (0)`) at the
time. **A stopped container still holds its name.** So this collides whether or not the primary's
stack is running. The host ports (55432/56379) are fixed for the same reason and collide the same
way if two stacks ever run at once.

---

## 4. The decision you have to make (deliberately not made for you)

Two viable designs. Both are defensible; they differ in isolation vs cost.

**A. Share the primary's stack.** Bootstrap = `bun install` + `uv sync`, and let `ensure-db.ts`
find the primary's DB reachable at `127.0.0.1:55432` (§2.3) and reuse it.
- *Cheap.* No compose changes, no new containers.
- *Cost:* every worktree's tests mutate **one shared database**. Two teammates running suites
  concurrently share state. Requires the primary's stack to be up, so bootstrap alone doesn't
  guarantee a green gate. Whether the suites are safe under a shared DB is **UNMEASURED** — if they
  truncate/seed tables, they will interfere.

**B. Per-worktree stack.** Reuse §2.2's pattern: derive an id from the checkout (as `test-env.sh`
does from `$$`), and give each worktree its own containers + ephemeral ports.
- *Isolated.* No cross-checkout interference; matches what `test-env.sh` already proved works here.
- *Cost:* needs `container_name:` removed or parameterized in compose (or a worktree-specific
  compose overlay), and `DATABASE_URL` threaded per worktree. Real work.

The reference implementation for B's shape is `../legacy/scripts/init-worktree.sh` — it solves the
same class of problem with a reserved port band, a `worktree_name_collides` guard, and a
process-group reap. Worth reading before choosing.

---

## 5. What to write

A single idempotent entry point — `scripts/init-worktree.sh` is the conventional name and is what
xp-agents' analyzer looks for. It must, at minimum:

1. `bun install`
2. `uv sync` in `apps/agent` (§3.2)
3. Whatever §4's decision implies for the database.
4. Be **idempotent** — re-running on a warm checkout must be a safe no-op or a safe regenerate.
5. **Fail loud.** A half-provisioned worktree must never host an agent. The runner
   (`worktree_bootstrap.run_bootstrap`) already treats non-zero as fatal: no agent starts and the
   worktree is left standing for inspection.

Then declare it (≤100 chars, runs with `shell=True`, cwd = the new worktree):

```bash
printf %s '"bash scripts/init-worktree.sh"' | python3 \
  ~/.claude/plugins/cache/xp-agents/xp-agents/4.12.0/smm/system_context_cli.py \
  --smm-dir ~/.claude/plugins/data/xp-agents-xp-agents/cf77350916c2/smm \
  edit-stack-field worktree_bootstrap
```

Notes: default timeout is 600s, tunable with `XP_BOOTSTRAP_TIMEOUT_S` (a cold `bun install` +
`uv sync` may need it). Update mode leaves an existing value alone — it is treated as a deliberate
declaration, so `/xp-system-context` will not clobber it.

---

## 6. How to know it worked — verify, don't assume

**This is the part that matters.** A bootstrap command's own exit code proves nothing: measured on
a sibling repo, the plausible candidate exited **0**, installed 2208 packages, and fixed neither
bug. Verify with a **differential** instead:

```bash
# 1. baseline in the primary
bun run test:all; echo "primary exit=$?"          # expect 0

# 2. bare worktree, unprovisioned
git worktree add --detach /tmp/dr-probe HEAD
cd /tmp/dr-probe && bun run test:all; echo "bare exit=$?"   # expect non-zero

# 3. run your candidate, then RE-MEASURE
bash scripts/init-worktree.sh
bun run test:all; echo "provisioned exit=$?"      # must be 0 — this is the proof

# 4. clean up
cd - && git worktree remove --force /tmp/dr-probe
```

Never read a runner's exit code through a pipe — `cmd | tail` gives you **tail's** exit status, and
a red run reads as green. (That mistake was made, and caught, while gathering this brief.)

Verify **every declared gate separately**, not just one. The install/generate split is
**per-artifact, not per-project**: on a sibling repo, `bun install` fully closed the *test* gap
while leaving the *typecheck* gap open. Here, check at least `bun run test:all`, `bun run
typecheck`, and `bun run lint`.

---

## 7. Measured vs not

**Measured here:** primary `test:all` exit 0; bare worktree exit 1; `bun install` exit 0 / 1871
packages; typecheck 1 → 0 after install; `test:all` **still 1** after install; `.venv` absent;
compose conflict on `divineruin-valkey` against a *stopped* container; `bun run lint:python`
exit 0 in 8s with `.venv` absent (uv self-bootstraps — no partial-bootstrap trap, §2.1); the
pre-commit suite has no DB step, so §3.3 does not gate it.

**Not measured:** whether option A's shared DB is safe under concurrent suites; the cold cost of
`bun install` + `uv sync` (timings seen were warm-cache — the 8s above is a warm uv cache, a cold
one will be slower); whether the full pre-commit suite passes end-to-end in a `bun install`-only
worktree (only its `lint:python` leg — the one at risk — was run); whether `bun run lint` and the
e2e/maestro surfaces have provisioning needs of their own beyond §3.

If something here contradicts what you observe, trust your measurement and correct this doc — that
is exactly how it came to exist.

---

## 8. Resolution (implemented 2026-07-17, story-005)

Built as `scripts/init-worktree.sh` + `scripts/worktree-common.sh`, declared as
`stack.worktree_bootstrap`. **Option B (per-worktree stack) was chosen** — the
repo had already committed to a shared singleton hardened by `_db_lifecycle.py`'s
flock refcount, but per-worktree isolation eliminates the shared-DB race/seed
class outright for parallel teammates. Corrections found by re-measuring in a
probe worktree (the differential in §6):

- **§3.1/§3.2 overstated the blocker.** `bun install` alone closes the *entire*
  `bun run lint` + `typecheck` gate here — `uv run` self-bootstraps `apps/agent/.venv`
  for the ruff/pyright leg. `test:all`'s residual failure was **not** `.venv`; it
  was a missing `.env` (the TS server lane fails loud on an unset `DATABASE_URL`).
- **The Expo typegen gap the brief missed, and its true severity.** `apps/mobile`
  has `typedRoutes: true`, so a bare worktree lacks `router.d.ts`/`expo-env.d.ts`.
  But `typecheck:mobile` still exits **0** without them — it is a **false green**
  (a bogus route compiles clean), not the legacy's hard-fail. The bootstrap
  regenerates them anyway (bounded dev-server) to close the false green.
- **`.env.example` carries a latent bug** the copy surfaces: `ASYNC_AUDIO_DIR=`
  (empty) + `activities.ts`'s `?? default` (doesn't catch `""`) resolved the audio
  dir to filesystem root. Fixed to `||`.
- **§3.3's collision was already half-solved and is now moot.** `_db_lifecycle.py`
  self-heals the stale-name conflict *and* keys its refcount on host:port; Option B
  drops `container_name` entirely, so compose namespaces by `COMPOSE_PROJECT_NAME`
  (= checkout basename) and each worktree offsets its host ports by
  `(cksum(basename) % 900 + 1) * 10` — primary = offset 0 (byte-identical). The
  DB helpers needed **no change** (they key on `DATABASE_URL`). One-time primary
  step: `docker compose down && up` to re-adopt the namespaced names (the
  `divineruin_pgdata` volume/data survives).
- **DB was per-worktree, not shared:** the bootstrap runs `docker compose up
  --wait` (healthcheck-gated, closing the migrate/seed readiness race) then
  `migrate` + `seed` against the worktree's own empty volume.

Verified via the §6 differential: fresh probe worktree → bootstrap exit 0 → its
own stack on offset ports → `typecheck`/`lint`/`test:all` all 0.
