# Milestones

A user-facing goal is measured where users are.

Each Measure is one shell line run from the repository root. It prints the
remaining distance in one line: a cheap read over records or files, never a test
run.

## Run only the tests an edit could break
Goal: "set up proof for divineruin's tests so you only run the tests an edit could break" (human 2026-11-02, via the proof session). Extended: "if we optimize the test efficiency using proof then we can cut down the hook costs and move faster" (human 2026-11-16): a content or shared-module edit keys only its readers and representatives, and a scheduled fresh super run covers the rest.
Baseline (main fd77ddfa, 2026-11-02, host load ~20): `bun run test` 14s / 2049 tests; `test:python` 48s / 8836; `test:acceptance:nollm` 618s / 636.
Measure: python3 scripts/proof_key_breadth.py
Reading (d4bbc919, 2026-11-16): distance=816 mean=18.9 files=2198
Candidates: sprint proof-targeted-selection (super run, docs out of keys, shared-code representatives, content keyed by reader, free land runs land+sprint sets and CI only lints); target below 50 files keying more than 20 expensive tasks, with a mean below 5.

## Hollow creatures (Phase 7 M7.3)
Goal: the corruption aura, resonance-on-death and the Tier 4 Hollow behaviours (Choir, Still, Architect) work in play: `docs/milestones/07_bestiary.md` Milestone 7.3 ACs, including the Hollow edge cases (Execution plan Milestone 33, in progress).
Measure: python3 -c 'import re; s=open("docs/milestones/07_bestiary.md").read(); b=re.search(r"^### Milestone 7.3 .*?(?=^### |\Z)",s,re.M|re.S).group(0); print("distance=%d" % len(re.findall(r"^- \[ \] ",b,re.M)))'
Candidates: re-verify the aura and resonance boxes against `apps/agent/hollow_resonance.py` (Sprint 64 shipped both functions, but their boxes are unchecked; constraint 11). The Still (passive until attacked, damage reflection) and the Architect (terrain manipulation). Tier 3 boss HP and phases (Hollowed Knight, Veilrender). The Elite/Boss Mawling multiattack and the melee-within-5-ft rule from M33's required inputs shipped in v0.30.0; check them off there.

## Harvesting and the encounter builder (Phase 7 M7.4)
Goal: `build_encounter` builds encounters from the catalog, and harvesting enforces skill gates: `docs/milestones/07_bestiary.md` Milestone 7.4 ACs, which unblock Phase 9's material sell values (Execution plan Milestone 34).
Measure: python3 -c 'import re; s=open("docs/milestones/07_bestiary.md").read(); b=re.search(r"^### Milestone 7.4 .*?(?=^### |\Z)",s,re.M|re.S).group(0); print("distance=%d" % len(re.findall(r"^- \[ \] ",b,re.M)))'
Candidates: D-4: `build_encounter` reads each companion's `hp_factor`, not a flat 0.75 (Sable is 0.50), which overrides the doc's "75% HP" AC wording. Movement modes (fly, swim, climb, burrow) in the creature schema in both languages, if environment modifiers need them. Normalize `behavior.morale`/`group_size` to one shape. Backfill natural rows' engine-resolvable riders before they enter combat. Fix the woven_void_fragment, veil_shard and salvageable_weapon tier/category against the spec. Reach the creature catalog only through `query_info kind="creature"`. Choose the signature ability (`04_combat.md:34`).

