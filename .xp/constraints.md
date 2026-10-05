# Constraints

Reversing one of these makes it a different project. Cap the entire UTF-8 file at
4,500 bytes to fit Codex's 10,000-byte SessionStart hook limit. Reviewers enforce
these — cite the item. The incident behind each one is `.xp/system.md` →
Constraint case law.

1. **Test behavior at the outermost boundary that reaches it, once.** When an
   integration or acceptance test covers a behavior, delete the unit tests that
   duplicate it. Unit tests are TDD scaffolding, not a permanent asset.
2. **Tests cost what code costs.** Test lines stay at or below twice the lines
   they test. The commit hook finishes in under a minute; everything slower runs at
   push, at sprint close, or nightly. A slow test is a defect in the test.
3. **A guard is fault-injected once, when it is added, in its own test file,
   and only if its failure would be silent or corrupting.** No tests of tests,
   no meta-tests of gates, no proof that a check's corpus is non-empty. A loud
   failure needs no guard at all.
4. **Small files: target 300 lines, hard cap 500 — tests included, because
   tests ARE production code**: same review bar, never skipped for tests.
   Over-cap means extract, not scroll. CODE ONLY (human 2026-09-04): authored
   data — `content/*.json`, fixtures, generated files — is exempt.
5. **Comments carry only what neither a test nor a name can** — the why, an
   external constraint, a rejected design. Restates the code → delete. Narrates
   history → delete (git holds it). Checkable claim → make it a test.
6. **Fail fast, fail loud** — raise instead of returning None/empty when
   something is wrong; no fallback that masks a defect. REPLACING A CRASH WITH
   TOLERANCE MEANS ENUMERATING WHAT YOU NOW TOLERATE, and leaving a floor that
   still fails: "produced nothing usable".
7. **Name the producer.** A capability the DM invokes by id is not shipped
   until something surfaces that id — a tool response, a prompt, or an event
   payload.
8. **A cross-language AC names both sides.** Content and contracts are mirrored
   in Python and TypeScript; a guard on one side certifies nothing about the
   other.
9. **Replacing a literal means an inventory, not a path.** A card that replaces
   a hardcoded id — a companion, a tier tuple, a name — lists every site of that
   literal repo-wide (code, prompts, content, tests) or says which it leaves and
   why.
10. **A guard that models someone else's contract certifies the model, not the
   contract.** Where the real thing can be executed — a vendor type, a live
   endpoint, a schema the provider compiles — the test constructs or calls it.
   Mock our own seams; never the other side's shape, in or out. A VENDOR LIMIT
   IS PER REQUEST, NOT PER PROJECT.
11. **A claim about code is a code claim — RUN it, don't read it.**
12. **A failure that RECURS is a defect, not variance.** Fix what produces it,
   never the guard that caught it. A note naming an owner is not a schedule: if
   it must be fixed, it is a card.
