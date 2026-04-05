# Documentation Index

Quick-reference index for all design docs. Use line ranges for targeted reads.

---

## product_overview.md (255 lines)

Vision, pitch, and high-level systems overview. Read first for context.

| Section | Lines | What's There |
|---|---|---|
| What This Is | 3-13 | Voice-first MMORPG pitch, Aethos setting |
| What Makes This an MMO | 15-27 | Shared persistent world, player economy, faction politics |
| Why Voice-First | 35-47 | Gameplay advantages of voice, target audience |
| What It Feels Like | 51-63 | Walkthrough of a typical session |
| The World | 67-91 | Aethos overview, Pantheon as game systems (10 gods) |
| How It Works | 96-144 | Three-layer DM architecture, voice pipeline, tech stack |
| Game Systems | 148-172 | 18 archetypes x 10 gods, combat, multiplayer scales |
| Monetization | 176-190 | Subscription model, unit economics, red lines |
| Where We Are | 194-217 | Current state, MVP to MMO path (7 steps) |
| The Hard Problems | 220-237 | Six key technical challenges |

---

## game_design_doc.md (1499 lines)

All player-facing systems. The largest doc — always read specific sections, not the whole thing.

| Section | Lines | What's There |
|---|---|---|
| Character Creation | 18-73 | Voice-conversation flow: Awakening → Origins → Calling → Devotion → Identity (10-15 min) |
| Class System | 76-199 | 18 archetypes across 6 categories x 10 gods = 180 combos |
| Progression System | 197-238 | Archetype Mastery (XP), Divine Favor (alignment), World Reputation |
| Game Mechanics | 241-321 | d20+mod vs DC, 15 skills in 3 groups, status effects, difficulty tiers |
| Session Structure | 325-416 | 30-90 min sessions, 5 phases, fluid entry, DM behavioral modes |
| Silent/Voiced Layers | 417-432 | Catch-Up (tap-based) vs Enter the World (voice) |
| Combat Design | 435-484 | Phase-based rounds, declarations, interrupts, sound as tactics, boss fights |
| Navigation | 488-542 | Intent-based movement, macro/micro, audio compass |
| NPC Design | 543-700 | Companion system (5 functions), 4 NPC tiers, relationships |
| Asynchronous Play | 700-1035 | Crafting, training, scouting, factions, god whispers, companion errands |
| The Economy | 1038-1081 | Silver-based currency (cp/sp/gc), earning channels |
| Death and Resurrection | 1084-1123 | Fallen → death saves → Mortaen's domain → return with escalating cost |
| PvP Design | 1126-1183 | Opt-in, structured, story-driven. Arena, territory, heists |
| Seasonal Arc Structure | 1187-1211 | Multi-season narrative with Veythar reveal |
| Content Moderation | 1214-1263 | 5 layers: DM, AI guardrails, voice analysis, reputation, party controls |
| Monetization | 1266-1348 | Subscription, battle pass, voice cosmetics, property system |
| Opening Experience | 1351-1483 | First 30 min flow: prologue → creation → normalcy → disruption → call to action |
| Open Design Questions | 1486-1499 | All marked resolved |

---

## technical_architecture.md (1499+ lines)

Implementation blueprint. The second largest doc.

