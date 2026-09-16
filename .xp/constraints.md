# Constraints

Reversing one of these makes it a different project. Cap: 15 items; adding over
the cap requires retiring one. Reviewers enforce these — cite the item.

1. **Fault-inject every guard.** A check that cannot red against its target
   defect is vacuous and worse than no check — it certifies.
2. **Small files: target 300 lines, hard cap 500 — tests included, because
   tests ARE production code**: same review bar, never skipped for tests.
   Large files eat agent context; over-cap means extract, not scroll.
   CODE ONLY (human decision 2026-09-04): authored data — `content/*.json`,
   fixtures, generated files — is exempt; two reviewers have spent a round on it.
3. **Comments exist only for what neither a test nor a name can carry** — the
   why, an external constraint, a rejected design. Restates the code → delete.
   Narrates history → delete (git holds it). Checkable claim → make it a test.
4. **Fail fast, fail loud** — raise instead of returning None/empty when
   something is wrong; no fallback that masks a defect. WHEN YOU REPLACE A CRASH
   WITH TOLERANCE, ENUMERATE WHAT YOU ARE NOW TOLERATING: sprint-048's narration
   normalizer coerced the shapes I had seen and let its `else` absorb every shape I
   had not, so an errand "resolved" in silence. A tolerant parser needs a floor
   that still fails — here, "produced nothing usable".
5. **Test at boundaries** — validate at system edges (input, APIs, I/O); trust
   internal logic.
6. **Name the producer.** A capability the DM invokes by id is not shipped
   until something surfaces that id — a tool response, a prompt, or an event
   payload. Twice in sprint-045 we shipped a gate keyed on a token nothing
   produced: a reaction `window` the DM had to guess among 9.
7. **A cross-language AC names both sides.** Content and contracts are mirrored
   in Python and TypeScript; a guard living on one side certifies nothing about
   the other. Verify names both files, or the DIRECTORY — never one file whose
   tests a later split can silently narrow. But `test:all` DOES NOT BELONG IN A
   VERIFY LINE (human decision 2026-09-06): the `story` tier already runs it on the
   merged tree at every close, so a card repeating it only slows the executor.
8. **Replacing a literal means an inventory, not a path.** A card that replaces
   a hardcoded id — a companion, a tier tuple, a name — lists every site of that
   literal repo-wide (code, prompts, content, tests) or says which it leaves and
   why. Sprint-046 story-008 excluded four `companion_kael` sites without
   grepping; the reviewer found sixteen more on the session path.
9. **A guard that models someone else's contract certifies the model, not the
   contract.** Where the real thing can be executed — a vendor type, a live
   endpoint, a schema the provider compiles — the test constructs or calls it.
   Twice in sprint-047: a schema walk went green on all three ceilings while the
   live API refused three agents ("compiled grammar is too large"); and a
   `MagicMock` invented whichever attribute production named, so token counters
   read 0 for months. Sprint-048 added the PARSING side — we read the model's
   narration `segments` assuming dicts, and it sent a bare string. Mock our own
   seams; never the other side's shape, in or out. A VENDOR LIMIT IS PER REQUEST,
   NOT PER PROJECT: ADR 0004's strict ceilings are the gameplay agents' toolsets,
   and narration's one tool was accepted strict the day we finally asked
   (sprint-050).
10. **A claim about code is a code claim — open the file.** Four times in
   sprint-048 the lead asserted what code does from a DESCRIPTION and was wrong:
   `reactions_available`'s polarity stated backwards from its name, and "no
   distinctness guard exists" after stopping at line 138 of a 171-line test file.
   Every one was caught by a reviewer or a refresh, none by the author. An AC that
   names a field's VALUES — polarity, sentinel, shape — or an ABSENCE ("nothing
   checks X") is the code claim this rule is about.
11. **A failure that RECURS is a defect, not variance.** Fix what produces it,
   never the guard that caught it. The training midpoint judge red in sprints 48,
   49 and 50 — about 40% of pushes — each run shrugged off alone; the cause was
   the DM paraphrasing the resolved state away, one prompt line. A note naming an
   owner is not a schedule: if it must be fixed, it is a card.
