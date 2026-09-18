# Constraints

Reversing one of these makes it a different project. Cap: 15 items and 4000
chars — over that, SessionStart's 9500-byte budget CLIPS the tail and the lead
never sees it. Reviewers enforce these — cite the item. The incident behind each
one is `.xp/system.md` → Constraint case law.

1. **Fault-inject every guard.** A check that cannot red against its target
   defect is vacuous and worse than no check — it certifies.
2. **Small files: target 300 lines, hard cap 500 — tests included, because
   tests ARE production code**: same review bar, never skipped for tests.
   Over-cap means extract, not scroll. CODE ONLY (human 2026-09-04): authored
   data — `content/*.json`, fixtures, generated files — is exempt.
3. **Comments carry only what neither a test nor a name can** — the why, an
   external constraint, a rejected design. Restates the code → delete. Narrates
   history → delete (git holds it). Checkable claim → make it a test.
4. **Fail fast, fail loud** — raise instead of returning None/empty when
   something is wrong; no fallback that masks a defect. REPLACING A CRASH WITH
   TOLERANCE MEANS ENUMERATING WHAT YOU NOW TOLERATE, and leaving a floor that
   still fails: "produced nothing usable".
5. **A falsifier is a behaviour command, not a grep of the fix.** Name the test
   that reds on it.
6. **Name the producer.** A capability the DM invokes by id is not shipped
   until something surfaces that id — a tool response, a prompt, or an event
   payload.
7. **A cross-language AC names both sides.** Content and contracts are mirrored
   in Python and TypeScript; a guard on one side certifies nothing about the
   other. Verify names both files, or the DIRECTORY — never one file whose tests
   a later split can silently narrow. `test:all` stays OUT of Verify (human
   2026-09-06), BUT THE EXECUTOR RUNS `bun run test:python` BEFORE FINISHING,
   and a card that edits an acceptance harness, a combat declaration or a band
   also runs `bun run test:acceptance:nollm`.
8. **Replacing a literal means an inventory, not a path.** A card that replaces
   a hardcoded id — a companion, a tier tuple, a name — lists every site of that
   literal repo-wide (code, prompts, content, tests) or says which it leaves and
   why.
9. **A guard that models someone else's contract certifies the model, not the
   contract.** Where the real thing can be executed — a vendor type, a live
   endpoint, a schema the provider compiles — the test constructs or calls it.
   Mock our own seams; never the other side's shape, in or out. A VENDOR LIMIT
   IS PER REQUEST, NOT PER PROJECT.
10. **A claim about code is a code claim — RUN it, don't read it.** BEFORE
   MINTING run the Verify, grep every `file:NNN`, re-run every measurement. An
   AC naming VALUES or an ABSENCE is this rule. Caught by a refresh or a
   reviewer, never the author.
11. **A failure that RECURS is a defect, not variance.** Fix what produces it,
   never the guard that caught it. A note naming an owner is not a schedule: if
   it must be fixed, it is a card.
12. **An absence AC is only as wide as the walk under it, and a walk needs a
   REACHABLE non-empty floor.** A guard proving "nothing does X" names every
   corpus it walks and reds when that corpus comes back empty: a missing
   directory, a hand-maintained tuple and a moved file all read as green. A walk
   is only as good as the ANSWER it compares: a side that can ABSTAIN turns
   "they agree" into no measurement. Tightening one predicate DRAINS its
   neighbour — re-inject the guards a change passes through, not only the one it
   adds.