| Section | Lines | What's There |
|---|---|---|
| Architecture Overview | 11-22 | Eight major layers |
| Language Architecture | 26-140 | Python (agent) + Bun/TS (everything else), monorepo structure |
| Client Architecture | 144-319 | Expo screens, HUD layers, data flow, audio mixing, performance targets |
| Voice Pipeline | 323-448 | STT (Deepgram), VAD (Silero + semantic), TTS (Inworld), LLM (Claude) |
| DM Agent Architecture | 452-754 | Layer 1: Voice Agent, Layer 2: Background Process, Layer 3: Toolset. Prompt architecture (static/warm/hot) |
| Orchestration Design | 774-958 | tts_node voice router, tag format, multi-player input arbitration, error recovery, session lifecycle |
| Transport (LiveKit) | 960-1035 | SFU model, room capacity, multiple agents per room |
| Game Engine Layer | 1038-1068 | Rules engine (pure functions), world state manager |
| Agent Layer | 1072-1118 | NPC tiers, background world simulation |
| Multiplayer Architecture | 1122-1289 | Ventriloquism, multi-player input, room structure, DM merge/fork |
| Infrastructure | 1293-1391 | MVP infrastructure, cloud platform, cost |
| Development Priorities | 1394-1413 | 18 ordered priorities |
| Testing Strategy | 1417-1499 | Five tiers: Infrastructure, Rules Engine, DM Behavior, Experience, Content |

---

## audio_design.md (~800 lines)

Soundscapes, SFX, music, voice design.

| Section | Lines | What's There |
|---|---|---|
| Audio Philosophy | 18-50 | "Sound Is Sight", four channels, ducking rules |
| Environmental Soundscapes | 50-200 | Layered ambient (foundation + detail + motion + seasonal), corruption audio |
| Sound of the Hollow | 200-280 | Hollow breaks rules: reversed sounds, impossible frequencies |
| Combat Audio | 280-380 | Spatial positioning, intensity layers, boss fights, critical hits |
| Voice Design | 380-500 | DM narrator, companion voices (Kael, Sable), god voices, NPC pools |
| Music System | 500-600 | Adaptive stems (8 types), crossfade rules, layering |
| UI Sounds | 600-680 | Physical-feeling (wood, leather, parchment), dice rolls |
| AI Generation Prompts | 680-750 | Prompts for generating every audio asset category |
| MVP Asset Inventory | 750-end | Complete asset list with IDs and generation prompts |

---

## world_data_simulation.md (948 lines)

DB schemas, JSON entity formats, world sim rules, content style guide.

| Section | Lines | What's There |
|---|---|---|
| Content Authoring Format | 10-21 | JSON schemas, Tier 1 (authored) vs Tier 2 (generated) |
| Location Schema | 23-102 | Full JSON: conditions, hidden elements, exits, ambient sounds |
| NPC Schema | 104-189 | Personality, speech style, knowledge gating, schedules, voice mapping |
| Item Schema | 191-239 | Mechanical effects, economic properties |
| Quest Schema | 241-349 | State machine: stages, branches, completion conditions, world effects |
| Event/Trigger Schema | 350-399 | Trigger conditions, probability, cooldown, priority |
| Faction Schema | 400-457 | Reputation tiers with gameplay effects, relationships |
| Content Style Guide | 460-617 | Write for the ear, description limits, NPC content, Hollow wrongness |
| World Simulation Rules | 620-806 | World clock (1:1), 4 simulation layers (per-minute through event-driven) |
| Data Model | 810-904 | PostgreSQL + Redis: 10 content tables, 12 state tables, 7 Redis patterns |
| MVP Content Scope | 908-934 | ~20 locations, ~25 NPCs, ~40 items, ~5 quests, ~18 events |

---

## mvp_spec.md (~800 lines)

Scope, session arc, success criteria, buildable entities.

| Section | Lines | What's There |
|---|---|---|
| What the MVP Must Prove | 10-23 | Six core questions |
| MVP Scope Summary | 25-60 | One culture, one city, one wilderness, one story arc |
| The Greyvale Story Arc | 60-300 | Session-by-session (5 sessions): arrival → investigation → journey → ruins → revelation |
| MVP Entities | 300-450 | Lists of locations, NPCs, items, quests, events |
| Success Criteria | 450-550 | Quantitative (latency, accuracy, completion rate) and qualitative |
| Playtest Structure | 550-650 | Internal → Alpha → Beta rounds |
| What We're NOT Building | 650-700 | Explicit scope cuts |
| Appendix: Buildable Entities | 700-end | Full JSON for every MVP entity |

