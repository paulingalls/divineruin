# Changelog

## 0.27.0 — 2026-10-04

- Adopt the v1 development constraints: test production behavior once at the outermost useful boundary, retire duplicate unit coverage, and remove documentation wording checks and test meta-checks.
- Keep pushes service-free with local lint and Bun tests. Run the full suite at sprint close; free patches use focused acceptance and normal PR CI.
- Reduce tracked test lines from 177,625 to 160,513 and the test/source ratio from 2.2106× to 1.9992×. Preserve unique behavior checks while removing redundant tests, setup, and commentary.
- Make the live material-inventory acceptance check independent of Bun's compact diagnostic output.
