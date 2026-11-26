# Milestones

A user-facing goal is measured where users are.

Each Measure is one shell line run from the repository root. It prints the
remaining distance in one line: a cheap read over records or files, never a test
run.

## Archetype synergies and the Unbound Path (Phase 8 M8.3)
Goal: Layer 4 archetype synergy bonuses work, and the Unbound Path is a mechanically complete alternative to a patron: `docs/milestones/08_patrons.md` Milestone 8.3 ACs.
Measure: python3 -c 'import re,json; s=open("docs/milestones/08_patrons.md").read(); b=re.search(r"^### Milestone 8.3 .*?(?=^### |\Z)",s,re.M|re.S).group(0); p=sum(c["status"]=="pending" for g in json.load(open("content/gods.json")) for r in (g["layer_4_synergy_matrix"] or {}).values() for c in r["clauses"]); print("distance=%d" % (len(re.findall(r"^- \[ \] ",b,re.M))+p))'
Candidates: see the phase doc; depends on M8.1 and M8.2. (a) A combat-roll seam (sprint combat-roll-synergies covers crit range, crit riders, the Extra Attack damage, Veythar cantrips and Mortaen's undead and Sacred Flame clauses) for the remaining attack, damage, AC, initiative, death saves, Inspire die, Shadow Veil duration and fact-dependent combat clauses. Spell-heal landing (sprint heal-synergies covers Orenthel cleric/paladin, Mortaen cleric/paladin, Thyra and Nythera cleric) leaves the Orenthel mage clause pending (no mage reaches a heal), Sprint encounter-facts built the encounter-fact ledger (`encounter_facts.py`: ally downers, misses, attacked, death-save successes, deaths) and used it for Mortaen warrior/druid/warden, Zhael warrior/guardian/cleric and Kaelen paladin. Sprint fallen-ally-synergies shipped Mortaen guardian (+1 AC while any other ally is at 0 HP, encounter-wide, human 2026-11-24), Mortaen marshal (death saves) and Kaelen bard (d6 Inspire on attacks), all read from live state with no ledger key. Sprint syrath-deeper-shadow shipped Syrath rogue/spy/whisper Deeper Shadow (two-round Shadow Veil; +1d6 on the first strike from the veil, spy/whisper wording per human 2026-11-24) and Zhael oracle's second Fate's Thread per long rest. Combat now resolves Direct Strike, Coordinated Assault, Sacrifice Play, Reposition and Field Medic Order through `combat_martial.resolve_order`. Sprint zhael-orders-and-omens shipped their patron integration. Zhael marshal Moment to Rally means any ally-targeted order, Interceding Order only when its +2 applies, grants +1 on the ally's next save of any kind, death saves included. It is once per encounter per marshal, clears at combat end, and is consumed through `encounter_facts.consume_rally` at every ally save settlement (human 2026-11-24). That sprint also shipped Zhael bard/diplomat Foretold Words (`check(mode="foretell_social")`, once per NPC per session, binding the next social check's DC; human 2026-11-24). Sprint orenthel-and-nythera-edges (#763) shipped Orenthel guardian Sheltering Light (5 ft), warrior Dawnward Strike (Hollow and undead) and Nythera mage Saltwind Casting; the human kept those over this clone's encounter-wide versions (2026-11-25). Sprint wounded-and-weary (2026-11-25) shipped Orenthel druid/beastcaller Cleansing Touch, Nythera skirmisher/rogue Unmoored Step (one own move at normal allowance provokes nothing, human 2026-11-25), Veythar cleric Arcana (derived live), Song of Rest as a real short-rest heal, and Orenthel bard's Song of Rest +1d6 and `orenthel_inspire_heal`. Pending clauses that depend on base mechanics include Wild Shape (Thyra +5 temp HP x3), crafting Focus cost (Aelora -1 x3), guardian/warden protective reactions (Aelora +2 Stamina x2), Marshal Rally temporary HP (Orenthel marshal). The Zhael paladin clause depends on the approved oath system's execution. Turn Undead/Hollow now resolves saves in combat, including the Valdris DC bonus. (b) A circumstance producer feeding check resolution for the 30 numeric circumstance-check clauses (commerce, hidden information, burial, evidence, repair, shelter and related conditions). See sprint archetype-synergies DATA `synergy-review.md`, retained-pending clause inventory; these categories do not exhaust its 103 pending clauses. Keep clauses pending until their production prerequisites exist.

## First share: friends play the story on TestFlight
Goal: "I think we need to really focus on the story to get people started" (human 2026-11-15): a friend on TestFlight plays a complete first episode and two more sessions without the DM improvising the plot: every box in `docs/milestones/13_first_share.md`. This checkout's line is Session 1; the divineruin2 clone adds Session 2, Session 3 and deployment sections to the same file.
Measure: python3 -c 'import re; print("distance=%d" % len(re.findall(r"^- \[ \] ",open("docs/milestones/13_first_share.md").read(),re.M)))'
Hosting (human 2026-11-16): a new DigitalOcean project `divineruin`, kept apart from the human's other projects; one s-2vcpu-4gb droplet runs server, agent and worker from `deploy/compose.yml`; DO managed Postgres and managed Valkey; media on Spaces (replaces the local media volume, so the object-storage adapter in `docs/ideas/object-storage-migration.md` becomes a card); about $60/mo before usage-billed providers. Images go to GHCR (`ghcr.io/paulingalls/divineruin-*`, human 2026-11-16), not legacy's `cordelia-beta` DOCR: DO allows one registry per account, and sharing it would couple the estates through legacy's Terraform state and a registry-wide pull credential that reaches legacy's BIPA-bearing images. Branch protection: answered by the develop milestone (met; `.xp/milestones-met.md`). Spend still needs the human's go before any billed resource is created.
Candidates: a carry choice for the fragment with a consequence in session 2 (needs a consumer on the Greyvale side first); re-choosing race and patron in a later session at Temple Row; an in-session patron whisper instead of the catch-up one; cut market beat 2 if a played session runs past 30 minutes; the human plays the build end to end and files what breaks.

## Core residuals

Goal: Close the remaining foundational documentation and voice character-creation criteria.
Measure: python3 -c 'import re; print("distance=%d" % (sum(len(re.findall(r"^- \[ \] ",open("docs/milestones/"+f).read(),re.M)) for f in ("00_doc_updates.md","01_core_systems.md"))))'
Candidates: Phase 0 Knowledge System listing and Phase 1 standard-array assignment by voice. The Phase 2 REST and mentor discovery, Phase 6 companion profiles, Phase 7 creature schema and Phase 10 terrain counts are reconciled in their phase docs.

## Economy

Goal: Finish prices, currency, rewards, reputation and the rest of the Phase 9 economy outside M9.6.
Measure: python3 -c 'import re; s=open("docs/milestones/09_economy.md").read(); b=re.search(r"^### Milestone 9\.6 .*?(?=^### |\Z)",s,re.M|re.S).group(0); print("distance=%d" % (len(re.findall(r"^- \[ \] ",s.replace(b,"",1),re.M))))'
Candidates: M9.1–M9.5 and M9.7–M9.10. Sequence pricing and loot with Phases 4–7 and supply/demand with the Phase 11 tick. M9.6 is measured under Selling.

## Selling

Goal: Let players sell goods and crafted items for engine-determined proceeds, with merchant inventory and a fence.
Measure: python3 -c 'import re; s=open("docs/milestones/09_economy.md").read(); b=re.search(r"^### Milestone 9\.6 .*?(?=^### |\Z)",s,re.M|re.S).group(0); print("distance=%d" % (len(re.findall(r"^- \[ \] ",b,re.M))))'
Candidates: M9.6 merchant pools, restock, buyback, priced sales, crafting sell decisions and the Aelora fence. Inputs include M9.2 pricing, M9.5 reputation and Phase 6 merchant roles.

## World loop

Goal: Run the persistent world clock, ticks, simulation, routing and god heartbeat.
Measure: python3 -c 'import re; print("distance=%d" % (len(re.findall(r"^- \[ \] (?!\[P12\] )",open("docs/milestones/11_world_loop.md").read(),re.M))))'
Candidates: M11.1–M11.6 and blocking decisions D-A (clock anchor), D-B (restock layer), D-C (worker placement), D-D (catch-up) and D-E (heartbeat budget). Phase 9 supplies economy inputs and Phase 8 supplies patrons. Criteria beginning with [P12] count under Story machinery and Season 1.

## Story machinery and Season 1

Goal: Run the scoped story engine and make Season 1 playable through it.
Measure: python3 -c 'import re; print("distance=%d" % (len(re.findall(r"^- \[ \] ",open("docs/milestones/12_story_content.md").read(),re.M))+len(re.findall(r"^- \[ \] \[P12\] ",open("docs/milestones/11_world_loop.md").read(),re.M))))'
Candidates: M12.1–M12.7, Phase 11 criteria beginning with [P12] and blocking decisions D-F (event scope), D-G (zone bands), D-H (drift clamp), D-I (campaign gates), D-J (god knowledge), D-K (god action tiers) and D-L (repeatable XP). A single boundary test can close the paired criteria for scoped occurrences (11:161 / 12:71), drift clamp (11:162 / 12:92) and delve respawn/contract board (11:164 / 12:138–139).

## Narrated-only mechanics

Goal: Settle the missing base mechanics in the engine and certify the remaining spoken combat behaviors.
Measure: python3 -c 'import re; s=open("docs/milestones/14_engine_completeness.md").read(); b=re.search(r"^### Milestone 14\.1 .*?(?=^### |\Z)",s,re.M|re.S).group(0); print("distance=%d" % (len(re.findall(r"^- \[ \] ",b,re.M))))'
Candidates: M14.1 reactions, spell ledger and missing spell effects, Rally, oaths, crafting, companion effects, world-risk integration and voice certification. Inputs include M9.1, Phase 11 and M15.1. Patron synergy clauses stay in M8.3.

## Gameplay systems

Goal: Deliver the remaining async, companion, guidance, creation, exploration and player resonance systems.
Measure: python3 -c 'import re; s=open("docs/milestones/14_engine_completeness.md").read(); b=re.search(r"^### Milestone 14\.2 .*?(?=^### |\Z)",s,re.M|re.S).group(0); print("distance=%d" % (len(re.findall(r"^- \[ \] ",b,re.M))))'
Candidates: M14.2 mini-quests, check-ins, quest hints, companion refusal, culture placement, Tier 2 locations, cross-session travel, bard performance and affect. Phase 11 supplies world state and M15.1 supplies authored inputs.

## Audio and HUD

Goal: Deliver designed audio navigation, spatial sound, adaptive music and glanceable HUD support.
Measure: python3 -c 'import re; s=open("docs/milestones/14_engine_completeness.md").read(); b=re.search(r"^### Milestone 14\.3 .*?(?=^### |\Z)",s,re.M|re.S).group(0); print("distance=%d" % (len(re.findall(r"^- \[ \] ",b,re.M))))'
Candidates: M14.3 audio compass, spatial DSP, music stems, navigation fallback and faction standing. Uses existing audio playback, location state and reputation.

## Multiplayer and social

Goal: Deliver the designed party, discovery, private voice and guild experiences.
Measure: python3 -c 'import re; s=open("docs/milestones/14_engine_completeness.md").read(); b=re.search(r"^### Milestone 14\.4 .*?(?=^### |\Z)",s,re.M|re.S).group(0); print("distance=%d" % (len(re.findall(r"^- \[ \] ",b,re.M))))'
Candidates: M14.4 group companion behavior, raids, encounter merge/fork, matchmaking, private audio, guilds and independent NPC agents. Depends on existing voice transport and the cost model.

## Platform

Goal: Enforce the designed consent, moderation and entitlements for player-facing operation.
Measure: python3 -c 'import re; s=open("docs/milestones/14_engine_completeness.md").read(); b=re.search(r"^### Milestone 14\.5 .*?(?=^### |\Z)",s,re.M|re.S).group(0); print("distance=%d" % (len(re.findall(r"^- \[ \] ",b,re.M))))'
Candidates: M14.5 structured PvP, moderation layers and Session Tone, and monetization. Uses the session, voice and discovery surfaces.

## Content coverage

Goal: Fill the remaining authored world, encounters and MVP story content.
Measure: python3 -c 'import re; print("distance=%d" % (len(re.findall(r"^- \[ \] ",open("docs/milestones/15_content_coverage.md").read(),re.M))))'
Candidates: M15.1 events, quests and hints, NPCs, locations, creature homes, gathering, undead, starter openings, prices and Sessions 4–5. Depends on the corresponding Phase 9, 11, 12 and 14 systems. Inventory role pools stay under Selling.