---

## aethos_lore.md (~1000 lines)

World history, gods, races, cultures, the Hollow, creature taxonomy.

| Section | Lines | What's There |
|---|---|---|
| The Core Mystery | 19-22 | A god broke the world trying to save it |
| Cosmology | 24-80 | The Veil, the Wellspring, the Sundering, the Hollow |
| Veythar's Secret | 80-200 | The guilty god: Resonance Lattice, Attenuation Spheres, Invocation |
| The Ten Gods | 200-500 | Full profiles: domains, personalities, game governance |
| Veythar's Artifacts | 500-560 | Three artifacts and their locations |
| Races of Aethos | 560-650 | 6 races: Draethar, Elari, Korath, Vaelti, Thessyn, Human |
| Cultures & Regions | 650-800 | 8 cultures with regions and customs |
| The Hollow | 800-900 | Creature taxonomy: Drift, Rend, Breach, Apex tiers |
| Geography | 900-end | Voidmaw, Ashmark, major regions, Greyvale |

---

## cost_model.md (277 lines)

Per-session cost breakdowns, subscriber economics.

| Section | Lines | What's There |
|---|---|---|
| Pricing Inputs | 10-35 | Current prices (Feb 2026): Deepgram, Inworld, Claude, LiveKit |
| Session Model | 38-68 | Solo vs party: speaking time, exchanges, output chars |
| Per-Session Cost | 71-108 | Solo $0.40, Party per-player $0.14 |
| Monthly Economics | 111-138 | Heavy/moderate/light x solo/party margins |
| Cost Distribution | 144-161 | TTS 53%, STT 16%, LLM 16%, Transport 15% |
| Optimization Paths | 164-195 | TTS Mini, caching, model tiering, self-host |
| Scale Projections | 199-224 | 10K subs: 84% margin. 100K: 89% |
| TTS Evaluation | 265-273 | Provider comparison: Inworld, Cartesia, Chatterbox, Dia2 |

---

## milestones/ (10 phase files, ~1580 lines total)

Game mechanics implementation milestones. See `milestones/README.md` for dependency graph and parallelism guide.

| File | Phase | Milestones |
|---|---|---|
| `00_doc_updates.md` | Doc fixes | 4 — CLAUDE.md overhaul, INDEX.md indexes, economy fixes, cross-references |
| `01_core_systems.md` | Core | 6 — attributes, skills, resources, leveling, training, errands |
| `02_archetypes.md` | Archetypes | 5 — chassis, abilities, specialization, spells, mentors |
| `03_magic.md` | Magic | 4 — resonance, hollow echo, spell catalog, concentration |
| `04_combat.md` | Combat | 6 — 4-beat phases, actions, conditions, death, dramatic dice, social/travel |
| `05_crafting.md` | Crafting | 4 — recipes, workspaces, quality, durability |
| `06_npcs.md` | NPCs | 4 — stat blocks, settlements, mentors, companions |
| `07_bestiary.md` | Bestiary | 4 — creature schema, regional catalog, hollow creatures, loot/encounters |
| `08_patrons.md` | Patrons | 3 — profiles, abilities, synergies |
| `09_economy.md` | Economy | 3 — currency, merchant pricing, quest rewards |

---

## brand_spec.md (250 lines)

Design tokens, UI patterns, art direction. Read before any UI work.

| Section | Lines | What's There |
|---|---|---|
| Colors | 9-34 | Foundation, text, accent tokens (12 colors with hex) |
| Typography | 39-57 | Cormorant Garamond, Crimson Pro, IBM Plex Mono |
| Type Scale | 66-75 | 7 sizes: display (48px) to caption (10px) |
| Spacing & Radius | 78-90 | Radius 6-27px, Space 4-48px |
| Shadows & Glows | 94-105 | Hollow glow, text glow, elevation shadows |
| Grain Overlay | 109-120 | SVG fractalNoise at 3% opacity |
| UI Patterns | 124-186 | Surface hierarchy, text roles, HUD, special treatments |
| Art Direction | 189-221 | Dissolving ink style, near-monochrome + 3 accent washes |
| Logo | 224-238 | Cormorant Garamond 300, all-caps, parchment |
| Brand Principles | 242-250 | 6 principles |

