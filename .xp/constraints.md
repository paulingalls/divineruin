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
