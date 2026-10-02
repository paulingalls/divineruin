# Sprint 62 retrospective

This sprint laid the groundwork for Milestone 32's full catalog reference. The switch-over itself is Sprint 63. Catalog rows can now carry the combat mechanics encounters use: conditions behind saves, grapples, save-for-half damage, commands and accusations, signature abilities and resistance tags. Both the Python and TypeScript validators check these fields, and they reuse the combat-entry checks rather than copying them (story-129).

The catalog now holds 36 creatures:
- all nine spec Hollow creatures (130, 131), which checks two M7.3 boxes;
- the eight encounter-only creatures, whose spec blocks the human signed off (132) before their catalog rows were written (133).

Debt 023c31e7 is closed: a player's materials now appear in the DM's inventory, in the HUD and in repair, and combat still starts while a material is held (134). Six cards landed against a cap of six. A free patch, v0.21.4, fixed a pre-push bug that blocked every push from this checkout: a key missing from `.env` read as an empty value. The same patch fixed the `.git/config` lock race between parallel worktree setups.

**What the process caught.**
- **The slate review failed three cards, and each finding was real.** No faithful copy of the eight encounter blocks could fit the tier bands; `crystal_flask` was in both catalogs; and the doc test checked attack names only.
- **The execution plan review stopped story-133 before any code.** The signed-off spec gave three Hollow troops the same `vulnerable_to`, which the Hollow distinctness walk forbids. The human chose distinct sets.
- **Story reviewers fixed real defects inside their own rounds:**
  - pin tests that no tier collected (130);
  - veil effects paraphrased away from the spec, with a pin that checked the catalog against itself (130);
  - Tier 4 pins that checked only free text, never the fields combat reads (131);
  - a missing Architect legendary action (131);
  - a one-directional signature check (132);
  - a loosened placeholder-audio guard (133);
  - my own dropped `pipefail` guard when I moved the env-value test into its own script (free patch, round 2).
- **The card refresh corrected three wrong claims in story-132's card before it was minted.**

**What it missed.**
- **The slate's header rule had no check in the card that authored the data.** Story-132's doc test never checked the pairwise-distinct Hollow rule, so the conflict surfaced only after sign-off, at story-133's plan review.
- **Two clones shipping to one origin cost several unplanned rounds:**
  - land takes its base from the local trunk, so a stale local main made it refuse, and then the recorded base forced a mechanical third review round;
  - merging main without reinstalling left the Python lane red on the workspace report;
  - worktrees cut before v0.21.3's validator change tore down with their old scripts.

**Rules.** Constraint 12 (every walk needs a reachable non-empty floor) earned its place again: the nine-Hollow test, the distinctness walk and the faction exclusion all fail on an empty set. Constraint 1 (fault-inject every guard) caught my own extraction slip. Nothing cost more than it returned. The land-base behaviour is a plugin defect, filed as note e99d78bd and promoted here as a workaround.

**Executable diff (`.xp/system.md`).**
- **Conventions:** pytest collects only `test_*.py`, so a pin module may hold data but never test functions.
- **Conventions:** a sprint-header rule that a later card's walk enforces must also be named in the AC of the card that authors the data.
- **Dependency-changing landings:** a paragraph on two clones sharing one origin:
  - `git fetch origin main:main` before landing after the other clone releases;
  - frozen installs after merging main;
  - a teardown sweep for worktrees cut before a validator change.

**Carried to Sprint 63 (the cutover)**, recorded on M32 in plan.md:
- Lunge's recharge exists only as text.
- Memory Scream needs a path where a successful save means no damage.
- Encounter `properties` must be derived.
- A Boss signature has no sound-first cue.
- The combat check functions the schema reuses should lose their underscore prefix.

Material tier/category mismatches with the spec are recorded on M34.