---

## player_resonance_system.md (570 lines)

Voice affect analysis for DM adaptation.

| Section | Lines | What's There |
|---|---|---|
| The Problem | 14-18 | Claude is deaf to how the player speaks |
| The Solution | 19-28 | Affect Analyzer: transcript metadata + raw audio + behavior |
| Signal Sources | 30-84 | Deepgram timestamps/confidence, AudioFrame RMS, transcript patterns |
| The Affect Vector | 88-157 | JSON schema: engagement, energy, interaction_style, latency |
| Architecture | 160-287 | Parallel branch via asyncio.Queue, stt_node override, never adds latency |
| DM Behavioral Shifts | 291-342 | Affect→DM response mapping, Hollow intensity modulation |
| Implementation Plan | 346-480 | 4 phases: transcript-only → audio → behavioral → tuning |
| Cost Impact | 482-493 | ~$0.006 per session |
| Resolved Questions | 507-570 | Deepgram capabilities, calibration, privacy |

---

## story_vigil_of_greyhaven.md (365 lines)

Narrative fiction piece. Demonstrates Hollow creature taxonomy in action and the world's tone.

| Section | Lines | What's There |
|---|---|---|
| Day 1-40 | 9-324 | Kael Thornridge's squad holds Greyhaven: shadelings → mawlings → hollowed knight → veilrender |
| Epilogue | 326-365 | Bardic song memorializing the seven defenders |

---

## image_prompt_library.md (380 lines)

Nano Banana 2 prompts for all art categories.

| Section | Lines | What's There |
|---|---|---|
| Style Foundation | 6-26 | Core keywords, always-include, avoid-list |
| Accent Color Rules | 28-39 | Three colors: Teal, Ember, Gold with hex and prompt language |
| Character Portraits | 43-108 | Companion, NPC, player character prompts |
| Location Illustrations | 111-174 | Town, wilderness, corrupted, interior prompts |
| Item & Object Art | 178-221 | Weapon, artifact, quest item prompts |
| Story Moments | 224-272 | Combat, god contact, hollow encounter prompts |
| UI & Marketing | 278-315 | App store, social media, loading screen prompts |
| Consistency Tips | 319-350 | 6 tips, aspect ratio table |
| Production Pipeline | 354-380 | Batch consistency, post-processing, priorities |

---

## map_generation_prompt.md (99 lines)

Single prompt for generating the Aethos world map.

| Section | Lines | What's There |
|---|---|---|
| Prompt | 7-54 | Full map generation prompt: regions, corruption gradient, style |
| Usage Instructions | 58-68 | How to use with AI generators |
| Variations | 70-83 | Artistic, cartographic, darker, lighter |

---

## divine_ruin_missing_prompts.md (363 lines)

Audio asset generation prompts not covered in audio_design.md.

| Section | Lines | What's There |
|---|---|---|
| Combat SFX (CMB-002–022) | 8-134 | Sword, blunt, arrows, spells, hits, crits, status effects, enemy signatures |
| Dice Sounds | 137-151 | Standard roll, skill check |
| Music Stems | 153-180 | Tension, combat boss, sorrow, title themes |
| Stingers (STG-001–009) | 183-249 | Quest, level up, faction, god whisper variants, death, session |
| UI Sounds (UI-002–010) | 253-301 | Cancel, error, async complete, menu, scroll, confirm |
| Sable's Sounds | 304-322 | 5 emotional states as animal sounds |
| Environment (ENV-004–008) | 326-352 | Millhaven variants, wilderness night |

---

