# Changelog

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
