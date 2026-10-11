# Changelog

## 0.29.0 — 2026-10-10

- Elite and Boss Mawlings attack Claw, Dissolution Maw, Claw. The per-role sequence is authored on the catalog row, and both validators reject unknown role keys and unresolvable attack references. Standard Mawlings keep Claw then Dissolution Maw.
- A melee hit from within 5 ft on a Fallen character adds two death-save failures. Ranged hits, save damage and the Dissolution Field tick still add one. A queued strike continues onto a target who fell earlier in the same phase; only damage reaches a Fallen ally, so a hostile mark aimed at one is wasted.
- Story land runs the fast lane (`bun run test:all`) on the merged tree before the merge commits, and keeps the full output in `flake-artifacts/last-pre-merge-commit.log`. Acceptance stays at sprint close.
- `probe_strict_limits.py --provider openai-luna --agent <name>` sends one strict-compile request for one agent with retries off. The combat agent's 9 tools were accepted strict.
- Split `combat_turn.py` into the tool shells and `combat_resolve_phase.py`, and move the down-target rules into `combat_down.py`, which breaks an import cycle through `combat_ability`.
- Source walks in the strict-budget and line-cap tests read tracked files only, ending an intermittent fast-lane failure under parallel runs. Meta-tests of test helpers were deleted; constraint 3 now keeps tests of tests, hooks and tools out of regular runs, and new constraint 13 makes wall clock a quality budget.

## 0.28.0 — 2026-10-08

- Mawlings declare their authored Claw then Dissolution Maw multiattack as one declaration with per-strike targets. Each strike keeps its own held reaction window across pauses and reloads; an unavailable strike drains unresolved, with no retargeting. Minion Mawlings keep a single attack.
- Dissolution Maw applies its CON DC 13 held-item durability rider to a DM-selected, equipped player item, chosen from target-scoped inventory facts that include guests. Role DC modifiers apply, and companions are excluded. Both validators reject riders on save- or condition-resolved attacks.
- A living ally grappled by a living, able Mawling takes 1d6 necrotic Dissolution Field damage at its turn start, even when stunned, Fallen or omitted from declarations. Damage to a Fallen character now adds one automatic death-save failure.
- Reaction spends checkpoint in the same transaction as their resource debit, so a reload cannot re-spend them. The checkpoint save refuses to run without the combat-state lock.
- Split XP roles across model families: codex plans and executes, and Claude reviews plans and diffs.

## 0.27.0 — 2026-10-04

- Adopt the v1 development constraints: test production behavior once at the outermost useful boundary, retire duplicate unit coverage, and remove documentation wording checks and test meta-checks.
- Keep pushes service-free with local lint and Bun tests. Run the full suite at sprint close; free patches use focused acceptance and normal PR CI.
- Reduce tracked test lines from 177,625 to 160,505 and the test/source ratio from 2.2106× to 1.9991×. Preserve unique behavior checks while removing redundant tests, setup, and commentary.
- Make the live material-inventory acceptance check independent of Bun's compact diagnostic output.