## agent_handoffs_and_scenes.md (923 lines)

Multi-agent architecture, LiveKit handoffs, scenes, and structured play.

| Section | Lines | What's There |
|---|---|---|
| Problem Statement | 6-27 | Why the monolithic agent doesn't work (prompt bloat, fragile transitions) |
| LiveKit Agent Handoffs | 29-70 | Tool-return (LLM-driven) and programmatic handoff mechanisms |
| Proposed Agent Architecture | 72-383 | Agent graph: Prologue → Creation → Onboarding → City/Wilderness/Dungeon/Combat |
| Context Transfer Strategy | 385-403 | Template-based summaries, session.userdata persistence |
| Structured Play: Scenes and Play Trees | 405-528 | Scenes as standalone entities, beat progression, play tree structure |
| LiveKit Rooms as Shared Spaces | 530-616 | Room architecture, multi-agent rooms, data channels |
| Development Milestones (H.1-H.8) | 618-end | Agent handoff milestones — all complete |

---

# Game Mechanics Docs (docs/game_mechanics/)

Canonical specifications for all game systems. These supersede the summary sections in `game_design_doc.md`.

---

## game_mechanics/game_mechanics_core.md (1103 lines)

Foundational systems: attributes, skills, resources, leveling, async activities.

| Section | Lines | What's There |
|---|---|---|
| Document Status | 9-47 | Status and update timestamps for all mechanics files |
| Implementation Directive | 49-126 | LLM is narrator, not engine — rules engine returns narrative-ready packets |
| Core Resolution Mechanic | 128-144 | d20 + modifier vs DC, result packets with narrative cues |
| Attributes | 146-186 | 6 attributes, modifier math, attribute increases at L4/8/12/16/20 |
| Proficiency Bonus | 188-205 | Bounded scale: +1 (L1-6), +2 (L7-13), +3 (L14-20) |
| Skill System | 207-480 | 20 skills, 4 tiers (Untrained/Trained/Expert/Master), use counters, advancement |
| Difficulty Class (DC) Scale | 482-511 | Trivial (5) through Legendary (28), auto-fail thresholds |
| Hit Points | 513-543 | HP formula with half-CON growth rule |
| Resource System — Stamina and Focus | 545-588 | Dual pools, archetype assignments, recovery rates |
| Experience Points and Leveling | 590-685 | ~100 XP/session, 20-level progression, unified milestones |
| Async Training System | 687-816 | Variable-duration cycles, midpoint decisions, micro-bonuses |
| Companion Errands | 818-909 | 4 errand types (Scout/Social/Acquire/Relationship), risk-based returns |
| Async Activity Concurrency | 911-931 | 3 independent slots: Training + Crafting + Errand |
| Combat, Conditions & Death | 933-937 | Cross-reference to game_mechanics_combat.md |
| Character Creation | 939-1099 | 5 narrative choices → auto-computed attributes, equipment, spells |
| Design Decisions Log | 1101-end | Cross-reference to game_mechanics_decisions.md |

---

## game_mechanics/game_mechanics_combat.md (1060 lines)

Combat resolution, status effects, death, social encounters, travel, gathering.

| Section | Lines | What's There |
|---|---|---|
| Dramatic Dice System | 11-87 | Scarcity-based d20 animation (0-2 per combat), dramatic context rules |
| Combat System — Phase-Based | 89-201 | 4-beat phases (Declaration/Resolution/Narration/Wrap), no turn order |
| Combat Math | 203-261 | Attack rolls, AC by armor, weapon damage, cantrip scaling |
| Status Effects | 263-324 | 15+ conditions (Hollowed, Stunned, Prone, etc.) with mechanical effects |
| Resting | 326-338 | Short rest (Stamina full, Focus half), Long rest (all recovery) |
| Death and Dying | 340-613 | Death saves, Mortaen's domain, escalating costs, Hollowed Death, party wipe |
| Social Encounter Resolution | 615-846 | 3-tier system, disposition-as-DC, Diplomat de-escalation |
| Travel and Exploration | 848-971 | 3 travel modes, navigation checks, exhaustion, camping |
| Gathering and Resource Discovery | 973-end | Skill-gated harvesting, regional resource tables, discovery moments |

