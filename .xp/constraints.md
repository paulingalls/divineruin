# Constraints

Reversing one of these makes it a different project. Cap: 15 items; adding over
the cap requires retiring one. Reviewers enforce these — cite the item.

1. **Fault-inject every guard.** A check that cannot red against its target
   defect is vacuous and worse than no check — it certifies.
2. **Small files: target 300 lines, hard cap 500 — tests included, because
   tests ARE production code**: same review bar, never skipped for test-only
   changes. Large files eat agent context; over-cap means extract, not scroll.
3. **Comments exist only for what neither a test nor a name can carry** — the
   why, an external constraint, a rejected design. Restates the code → delete.
   Narrates history → delete (git holds it). Checkable claim → make it a test.
4. **Fail fast, fail loud** — raise instead of returning None/empty when
   something is wrong; no fallback that masks a defect.
5. **Test at boundaries** — validate at system edges (input, APIs, I/O); trust
   internal logic.
6. **Name the producer.** A capability the DM invokes by id is not shipped
   until something surfaces that id — a tool response, a prompt, or an event
   payload. Twice in sprint-045 we shipped a gate keyed on a token nothing
   produced: a reaction `window` the DM had to guess among 9, and a variant id
   reachable only by a name no channel emits.
7. **A cross-language AC names both sides.** Content and contracts are mirrored
   in Python and TypeScript; a guard living on one side certifies nothing about
   the other. Verify names both files, or the directory — never one file whose
   tests a later split can silently narrow. Prefer the whole fast lane
   (`bun run test:python` / `bun run test:all`): a six-file Verify filter in
   sprint-046 stayed green over two red tests the story had broken.
8. **Replacing a literal means an inventory, not a path.** A card that replaces
   a hardcoded id — a companion, a tier tuple, a name — lists every site of that
   literal repo-wide (code, prompts, content, tests) or says which it leaves and
   why. Sprint-046 story-008 excluded four `companion_kael` sites as "off the
   session path" without grepping; the reviewer found sixteen more that were on
   it, and the combat prompt's tag survived to round 2.