## Patron favor and gifts (Phase 8 M8.1)
Goal: all ten patrons' Layer 1 gifts are live, Layer 2 Resonance modifiers and Layer 3 tiers are defined, and the Unbound Path is selectable: `docs/milestones/08_patrons.md` Milestone 8.1 ACs (divineruin2 plan Milestones 8.1a–8.1d are done; tiers and decay are checked off).
Measure: python3 -c 'import re; s=open("docs/milestones/08_patrons.md").read(); b=re.search(r"^### Milestone 8.1 .*?(?=^### |\Z)",s,re.M|re.S).group(0); print("distance=%d" % len(re.findall(r"^- \[ \] ",b,re.M)))'
Candidates: (1) Sprint `patron-alignment-heartbeat` (deferred by the human 2026-11-04): first design a durable per-player deed journal (who writes it, patron-value tags and amounts, player attribution, an atomic checkpoint with favor so repeat ticks can't double-award), then `evaluate_patron_alignment` and a 15–30 minute in-session tick driven through `BackgroundProcess._run` with an owned clock. No heartbeat decay (decay stays at hydration). `record_patron_action` and quest completion already award immediately; don't double-count them. (2) Production rest and HP-restore callers for the Veythar, Syrath, Valdris, Zhael (`awaits_rest`) and Orenthel (`awaits_healing`) gifts; these overlap combat and rest code, so coordinate with the divineruin lead first. Mortaen and Nythera are `narrated`: decide whether that meets "mechanically distinct and always active".

## Patron abilities (Phase 8 M8.2)
Goal: every patron's abilities across the three favor tiers, with recharge, can be granted and activated by the DM in play: `docs/milestones/08_patrons.md` Milestone 8.2 ACs.
Measure: python3 -c 'import json,re; s=open("docs/milestones/08_patrons.md").read(); b=re.search(r"^### Milestone 8.2 .*?(?=^### |\Z)",s,re.M|re.S).group(0); g=json.load(open("content/gods.json")); print("distance=%d pending_engine=%d" % (len(re.findall(r"^- \[ \] ",b,re.M)),sum(a["status"]=="pending" and a["resolution"]=="engine" for p in g for a in p["layer_3_tier_abilities"].values())))'
Candidates: see the phase doc; depends on M8.1's Layer 3 definitions.

## Archetype synergies and the Unbound Path (Phase 8 M8.3)
Goal: Layer 4 archetype synergy bonuses work, and the Unbound Path is a mechanically complete alternative to a patron: `docs/milestones/08_patrons.md` Milestone 8.3 ACs.
Measure: python3 -c 'import re; s=open("docs/milestones/08_patrons.md").read(); b=re.search(r"^### Milestone 8.3 .*?(?=^### |\Z)",s,re.M|re.S).group(0); print("distance=%d" % len(re.findall(r"^- \[ \] ",b,re.M)))'
Candidates: see the phase doc; depends on M8.1 and M8.2. (a) A combat-roll seam for attack, damage, crit, AC, initiative, death saves, Inspire die, Shadow Veil duration and fact-dependent combat clauses; prospective owners are combat attack/damage, saves, initiative and reactions. (b) A circumstance producer feeding check resolution for the 30 numeric circumstance-check clauses (commerce, hidden information, burial, evidence, repair, shelter and related conditions). See sprint archetype-synergies DATA `synergy-review.md`, retained-pending clause inventory; these categories do not exhaust its 103 pending clauses. Keep clauses pending until their production prerequisites exist.

## First share: friends play the story on TestFlight
Goal: "I think we need to really focus on the story to get people started" (human 2026-11-15): a friend on TestFlight plays a complete first episode and two more sessions without the DM improvising the plot: every box in `docs/milestones/13_first_share.md`. This checkout's line is Session 1; the divineruin2 clone adds Session 2, Session 3 and deployment sections to the same file.
Measure: python3 -c 'import re; print("distance=%d" % len(re.findall(r"^- \[ \] ",open("docs/milestones/13_first_share.md").read(),re.M)))'
Hosting (human 2026-11-16): a new DigitalOcean project `divineruin`, kept apart from the human's other projects; one s-2vcpu-4gb droplet runs server, agent and worker from `deploy/compose.yml`; DO managed Postgres and managed Valkey; media on Spaces (replaces the local media volume, so the object-storage adapter in `docs/ideas/object-storage-migration.md` becomes a card); about $60/mo before usage-billed providers. Images go to GHCR (`ghcr.io/paulingalls/divineruin-*`, human 2026-11-16), not legacy's `cordelia-beta` DOCR: DO allows one registry per account, and sharing it would couple the estates through legacy's Terraform state and a registry-wide pull credential that reaches legacy's BIPA-bearing images. Branch protection: answered by the develop milestone below. Spend still needs the human's go before any billed resource is created.
Candidates: a carry choice for the fragment with a consequence in session 2 (needs a consumer on the Greyvale side first); re-choosing race and patron in a later session at Temple Row; an in-session patron whisper instead of the catch-up one; cut market beat 2 if a played session runs past 30 minutes; the human plays the build end to end and files what breaks.

## develop integrates, main is live
Goal: "for branches, we should add a develop branch. look at how things work in ../legacy especially with versioning" (human 2026-11-16). Sprints and free patches land on `develop`; `main` only fast-forwards to the SHA that was deployed and verified; versions are stamped from `changes/<branch>.md` notes after merge (legacy briefing: /Users/paulingalls/src/projects/legacy-briefing-for-divineruin.md). Switch after sprint greyvale-ruins lands on main (human 2026-11-16).
Measure: python3 -c 'import subprocess as s,re; c=open(".xp/config.yml").read(); u=[n for n,ok in (("trunk",re.search(r"^trunk: *develop",c,re.M)),("notes",re.search(r"^versioning: *notes",c,re.M)),("develop",s.run(["git","rev-parse","-q","--verify","origin/develop"],capture_output=True).returncode==0),("promote",__import__("os").path.exists("scripts/promote-main.sh"))) if not ok]; print("distance=%d %s" % (len(u)," ".join(u)))'
Candidates: create `develop` from main at v0.42.0 and make it the GitHub default branch; `.xp/config.yml` `trunk: develop` and `versioning: notes`; `changes/README.md`; `scripts/promote-main.sh` fast-forwards main to the verified deployed SHA (legacy `infra/deploy/release-beta.sh` step 6.5) and is called by the deploy script; tell divineruin2. Skip on day one (legacy judgment): promotion capstone, after-promotion workflow, disposable release worktree; add the ancestry check the first time main is hotfixed.