---

## game_mechanics/game_mechanics_archetypes.md (1224 lines)

18 archetype profiles with abilities, specializations, and spell acquisition.

| Section | Lines | What's There |
|---|---|---|
| Archetype Profiles | 9-415 | Overview of 18 archetypes: Martial(3), Arcane(3), Primal(3), Divine(3), Shadow(3), Support(3) |
| All Archetype Profiles — Complete | 417-1014 | Individual stat blocks: HP, armor, skills, passives, actives, reactions, milestones |
| Core + Elective Ability Model | 1016-1087 | Core (always available) vs Elective (chosen at L4/L8), reaction abilities |
| Spell Acquisition — Three Tracks | 1089-1152 | Core spells, Training study cycles, Discovery (scrolls/mentors) |
| Martial Mentor-Style System | 1154-end | Technique variants via NPC mentors, cultural attribution, 2-3 session loops |

---

## game_mechanics/game_mechanics_magic.md (542 lines)

Three magic sources, Resonance system, 87 spells.

| Section | Lines | What's There |
|---|---|---|
| Magic System — Three Sources and Resonance | 9-295 | Arcane/Divine/Primal multipliers, Resonance states, Hollow Echo, Veil Wards, racial interactions |
| Arcane Spell Catalog | 297-376 | 30 arcane spells with Focus costs and Resonance generation |
| Divine Spell Catalog | 378-450 | 28 divine spells: healing, protection, anti-Hollow |
| Primal Spell Catalog | 452-527 | 29 primal spells: terrain manipulation, area denial |
| Three-Source Catalog Comparison | 529-end | Side-by-side comparison of spell pools and Resonance profiles |

---

## game_mechanics/game_mechanics_crafting.md (587 lines)

Recipe learning, crafting resolution, durability, item catalog.

| Section | Lines | What's There |
|---|---|---|
| The Crafting Principle | 9-15 | Design philosophy: crafting mirrors spell acquisition |
| Crafting Resolution | 17-108 | 4 quality outcomes (Exceptional/Success/Partial/Failure), DC checks |
| Recipe System | 110-261 | Recipe slots, 3 acquisition tracks, experimentation |
| Crafting Categories | 263-341 | 7 categories with tier progression |
| Item Catalog | 343-517 | Complete pricing aligned to 1 sp = 1 day labor anchor |
| Durability System | 519-551 | Fragile/Standard/Reinforced/Masterwork, Hollow double corrosion |
| Async Crafting Activity | 553-583 | Concurrent crafting with variable timelines |
| Design Decisions Log | 585-end | Crafting & item decisions (36-43) |

---

## game_mechanics/game_mechanics_npcs.md (885 lines)

NPC schemas, role archetypes, mentors, settlements, companions.

| Section | Lines | What's There |
|---|---|---|
| NPC Schema | 11-63 | Extended stat blocks with social/economic/schedule/mentor layers |
| Role Archetype Templates | 65-377 | 12 roles: Merchant(7 subtypes), Blacksmith, Innkeeper, Healer, Scholar, Guard, etc. |
| Mentor Registry | 379-542 | Named mentors teaching martial variants and spells across cultures |
| Settlement Templates | 544-595 | Hamlet/Village/Town/City/Capital NPC distribution |
| Encounter Design: Hostile NPC Groups | 597-628 | Bandit Ambush, Ashmark Patrol, Cult Cell, Hollow-Corrupted templates |
| Companion Mechanical Framework | 630-881 | 4 companions (Kael/Lira/Tam/Sable), 75% player HP scaling, relationship tiers |
| Design Decisions Log | 883-end | NPC & companion decisions (30-35, 54-57) |

