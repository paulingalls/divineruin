# Milestones

A user-facing goal is measured where users are.

Each Measure is one shell line run from the repository root. It prints the
remaining distance in one line: a cheap read over records or files, never a test
run.

## Run only the tests an edit could break
Goal: "set up proof for divineruin's tests so you only run the tests an edit could break" (human 2026-11-02, via the proof session).
Baseline (main fd77ddfa, 2026-11-02, host load ~20): `bun run test` 14s / 2049 tests; `test:python` 48s / 8836; `test:acceptance:nollm` 618s / 636.
Measure: python3 -c 'import json,subprocess; from pathlib import Path;  r=json.loads(subprocess.check_output(["bunx","proof","plan","--json"],text=True,stderr=subprocess.DEVNULL)); t={x["task"] for x in r}; t.update({"agent-acceptance"} if any(x.startswith("agent-acceptance:") for x in t) else set()); t.update({"e2e"} if any(x.startswith("e2e:") for x in t) else set()); t.update("hook:"+n for n in ("pre-commit","pre-merge-commit","sprint") if "proof run" in (Path(".githooks")/n).read_text()); w="hook:pre-commit hook:pre-merge-commit hook:sprint bun-scripts bun-shared bun-design-tokens bun-server server-db server-locations-load server-terrain-startup server-invite-store bun-mobile bun-web agent-pytest agent-acceptance e2e".split(); m=[x for x in w if x not in t]; print("distance=%d undeclared: %s" % (len(m), " ".join(m)))'
Candidates: agent pytest task (uv sandbox venv cost); acceptance split per file; hooks call `proof run --set commit`; migrate remaining milestones from plan.md.

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
Candidates: Thyra's gift (`awaits_terrain`): Phase 10 shipped `apps/agent/terrain.py` `TerrainType`, so bind it. Veythar, Syrath, Valdris and Zhael (`awaits_rest`) wait on a production caller of `apply_long_rest`/short rest (`rest_mechanics.py:236`). Orenthel (`awaits_healing`) waits on an HP-restore caller. Mortaen and Nythera are `narrated`; decide whether "mechanically distinct and always active" needs more. Layer 2 and Layer 3 are still null in `content/gods.json`. Whether a favor loss may ever trigger a whisper is an open human question (note from story-224). The spec's 15–30 minute heartbeat against the hydration-time decay chosen in M8.1b. Unbound Path (Resonance visibility, +3 push, Veil Mastery).

## Patron abilities (Phase 8 M8.2)
Goal: every patron's abilities across the three favor tiers, with recharge, can be granted and activated by the DM in play: `docs/milestones/08_patrons.md` Milestone 8.2 ACs.
Measure: python3 -c 'import re; s=open("docs/milestones/08_patrons.md").read(); b=re.search(r"^### Milestone 8.2 .*?(?=^### |\Z)",s,re.M|re.S).group(0); print("distance=%d" % len(re.findall(r"^- \[ \] ",b,re.M)))'
Candidates: see the phase doc; depends on M8.1's Layer 3 definitions.

## Archetype synergies and the Unbound Path (Phase 8 M8.3)
Goal: Layer 4 archetype synergy bonuses work, and the Unbound Path is a mechanically complete alternative to a patron: `docs/milestones/08_patrons.md` Milestone 8.3 ACs.
Measure: python3 -c 'import re; s=open("docs/milestones/08_patrons.md").read(); b=re.search(r"^### Milestone 8.3 .*?(?=^### |\Z)",s,re.M|re.S).group(0); print("distance=%d" % len(re.findall(r"^- \[ \] ",b,re.M)))'
Candidates: see the phase doc; depends on M8.1 and M8.2.
