# Sprint 60 retrospective

M31 (Phase 7 M7.1, the creature stat block) shipped, and both scheduled debts were paid. Each enemy now carries one authored tier, and `tier_for_level` is gone. Humanoid coin scales from that tier, so the human-accepted balance change moves 17 rows' currency. Loot tables carry the spec's loot block: `requires` [{skill, tier}] as data, dice quantities rolled before the role modifier, and `hollow_residue`. The stat block follows the spec template, and one shared fixture corpus drives the Python and TypeScript validators. The `creatures` table has generated, indexed columns, and every content type now seeds in one transaction that rolls back on any validation error. A guard checks that design docs name only agents that exist, and a recap now counts the items each player actually received. Six cards landed against a cap of six, plus two `[sprint-direct]` commits.

**What the process caught.**
- **The card refresh changed all six cards** before they were marked ready. It found a missed `tier_for_level` caller, a test double listed as infrastructure, stale line anchors, and the real post-commit call site (`combat_turn.py:344`, not `combat_wrap.py`).
- **The plan review** caught a vacuous "every other row" check, and a currency falsifier that could not fail at L3 where the old and new lookups agree.
- **The story reviewers** found and fixed several gaps:
  - Three seed-loot guards could be deleted with nothing failing.
  - The warden fixture could not detect the old level lookup.
  - The tier and level generated columns could not be told apart.
  - A float disagreed between languages (Python rejects `8.0`, TS accepts it).
  - An M4.8 acceptance test broke, visible only in the pre-push lane.
- **A real defect behind the card:** a guest's `transact` find leaked into the host's saved recap. It was fixed on the sprint branch (`d050e50d`), with `SessionData.record_item_found` as the one rule for all three paths.

**What it missed.** Story-119 put four Postgres testcontainer boots into the fast unit lane. Nothing refused it: the slate review, the plan review and the Verify all passed. The round-1 reviewer only noted it. The lead moved the tests into `tests/acceptance/` and paid a confirming round. Separately, my own `ruff format` over `scripts/` ran without apps/agent's config, and briefly re-wrapped 80 lines at 88 columns.

**Rules.** Constraint 10 (run the claim) earned its place through the refresh leg again. Constraint 1 (fault-inject every guard) earned the most: every reviewer round found at least one guard that could not fail. Constraint 7 (name both sides) produced the float-parity fix. Nothing cost more than it returned this sprint.

**Executable diff.** `apps/agent/tests/test_container_lane.py` fails when any test file outside `tests/acceptance/` imports `testcontainers`. Its non-empty floor fails if no acceptance file imports it. Injecting a single `from testcontainers...` line into `tests/` makes it fail.
