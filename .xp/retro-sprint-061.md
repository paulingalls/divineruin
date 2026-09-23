# Sprint 61 retrospective

M32's natural-creature half shipped. All 19 natural creatures the bestiary spec authors are in `content/creatures.json`, each with complete stat blocks, spec loot tables and sound-first narration. That closes M7.2 at 11/11 and M7.1's narration box. Creatures carry a `home_region` and a `regions` list on one canonical region-id set, mirrored in Python and TypeScript. Internal `query_creatures_by_region` / `query_creature_by_id` answer against real Postgres; the DM surface is M34's, through `query_info(kind="creature")` (human decision). A loot drop may now name a harvested material, and combat loot raises instead of recording a raw id. Seeding refuses an empty or null `drops`. The rend and knight residue drops match the spec's tiers. Six cards landed against a cap of six. A free patch (v0.20.1) stopped the test tooling leaking temp dirs.

**What the process caught.**
- **The slate review turned every card RED**, and every finding was real:
  - four closed-set pins that the first new creature would break;
  - `crystal_flask` being in both catalogs;
  - a region-count AC that no spec-faithful mapping could satisfy;
  - Troll having no weapon attack;
  - War Golem's requirements being misstated.
- **The story reviewers fixed real defects inside their rounds:**
  - a region-to-DC map built from list order, which made its own guard vacuous;
  - a full-lane regression that the focused Verify missed (test_guest_ends_combat stubs);
  - a narration check with no fault test;
  - placeholder audio blocks;
  - a sweep that crashed concurrent runs;
  - a uniqueness test weakened from "distinct tactics AND morale" to the pair;
  - 12 filler material descriptions.
- **The story tier at land** caught two things the Verify and the reviewer had not run: stale milestone counts after a box was checked (story-126), and a reviewer's hand edit of the generated `docs/INDEX.md` (story-125). Each cost an unreviewed lead commit.

**What it missed.** The same land-time catch, three times: box-checking and doc-editing cards named neither `tests/docs` nor `test_milestone_status_consistency.py` in Verify, so the drift surfaced only in the tier. I also ran two lands at once, and both Playwright webServers bound :3001. That is recorded as a serial-lands rule; divineruin2 owns deriving the port per checkout (its Sprint 107). The day's disk-full and Docker.raw event (another project's Xcode output, then another session's cleanup) drove three pre-push failures and a wiped dev DB. The human dropped those failures as environmental.

**Rules.** Constraint 12 (a reachable non-empty floor) earned the most: every closed-set pin the slate review found would have turned a growing catalog red or vacuous. Constraint 10 caught two of my own wrong claims: an empty-drops refusal that did not exist, and "the header's region table", which the refresher could not find. Nothing cost more than it returned.

**Executable diff.** `.xp/constraints.md` item 7 gains: "A card that checks a milestone box or edits a doc names tests/docs and test_milestone_status_consistency.py in Verify." Cards 127 and 128 carried it by hand and landed green on it.

Also recorded: story-128's Mawling currency control holds by construction, because currency rolls before loot. The human signed off the Hollowmoth wounded cue ("A sharp squeal cuts the air, and the moth flutters on as if untouched.").