---

## game_mechanics/game_mechanics_bestiary.md (1234 lines)

Creature stat blocks, Hollow and natural creatures, materials, encounters.

| Section | Lines | What's There |
|---|---|---|
| Creature Stat Block Schema | 9-137 | Universal template: attributes, attacks, passives, loot, hollow fields |
| Hollow Creatures | 139-614 | 9 Hollow entities (Shadeling through The Architect), special mechanics |
| Natural Creatures | 616-1152 | 38+ creatures across 6 regions, Tier 1-3 |
| Material Catalog Summary | 1154-1199 | Material values and crafting uses for all creature drops |
| Encounter Building Guidelines | 1201-1230 | Tier-based scaling, solo player math, companion effectiveness |
| Design Decisions Log | 1232-end | Bestiary decisions (24-29) |

---

## game_mechanics/game_mechanics_patrons.md (366 lines)

10 divine patrons with 4-layer mechanical system.

| Section | Lines | What's There |
|---|---|---|
| Divine Patron System | 9-end | 4-layer architecture (Gift/Resonance/Favor/Synergy), 10 patron profiles (Veythar, Kaelen, Aelora, Thyra, Syrath, Orenthel, Valdris, Mortaen, Nythera, Zhael), Unbound Path, favor tracking, archetype synergies |

---

## game_mechanics/game_mechanics_decisions.md (186 lines)

72 locked design decisions with reasoning. Master reference for settled choices.

| Section | Lines | What's There |
|---|---|---|
| Core Systems, Combat & Character Creation | 9-77 | Decisions 1-53: bounded accuracy, skill tiers, resources, combat phases |
| Bestiary & Materials | 79-93 | Decisions 24-29: tier system, material drops, harvesting |
| NPCs, Mentors & Companions | 95-117 | Decisions 30-57: NPC templates, mentors, companions, death |
| Crafting & Items | 119-138 | Decisions 36-43: recipe system, quality, durability |
| Async Activities | 140-149 | Decisions 58-61: errand models, concurrency, risk |
| Racial Traits & Level Progression | 151-156 | Decisions 62-63: attribute bonuses, Thessyn adaptation |
| Social Encounter Resolution | 158-167 | Decisions 64-67: social tiers, disposition mechanics |
| Dramatic Dice System | 169-172 | Decision 68: rare visible rolls, tension management |
| Travel, Exploration & Gathering | 174-181 | Decisions 69-71: travel modes, gathering, node discovery |
| Economy Reconciliation | 183-end | Decision 72: 1 gc = 10 sp, matching lore bible |

---

## game_mechanics/game_mechanics_economy.md (~280 lines)

Canonical economy specification. Currency system, pricing tables, merchant formulas, quest rewards, and gaps for Phase 9.

| Section | Lines | What's There |
|---|---|---|
| Currency System | 7-12 | Three-tier decimal: cp/sp/gc at 10:1 ratios |
| Economic Anchor | 14-22 | 1 sp = 1 day unskilled labor, wage scale benchmarks |
| Canonical Price Tables | 26-115 | 60+ items: food, weapons, armor, gear, spell components |
| NPC Services | 119-137 | Healing, research, identification, resurrection pricing |
| Workspace Rental | 141-149 | Workshop/forge/lab daily rates, disposition discounts |
| Crafting & Repair | 153-167 | Commission tiers, repair pricing by item tier |
| Mentor Training Fees | 171-177 | Fee ranges by mentor renown, quest-gated exceptions |
| Starting Gold | 181-185 | Per-archetype starting wealth, purchasing power analysis |
| Merchant Pricing Formula | 189-199 | Disposition modifiers, faction reputation stacking |
| Quest Reward Tiers | 203-210 | Tier 1/2/3 reward ranges by content difficulty |
| Systems Not Yet Specified | 216-end | 7 systems needing design before Phase 9 implementation |
