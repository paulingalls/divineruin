# Documentation Index

Run `uv run python scripts/doc_index.py --write` after editing docs. The test compares
this file with the regenerated result. Scope: every regular `docs/**/*.md` file,
including nested directories; `docs/INDEX.md` is explicitly excluded. Non-Markdown
assets and source files are excluded. `decisions/`, `ideas/`, `milestones/` and
`mockups/` are listed by path and line count only; every other doc gets a section
table. A doc in a new top-level directory fails generation until it is given a group.
Detailed tables use `##` headings, or `###` headings when a document has one wrapping
`##`. Ranges are inclusive. Empty descriptions in detailed entries need a human summary.

Start with `product_overview.md` for the vision, `game_design_doc.md` for player
systems, and `milestones/README.md` for the implementation dependency graph.

# Core design

## aethos_lore.md (1750 lines)

World history, gods, races, cultures, the Hollow, creature taxonomy.

Additional topics: Cosmology: The Veil, the Wellspring, the Sundering, the Hollow; Veythar's Artifacts: Three artifacts and their locations; The Hollow: Creature taxonomy: Drift, Rend, Breach, Apex tiers

| Section | Lines | What's There |
|---|---|---|
| About This Document | 3-18 | Purpose of the lore bible, related documents, implementation note |
| The Core Mystery | 19-24 | A god broke the world trying to save it |
| The Cosmology of Aethos | 25-299 | The Veil, Wellspring, Sundering, and Hollow |
| Veythar, the Lorekeeper | 300-548 | The guilty god: Resonance Lattice, Attenuation Spheres, Invocation |
| The Layers of the Mystery | 549-565 | The mystery's reveal layers, from the breach to Veythar's guilt, and player reactions |
| The Deep Future — The Wellspring Question | 566-581 | Endgame choice: reach for the Wellspring or seal the Veil |
| The Pantheon of Aethos | 582-804 | Full profiles: domains, personalities, game governance |
| The Geography of Aethos | 805-1146 | Voidmaw, Ashmark, major regions, Greyvale |
| The Peoples of Aethos | 1147-1388 | Six races and their distinct histories and cultures |
| Deeper Cultural Detail | 1389-1547 | Languages, customs, ceremonies, trade, and the lived texture of mortal life. |
| The History Before the Sundering | 1548-1632 | What was Aethos like before the invasion? |
| The Original Creators | 1633-1728 | Who or what made Aethos and the gods? |
| Open Lore Questions | 1729-1750 | Unsettled history and cosmology questions |

---

## agent_handoffs_and_scenes.md (126 lines)

Shipped agent flow, mode handoffs, scene context, and H.1–H.8 history.

| Section | Lines | What's There |
|---|---|---|
| Agent flow | 7-48 | Entry chain, exploration, combat, and focused mode agents |
| Context transfer and reconnection | 49-59 | Session state and handoff context |
| Scenes and structured play | 60-67 | Quest scenes, Stage context, and beat hints |
| LiveKit rooms and multiplayer | 68-74 | Current session model and shared-room proposal |
| Development Milestones | 75-126 | Original H.1–H.8 plan and shipped outcomes |

---

## agent_strict_mode.md (494 lines)

Proposed continuation of ADR 0008: retain verbs and typed nouns, and generate selected
complex arguments in separate strict requests. Live provider and LiveKit feasibility
probes succeeded; voice latency remains a release gate. Measured 2026-09-18.

Additional topics: Luna evidence and production route: Seeded 27-case Luna matrix, 2026-09-20 GPT-5.6 decision, 2026-09-22 GPT-6 Luna route and rates

| Section | Lines | What's There |
|---|---|---|
| 1. Recommendation | 18-35 | Strict input guarantees, existing local validation, tool results as a separate contract |
| 2. What strict actually protects | 36-71 | Strict constrains tool names and arguments, not tool results or action legality |
| 3. Diagnosis and fresh evidence | 72-132 | Current counts, live failures, production model mismatch, unsuccessful simplifications, successful request partition |
| 4. The two requests | 133-195 | Fixed per-mode policy, selection and argument generation, LiveKit feasibility probe |
| 5. Integration and execution invariants | 196-243 | Tool scoping, call IDs, batches, cancellation, visible failure, request accounting |
| 6. Cache, latency, and cost | 244-295 | Measured preliminary timings, warmup, paired voice benchmark, go/no-go conditions |
| 7. Verification and rollout | 296-357 | Fault injections, implementation sequence, strict-off inventory, rollback |
| 8. Alternatives and boundaries | 358-376 | Rejected approaches, reproduction procedure, limits of the evidence |
| 9. Reproducing the research | 377-407 | Commands to rerun the probe and the request partition |
| 10. Seeded Luna gameplay evidence | 408-448 | 27-case seeded Luna acceptance run, 2026-09-20, and its results |
| 11. Production decision | 449-467 | On 2026-09-20 the human approved GPT-5.6 Luna for the current production rollout. |
| 12. GPT-6 Luna route (2026-09-22) | 468-494 | Default route moves to gpt-6-luna; rates and paid acceptance results |

---

## agent_tool_surface.md (643 lines)

Strict tool-schema limits and context timing, measured live against trunk `08fa9b8`
(2026-09-04). Design source for ADR 0008 (sum-typed verbs, `next` in results) and for
story-019. Answers "right information / right action at the right time" for the DM agent.

Additional topics: Verbs take sum types: The schema rules + per-verb rewrites (check, begin_activity, declare_phase, activate, travel, enter_mode); When a verb set grows: Split criteria: eval-driven, not count-driven; Right information at the right time: Layer-by-volatility placement rule; the ACTIVE COMBAT staleness bug; Right action at the right time: Why per-turn tool scoping thrashes the cache; the NOW block + `next` field; Plugin constraints and escape hatches: raw_schema, non-strict mixing, what LiveKit emits

| Section | Lines | What's There |
|---|---|---|
| 0. Summary | 17-54 | The six findings: sum types, exact limits, 2-4 unions/agent, state machine not tool list, layer placement, no tool search |
| 1. What trunk sends today | 55-95 | Per-agent tool + union counts; the bags of optionals |
| 2. The limits, precisely | 96-136 | 20 strict tools, 16 unions (recursive), ~13-nullable object cliff, additionalProperties/enum-null/oneOf rejections, and what does vs doesn't traverse `$ref` |
| 3. Diagnosis | 137-158 | Why folding nouns into verbs produced product-types-with-nulls |
| 4. Design | 159-405 | Schema rules for sum-typed verbs, growing verb sets, right information and action at the right time, plugin escape hatches |
| 5. Sequencing | 406-463 | Order of work for story-019 (Sprint 47, ahead of the M29 restore) |
| 6. Risks and how to measure them | 464-485 | Tool-selection eval, cache-read assertion |
| 7. Open questions for the human | 486-500 | query_info shape, enter_mode, resolve_phase-as-advance-verb, creation agent model |
| Appendix — how this was measured | 501-528 | The schema walk and the live limit probes |
| 8. Cost recommendations | 529-643 | Cache protection, fewer turns/session, models, TTS, a cost budget test |

---

## agent_verbs_and_stages.md (499 lines)

Tooling and context architecture. Refines technical_architecture's three-layer prompt model.
Design source for the Phase-2 enabler refactor milestones. Recharacterizes tools as a small
core verb vocabulary, locations as dynamically-assembled stages.

| Section | Lines | What's There |
|---|---|---|
| 1. Why this exists (the problem) | 11-32 | The limits: tool ceiling, duplicated consequence logic, content-driven tool growth |
| 2. The core model: Sense / Act / Resolve | 33-51 | The three operation kinds; Resolve is never a tool |
| 3. Sense has two channels: push (the Stage) and pull (`query_info`) | 52-72 | The Stage (push) vs `query` (pull); the cost/latency line; three ceiling levers |
| 4. Acts are verbs, never nouns | 73-111 | Decision test, verb test, description discipline, standard Act shape + ActResult |
| 5. Resolve is never a tool | 112-135 | Fires inside Acts; resolve_milestone removed (grant=Resolve, choice=select); report back richly |
| 6. Agents vs Stages — two axes, very different costs | 136-179 | Two axes, handoff/cache cost; collapse region agents into one exploration agent |
| 7. The Stage in detail | 180-315 | Cold/warm/hot tiers, placement discriminator, numbers→bands, check(skill,target), stage schema |
| 8. The loop and the three actors | 316-339 | Stage→Decide→Act→Resolve→Stage; user/LLM/world; coherence guardrail; event bus |
| 9. Worked example — the Accord Guild Hall | 340-369 | Real content rendered through the schema |
| 10. Verb vocabulary | 370-425 | 12 core verbs + mode-local sets; what each replaces; what folded |
| 11. Migration sequence (green throughout) | 426-444 | Five green-throughout steps; M2.4 adds zero tools |
| 12. Decisions (resolved) and deferrals | 445-486 | Resolved seams + deferrals with insertion points |
| 13. Relationship to the Golden Rules | 487-499 | How the model maps to the seven rules |

---

## audio_design.md (718 lines)

Soundscapes, SFX, music, voice design.

Additional topics: UI Sounds: Physical-feeling (wood, leather, parchment), dice rolls; AI Generation Prompts: Prompts for generating every audio asset category

| Section | Lines | What's There |
|---|---|---|
| About This Document | 3-17 | Audio as the experience; creative guide and prompt reference; related documents |
| Audio Philosophy | 18-47 | "Sound Is Sight", four channels, ducking rules |
| The Audio Stack — What the Player Hears | 48-77 | Seven-layer priority hierarchy and mixing rules |
| Environmental Soundscapes | 78-178 | Layered ambient (foundation + detail + motion + seasonal), corruption audio |
| The Sound of the Hollow | 179-229 | Hollow breaks rules: reversed sounds, impossible frequencies |
| Voice Design | 230-326 | DM narrator, companion voices (Kael, Sable), god voices, NPC pools |
| Combat Audio | 327-378 | Spatial positioning, intensity layers, boss fights, critical hits |
| Music Design | 379-432 | Adaptive stems (8 types), crossfade rules, layering |
| UI and Feedback Audio | 433-470 | Non-diegetic UI sound principles and categories |
| Spatial Audio Design | 471-496 | MVP stereo positioning and post-MVP binaural 3D audio |
| Async Audio Design | 497-527 | The Catch-Up layer uses pre-rendered audio, not live voice. This audio has distinct design requirements from the real-time sync experience. |
| Audio Asset Inventory — MVP Requirements | 528-669 | Complete asset list with IDs and generation prompts |
| Audio Technical Requirements | 670-703 | Format, spatialization, mixing, and playback requirements. |
| Open Audio Design Questions | 704-718 | Middleware, binaural library, generation consistency, accessibility and other open questions |

---

## audio_sa3_noise_investigation.md (242 lines)

Investigation of Stable Audio 3 noise-only outputs and the resolved production path.

| Section | Lines | What's There |
|---|---|---|
| 1. Objective when this started | 13-26 | M22 story-003 goal: regenerate 20 legacy SFX with the SA3 generator |
| 2. Expected vs. observed | 27-37 | Expected recognizable SFX; every clip was noise, from wrapper and official CLI |
| 3. The core contradiction | 38-48 | Same machine and package worked at M17 hours earlier |
| 4. Environment facts (verified) | 49-92 | `git+https://github.com/Stability-AI/stable-audio-3.git@ea9ba361f9e58da6afed1304657e20fda701a9a4` |
| 5. What was tried, and the result (all NOISE) | 93-108 | Five generation attempts, all noise; causes ruled out |
| 6. Dead ends explored | 109-124 | Open 1.0 harness cannot load SA3; Open 1.0 presets do not apply |
| 7. Strongest un-run lead (recommended first step next session) | 125-140 | Check whether checkpoint weights bind to the model |
| 8. Other un-run leads | 141-158 | System updates, replaying committed takes, recovering the M17 invocation |
| 9. Key paths / artifacts | 159-172 | `scripts/audio/generate_spell_sfx_stableaudio.py` |
| 10. State of the working tree / sprint (so the next session isn't surprised) | 173-188 | Which stories are committed and which edits are uncommitted |
| 11. Recommendation | 189-198 | Treat as environment forensics; verify weight binding first |
| 12. RESOLUTION (follow-up session, 2026-07-05 ~22:50) | 199-242 | Every lead above was run to ground; the stack works again with **zero changes**. |

---

## audio_sfx_pipeline.md (547 lines)

Sound-effect generation, asset keys, regeneration, and integration guidance.

| Section | Lines | What's There |
|---|---|---|
| 1. Goal & Principle | 3-20 | M17 goal: every spell cast plays an engine-emitted, generatable SFX |
| 2. Service Evaluation | 21-36 | ElevenLabs, Stable Audio 3, AudioGen and procedural synth compared on cost, licensing, quality |
| 2.5 Existing Divine Ruin Audio Pipeline (prior work — the actual recommended path) | 37-170 | Existing Stable Audio harness; SA3 Small SFX upgrade; one pipeline for all audio |
| 3. Recommendation | 171-252 | Quality gates the choice; bake-off and SA3-medium spike findings |
| 4. Keying Scheme (FROZEN CONTRACT for stories 002/003) | 253-392 | sound_id keyed by effect family; 7-key MVP palette; all 87 spells mapped |
| 5. Regenerate Recipe | 393-507 | Recommended Stable Audio path, ElevenLabs secondary, procedural fallback |
| 6. Integration Notes for Stories 002/003 | 508-547 | Asset SSOT location, bundling, family coverage matrix |

---

## brand_spec.md (249 lines)

Design tokens, UI patterns, art direction. Read before any UI work.

Additional topics: Colors: Foundation, text, accent tokens (12 colors with hex); Typography: Cormorant Garamond, Crimson Pro, IBM Plex Mono; Type Scale: 7 sizes: display (48px) to caption (10px); Spacing & Radius: Radius 6-27px, Space 4-48px; Shadows & Glows: Hollow glow, text glow, elevation shadows; Grain Overlay: SVG fractalNoise at 3% opacity

| Section | Lines | What's There |
|---|---|---|
| Design Tokens | 7-123 | Colors, typography, spacing, shadows, and grain overlay |
| UI Patterns | 124-188 | Surface hierarchy, text roles, HUD, special treatments |
| Art Direction | 189-223 | Dissolving ink style, near-monochrome + 3 accent washes |
| Logo | 224-241 | Cormorant Garamond 300, all-caps, parchment |
| Brand Principles (Quick Reference) | 242-249 | 6 principles |

---

## cost_model.md (288 lines)

Per-session cost breakdowns, subscriber economics.

Additional topics: TTS Evaluation: Provider comparison: Inworld, Cartesia, Chatterbox, Dia2

| Section | Lines | What's There |
|---|---|---|
| Purpose | 3-10 | Can a $15–20/month subscription cover voice AI costs? Yes, after the Inworld switch |
| Pricing Inputs (February 2026) | 11-49 | Current prices (Feb 2026): Deepgram, Inworld, Claude, LiveKit |
| Session Model Assumptions | 50-82 | Solo vs party: speaking time, exchanges, output chars |
| Per-Session Cost Breakdown | 83-122 | Solo $0.40, Party per-player $0.14 |
| Monthly Subscriber Economics | 123-155 | Heavy/moderate/light x solo/party margins |
| Cost Distribution | 156-175 | TTS 53%, STT 16%, LLM 16%, Transport 15% |
| Optimization Paths | 176-209 | TTS Mini, caching, model tiering, self-host |
| Projections at Scale | 210-239 | 10K subs: 84% margin. 100K: 89% |
| Comparison: What Traditional MMOs Spend | 240-247 | AI compute costs more per session; content production costs far less |
| Risks and Uncertainties | 248-265 | TTS vendor concentration, session length creep, pricing trends, background costs |
| Verdict | 266-288 | Unit economics are strong at $17.50/month; TTS provider evaluation summary |

---

## dependency_upgrade.md (224 lines)

Reproducible inventory of all direct dependencies, lock resolutions, compatibility and release-age decisions, infrastructure holds, and executed validation lanes.

| Section | Lines | What's There |
|---|---|---|
| Python environments | 7-38 | Python environment and lockfile inventory. |
| Bun workspace | 39-124 | Release age policy: 604800 seconds. |
| Independent browser toolchain | 125-192 | Browser toolchain dependencies and validation. |
| Historical validation outcomes | 193-224 | Recorded compatibility checks and test results. |

---

## game_design_doc.md (1531 lines)

All player-facing systems. The largest doc — always read specific sections, not the whole thing.

Additional topics: Class System: 18 archetypes across 6 categories x 10 gods = 180 combos; Silent/Voiced Layers: Catch-Up (tap-based) vs Enter the World (voice); Navigation: Intent-based movement, macro/micro, audio compass; NPC Design: Companion system (5 functions), 4 NPC tiers, relationships; The Economy: Silver-based currency (cp/sp/gc), earning channels; PvP Design: Opt-in, structured, story-driven. Arena, territory, heists

| Section | Lines | What's There |
|---|---|---|
| About This Document | 3-17 | Scope of the design document and related documents |
| Character Creation — A Narrated Experience | 18-75 | Voice-conversation flow: Awakening → Origins → Calling → Devotion → Identity (10-15 min) |
| Class System — Archetype + Divine Patronage | 76-201 | Archetype sets the toolkit, patron flavors it; six archetype categories |
| Progression System | 202-245 | Archetype Mastery (XP), Divine Favor (alignment), World Reputation |
| Game Mechanics | 246-331 | d20+mod vs DC, 15 skills in 3 groups, status effects, difficulty tiers |
| Session Structure | 332-441 | 30-90 min sessions, 5 phases, fluid entry, DM behavioral modes |
| Combat Design — Voice-First Combat | 442-496 | Phase-based rounds, declarations, interrupts, sound as tactics, boss fights |
| Navigation — Moving Through a Voice-First World | 497-553 | Intent-based movement, macro and micro navigation, audio compass, HUD fallback |
| Player Guidance — Never Feeling Stuck | 554-622 | Always-available help, escalating guidance, companion as guide |
| NPC Design — Characters, Not Furniture | 623-679 | NPC categories, companion system, relationship mechanics, voice and personality |
| The Companion — Your Other Voice in the Dark | 680-870 | Why the companion exists, what it does, how it talks, across contexts and over time |
| Asynchronous Play — The Living World Between Sessions | 871-1050 | Crafting, training, scouting, factions, god whispers, companion errands |
| The Economy — Currency, Trade, and Value | 1051-1098 | Currency, pricing and trade, earning money, the sync/async economy loop |
| Death and Resurrection — Consequences with Compassion | 1099-1142 | Fallen → death saves → Mortaen's domain → return with escalating cost |
| PvP Design — Structured, Opt-In, Story-Driven | 1143-1203 | Opt-in faction PvP, structured modes, voice-specific toxicity guardrails |
| Seasonal Arc Structure | 1204-1230 | Multi-season narrative with Veythar reveal |
| Content Moderation — Layered Approach | 1231-1282 | 5 layers: DM, AI guardrails, voice analysis, reputation, party controls |
| Monetization | 1283-1367 | Subscription, battle pass, voice cosmetics, property system |
| The Opening Experience — First 30 Minutes | 1368-1502 | First 30 min flow: prologue → creation → normalcy → disruption → call to action |
| Open Game Design Questions | 1503-1531 | All marked resolved |

---

## mvp_spec.md (970 lines)

Scope, session arc, success criteria, buildable entities.

Additional topics: What We're NOT Building: Explicit scope cuts

| Section | Lines | What's There |
|---|---|---|
| About This Document | 3-10 | What the MVP playtest must cover and where the full vision lives |
| What the MVP Must Prove | 11-25 | Six core questions |
| MVP Scope Summary | 26-41 | One culture, one city, one wilderness, one story arc |
| MVP World | 42-108 | Accord of Tides district and the Greyvale wilderness zone |
| MVP Story Arc | 109-259 | Session-by-session (5 sessions): arrival → investigation → journey → ruins → revelation |
| MVP Character Options | 260-296 | Playable character choices for the initial slice |
| MVP Systems | 297-356 | Included gameplay systems and their MVP limits |
| Playtest Structure | 357-378 | Internal → Alpha → Beta rounds |
| Success Criteria | 379-396 | Quantitative (latency, accuracy, completion rate) and qualitative |
| MVP Development Priorities | 397-435 | Ordered by dependency and risk. Aligned with the detailed 18-step priority list in the *Technical Architecture Document — Development Priorities*. |
| Document Relationships | 436-449 | Links to the design, architecture, lore, and data documents |
| Appendix: Starter Content Entities | 450-970 | Full JSON for every MVP entity |

---

## player_resonance_system.md (570 lines)

Voice affect analysis for DM adaptation.

Additional topics: DM Behavioral Shifts: Affect→DM response mapping, Hollow intensity modulation

| Section | Lines | What's There |
|---|---|---|
| About This Document | 3-12 | Real-time read of how the player speaks, sitting between STT and the LLM |
| The Problem | 13-18 | Claude is deaf to how the player speaks |
| The Solution | 19-30 | Affect Analyzer: transcript metadata + raw audio + behavior |
| Signal Sources — What We Already Have | 31-86 | Deepgram timestamps/confidence, AudioFrame RMS, transcript patterns |
| The Affect Vector | 87-159 | JSON schema: engagement, energy, interaction_style, latency |
| Architecture — Where It Lives | 160-290 | Parallel branch via asyncio.Queue, stt_node override, never adds latency |
| What the DM Does With It | 291-345 | Affect injected as hot-layer prose; DM behavior shifts; Hollow intensity |
| Implementation Plan | 346-482 | 4 phases: transcript-only → audio → behavioral → tuning |
| Cost Impact | 483-494 | ~$0.006 per session |
| Future Extensions (Post-MVP) | 495-506 | Pitch tracking, cross-session baselines, multiplayer affect, companion mirroring |
| Resolved Technical Questions | 507-570 | Deepgram capabilities, calibration, privacy |

---

## product_overview.md (254 lines)

Vision, pitch, and high-level systems overview. Read first for context.

Additional topics: What Makes This an MMO: Shared persistent world, player economy, faction politics; Why Voice-First: Gameplay advantages of voice, target audience

| Section | Lines | What's There |
|---|---|---|
| What This Is | 3-50 | Voice-first MMORPG pitch, Aethos setting |
| What It Feels Like to Play | 51-66 | Walkthrough of a typical session |
| The World | 67-95 | Aethos overview, Pantheon as game systems (10 gods) |
| How It Works | 96-147 | Three-layer DM architecture, voice pipeline, tech stack |
| Game Systems | 148-175 | 18 archetypes x 10 gods, combat, multiplayer scales |
| Monetization | 176-193 | Subscription model, unit economics, red lines |
| Where We Are | 194-220 | Current state, MVP to MMO path (7 steps) |
| The Hard Problems | 221-240 | Six key technical challenges |
| The Deeper Documents | 241-254 | Map of the design documents and what each covers |

---

## release-0.13.0.md (17 lines)

Sprint 55 release notes and deployment handoff.

| Section | Lines | What's There |
|---|---|---|
| Operational handoff | 11-17 | Pre-deploy audit of spell-training cycles; lost local primary database volume |

---

## story_vigil_of_greyhaven.md (364 lines)

Narrative fiction piece. Demonstrates Hollow creature taxonomy in action and the world's tone.

| Section | Lines | What's There |
|---|---|---|
| Day One | 7-74 | Kael Thornridge's squad holds Greyhaven: shadelings → mawlings → hollowed knight → veilrender |
| Day Seven | 75-130 | The shadelings came first. |
| Day Fifteen | 131-166 | The mawlings arrived on Day Twelve. |
| Day Twenty-Three | 167-200 | The market-square deadfall trap destroys eight mawlings at a cost |
| Day Thirty-One | 201-234 | Jorin died on Day Twenty-Eight. |
| Day Thirty-Seven | 235-282 | The hollowed knight appeared on Day Thirty-Five. |
| Day Forty | 283-326 | They didn't make it to Day Forty-One. |
| Epilogue | 327-364 | Bardic song memorializing the seven defenders |

---

## technical_architecture.md (1666 lines)

Implementation blueprint. The second largest doc.

Additional topics: Transport (LiveKit): SFU model, room capacity, multiple agents per room; Agent Layer: NPC tiers, background world simulation

| Section | Lines | What's There |
|---|---|---|
| About This Document | 3-10 | Scope of the MVP technical architecture; last research update |
| Architecture Overview | 11-25 | Eight major layers |
| Language Architecture — Python + TypeScript Hybrid | 26-143 | Python (agent) + Bun/TS (everything else), monorepo structure |
| Client Architecture — Expo React Native | 144-324 | Expo screens, HUD layers, data flow, audio mixing, performance targets |
| The Voice Pipeline — End to End | 325-452 | STT (Deepgram), VAD (Silero + semantic), TTS (Inworld), LLM (Claude) |
| DM Agent Architecture | 453-724 | Layer 1: Voice Agent, Layer 2: Background Process, Layer 3: Toolset. Prompt architecture (static/warm/hot) |
| Orchestration Design | 725-969 | tts_node voice router, tag format, multi-player input arbitration, error recovery, session lifecycle |
| Game Engine Layer | 970-1005 | Rules engine (pure functions), world state manager |
| Agent Layer — Autonomous NPCs and World Simulation | 1006-1055 | How alive NPCs should be: NPC tiers from ambient to autonomous |
| Multiplayer Architecture | 1056-1226 | Ventriloquism, multi-player input, room structure, DM merge/fork |
| Authentication | 1227-1259 | Email + 6-digit verification code. No passwords, no OAuth. |
| Infrastructure | 1260-1360 | MVP infrastructure, cloud platform, cost |
| Development Priorities (Ordered by Dependency) | 1361-1383 | 18 ordered priorities |
| Testing and Quality Strategy | 1384-1621 | Five tiers: Infrastructure, Rules Engine, DM Behavior, Experience, Content |
| Open Technical Questions | 1622-1648 | Questions resolved by LiveKit research and those still open |
| Document Relationships | 1649-1666 | Table of the design documents, their purpose and status |

---

## worktree-bootstrap-brief.md (280 lines)

Worktree bootstrap design brief and measured implementation outcome.

| Section | Lines | What's There |
|---|---|---|
| 1. What this is for | 10-28 | Why teammate worktrees need a declared bootstrap command |
| 2. What is already true here — read this before writing anything | 29-96 | Three things already exist. Do not reinvent them. |
| 3. The measured blockers | 97-142 | node_modules, the agent .venv, and global Docker container names |
| 4. The decision you have to make (deliberately not made for you) | 143-166 | Two viable designs. Both are defensible; they differ in isolation vs cost. |
| 5. What to write | 167-194 | Requirements for an idempotent, fail-loud scripts/init-worktree.sh |
| 6. How to know it worked — verify, don't assume | 195-226 | Verify per artifact, not by the bootstrap's exit code |
| 7. Measured vs not | 227-245 | Which claims in this brief were measured and which were not |
| 8. Resolution (implemented 2026-07-17, story-005) | 246-280 | Per-worktree stack chosen; corrections found by re-measuring |

---

## world_data_simulation.md (950 lines)

DB schemas, JSON entity formats, world sim rules, content style guide.

Additional topics: Location Schema: Full JSON: conditions, hidden elements, exits, ambient sounds; NPC Schema: Personality, speech style, knowledge gating, schedules, voice mapping; Item Schema: Mechanical effects, economic properties; Quest Schema: State machine: stages, branches, completion conditions, world effects; Event/Trigger Schema: Trigger conditions, probability, cooldown, priority; Faction Schema: Reputation tiers with gameplay effects, relationships

| Section | Lines | What's There |
|---|---|---|
| Purpose | 3-10 | Content authoring format, world simulation rules, and data model; sparse data, DM narrates |
| Content Authoring Format | 11-461 | JSON schemas, Tier 1 (authored) vs Tier 2 (generated) |
| Content Style Guide | 462-621 | Write for the ear, description limits, NPC content, Hollow wrongness |
| World Simulation Rules | 622-811 | World clock (1:1), 4 simulation layers (per-minute through event-driven) |
| Data Model | 812-909 | PostgreSQL + Redis: 10 content tables, 12 state tables, 7 Redis patterns |
| MVP Content Scope | 910-938 | ~20 locations, ~25 NPCs, ~40 items, ~5 quests, ~18 events |
| Cross-References | 939-950 | Where these schemas and rules connect to the other design docs |

---

# Game mechanics

## game_mechanics/economy/faction_reputation_pricing.md (185 lines)

Faction-driven pricing layered on top of disposition. Reputation tiers, service refusal, faction-exclusive access.

| Section | Lines | What's There |
|---|---|---|
| Reputation Tiers and Price Modifiers | 9-21 | Reputation tier ladder mapped to price multipliers |
| Combined Pricing Formula | 22-46 | How faction modifier composes with disposition and events |
| Faction Service Refusal | 47-63 | When low standing blocks transactions entirely |
| Earning Reputation Through Economic Activity | 64-101 | Reputation gains from purchases/contracts/quest completions |
| Faction-Exclusive Access | 102-134 | Items/services gated to faction members |
| Interaction with Other Economy Systems | 135-146 | Stacking with supply/demand, gold sinks, inventory |
| DM Narration Guidance | 147-172 | How merchants voice reputation-driven pricing |
| Design Decisions | 173-185 | Locked decisions for faction pricing |

---

## game_mechanics/economy/game_mechanics_p2p_trade.md (226 lines)

Phase 2+ player-to-player trade design intent, inherited constraints, open questions.

| Section | Lines | What's There |
|---|---|---|
| Design Intent | 11-20 | What P2P trade is and isn't |
| Inherited Constraints | 21-52 | Constraints from voice-first, anti-fraud, audio HUD |
| Direct Trade (Same Location) | 53-74 | Face-to-face trade mechanic |
| Remote Trade | 75-101 | Trade across distance (couriers/mail) |
| Auction House / Marketplace | 102-125 | Centralized listing model |
| Trade Fees and Taxes | 126-145 | Fee structure as inflation control |
| Anti-Fraud and Anti-Exploit Guardrails | 146-175 | Voice/social attack vectors and mitigations |
| What Phase 1 Needs | 176-197 | Minimum hooks for later expansion |
| Phase 2 Design Process | 198-209 | How design will continue post-launch |
| Design Decisions | 210-226 | Locked decisions for P2P trade |

---

## game_mechanics/economy/gold_sink_ledger.md (428 lines)

Consolidated ledger of all gold sinks with magnitude analysis and gap analysis.

| Section | Lines | What's There |
|---|---|---|
| Design Philosophy | 9-36 | Why sinks matter, what counts as a sink |
| Categorization Framework | 37-64 | Sink categories (consumables/services/recurring/aspirational) |
| The Complete Ledger | 65-293 | Every sink in the game with magnitudes and triggers |
| Magnitude Analysis | 294-313 | Per-level/per-session sink expectations |
| Gap Analysis & Proposed Additions | 314-377 | Where the economy lacks sinks; proposals |
| Implementation Notes | 378-407 | How to wire sinks into the rules engine |
| Design Decisions | 408-428 | Locked decisions for sinks |

---

## game_mechanics/economy/inflation_targets_controls.md (275 lines)

Wealth-by-level curves, faucet/sink ratios, god-agent economic intervention, seasonal events.

| Section | Lines | What's There |
|---|---|---|
| Design Philosophy | 11-25 | Inflation control as live-ops, not static design |
| Phase 1: Per-Character Economic Curves | 26-79 | Wealth-by-level targets, faucet/sink ratios |
| Analytics Infrastructure (Phase 1) | 80-123 | Metrics to capture for tuning |
| Phase 2+: Global Economy Controls | 124-208 | God-agent intervention, server-wide levers |
| Phase 2+ Inflation Control Loop | 209-235 | Closed-loop adjustment cadence |
| What Phase 1 Needs | 236-256 | Minimum viable scope for launch |
| Design Decisions | 257-275 | Locked decisions for inflation control |

---

## game_mechanics/economy/merchant_inventory_restock.md (646 lines)

Three-tier stock model, inventory pools, daily restock, merchant gold pools, voice-first communication.

| Section | Lines | What's There |
|---|---|---|
| Three-Tier Stock Model | 9-22 | Always-stocked / Pooled / Special tiers |
| Inventory Pools — Definitions | 23-203 | Pool definitions per merchant role with item lists |
| Stock Limits by Settlement | 204-236 | Hamlet/Village/Town/City/Capital caps |
| Daily Restock Mechanics | 237-279 | Restock cadence, randomization, supply chain |
| Merchant Gold Pool | 280-340 | What merchants can afford to buy from players |
| Special Inventory Categories | 341-378 | Rare items, faction stock, festival inventory |
| Voice-First Inventory Communication | 379-448 | How the DM narrates browsing without lists |
| Implementation Reference | 449-625 | Algorithms, data shapes, restock pseudocode |
| Design Decisions | 626-646 | Locked decisions for inventory/restock |

---

## game_mechanics/economy/supply_demand_engine.md (597 lines)

Event-driven price fluctuation, three-phase event lifecycle, standard economic event catalog.

| Section | Lines | What's There |
|---|---|---|
| Design Philosophy | 9-16 | Events drive prices; baseline stays stable |
| Magnitude and Stacking Rules | 17-54 | Event modifier sizes, stacking, 0.5×–3.0× clamp |
| Item Tag Taxonomy (Economic) | 55-82 | Tags events target (food/weapon/luxury/etc.) |
| Event Lifecycle (Three Phases) | 83-129 | Onset → peak → resolution timing |
| Catalog of Standard Economic Events | 130-352 | Hollow incursion, plague, festival, blockade, etc. |
| Worked Example: Multi-Event Crisis | 353-394 | Stacking demonstration |
| Implementation Reference | 395-525 | Event data shape, evaluation order, hooks |
| DM Narration Patterns | 526-576 | How NPCs voice market shifts |
| Design Decisions | 577-597 | Locked decisions for supply/demand |

---

## game_mechanics/game_mechanics_archetypes.md (1357 lines)

18 archetype profiles with abilities, specializations, and spell acquisition.

| Section | Lines | What's There |
|---|---|---|
| Archetype Profiles | 9-416 | Overview of 18 archetypes: Martial(3), Arcane(3), Primal(3), Divine(3), Shadow(3), Support(3) |
| All Archetype Profiles — Complete (18 of 18) | 417-1148 | Individual stat blocks: HP, armor, skills, passives, actives, reactions, milestones |
| Core + Elective Ability Model | 1149-1221 | Core (always available) vs Elective (chosen at L4/L8), reaction abilities |
| Spell Acquisition System — Three Tracks | 1222-1286 | Core spells, Training study cycles, Discovery (scrolls/mentors) |
| Martial Mentor-Style System | 1287-1357 | Technique variants via NPC mentors, cultural attribution, 2-3 session loops |

---

## game_mechanics/game_mechanics_bestiary.md (1227 lines)

Creature stat blocks, Hollow and natural creatures, materials, encounters.

| Section | Lines | What's There |
|---|---|---|
| Creature Stat Block Schema | 9-131 | Universal template: attributes, attacks, passives, hollow fields, loot_table_id amendment |
| Hollow Creatures | 132-608 | 9 Hollow entities (Shadeling through The Architect), special mechanics |
| Natural Creatures | 609-1146 | 19 creatures across 6 regions plus multi-region, Tier 1-3 |
| Material Catalog Summary | 1147-1193 | Material values and crafting uses for all creature drops |
| Encounter Building Guidelines | 1194-1224 | Tier-based scaling, solo player math, companion effectiveness |
| Design Decisions Log (Bestiary) | 1225-1227 | Bestiary decisions (24-29) |

---

## game_mechanics/game_mechanics_combat.md (1060 lines)

Combat resolution, status effects, death, social encounters, travel, gathering.

| Section | Lines | What's There |
|---|---|---|
| Dramatic Dice System | 11-88 | Scarcity-based d20 animation (0-2 per combat), dramatic context rules |
| Combat System — Phase-Based | 89-202 | 4-beat phases (Declaration/Resolution/Narration/Wrap), no turn order |
| Combat Math | 203-262 | Attack rolls, AC by armor, weapon damage, cantrip scaling |
| Status Effects | 263-325 | 15+ conditions (Hollowed, Stunned, Prone, etc.) with mechanical effects |
| Resting | 326-339 | Short rest (Stamina full, Focus half), Long rest (all recovery) |
| Death and Dying | 340-614 | Death saves, Mortaen's domain, escalating costs, Hollowed Death, party wipe |
| Social Encounter Resolution | 615-847 | 3-tier system, disposition-as-DC, Diplomat de-escalation |
| Travel and Exploration | 848-972 | 3 travel modes, navigation checks, exhaustion, camping |
| Gathering and Resource Discovery | 973-1060 | Skill-gated harvesting, regional resource tables, discovery moments |

---

## game_mechanics/game_mechanics_core.md (1104 lines)

Foundational systems: attributes, skills, resources, leveling, async activities.

| Section | Lines | What's There |
|---|---|---|
| Document Status (All Mechanics Files) | 9-48 | Status and update timestamps for all mechanics files |
| Implementation Directive: The LLM is a Narrator, Not an Engine | 49-127 | LLM is narrator, not engine — rules engine returns narrative-ready packets |
| Core Resolution Mechanic | 128-145 | d20 + modifier vs DC, result packets with narrative cues |
| Attributes | 146-187 | 6 attributes, modifier math, attribute increases at L4/8/12/16/20 |
| Proficiency Bonus | 188-206 | Bounded scale: +1 (L1-6), +2 (L7-13), +3 (L14-20) |
| Skill System | 207-481 | 20 skills, 4 tiers (Untrained/Trained/Expert/Master), use counters, advancement |
| Difficulty Class (DC) Scale | 482-512 | Trivial (5) through Legendary (28), auto-fail thresholds |
| Hit Points | 513-544 | HP formula with half-CON growth rule |
| Resource System — Stamina and Focus | 545-589 | Dual pools, archetype assignments, recovery rates |
| Experience Points and Leveling | 590-686 | ~100 XP/session, 20-level progression, unified milestones |
| Async Training System | 687-817 | Variable-duration cycles, midpoint decisions, micro-bonuses |
| Companion Errands | 818-910 | 4 errand types (Scout/Social/Acquire/Relationship), risk-based returns |
| Async Activity Concurrency Model | 911-932 | 3 independent slots: Training + Crafting + Errand |
| Combat, Conditions & Death | 933-938 | Cross-reference to game_mechanics_combat.md |
| Character Creation | 939-1101 | 5 narrative choices → auto-computed attributes, equipment, spells |
| Design Decisions Log | 1102-1104 | Cross-reference to game_mechanics_decisions.md |

---

## game_mechanics/game_mechanics_crafting.md (591 lines)

Recipe learning, crafting resolution, durability, item catalog.

| Section | Lines | What's There |
|---|---|---|
| The Crafting Principle | 9-16 | Design philosophy: crafting mirrors spell acquisition |
| Crafting Resolution | 17-109 | 4 quality outcomes (Exceptional/Success/Partial/Failure), DC checks |
| Recipe System | 110-264 | Recipe slots, 3 acquisition tracks, experimentation |
| Crafting Categories | 265-344 | 7 categories with tier progression |
| Item Catalog | 345-520 | Complete pricing aligned to 1 sp = 1 day labor anchor |
| Durability System | 521-556 | Fragile/Standard/Reinforced/Masterwork, Hollow double corrosion |
| Async Crafting Activity | 557-588 | Concurrent crafting with variable timelines |
| Design Decisions Log (Crafting & Items) | 589-591 | Crafting & item decisions (36-43) |

---

## game_mechanics/game_mechanics_decisions.md (351 lines)

72 locked design decisions with reasoning. Master reference for settled choices.

Additional topics: Async Activities: Decisions 58-61: errand models, concurrency, risk

| Section | Lines | What's There |
|---|---|---|
| Core Systems, Combat & Character Creation (Decisions 1-53) | 9-78 | Decisions 1-53: bounded accuracy, skill tiers, resources, combat phases |
| Bestiary & Materials (Decisions 24-29) | 79-94 | Decisions 24-29: tier system, material drops, harvesting |
| NPCs, Mentors & Companions (Decisions 30-57) | 95-118 | Decisions 30-57: NPC templates, mentors, companions, death |
| Crafting & Items (Decisions 36-43) | 119-139 | Decisions 36-43: recipe system, quality, durability |
| Async Activities — Companion Errands & Concurrency (Decisions 58-61) | 140-150 | Errand decision models, companion unavailability, three activity slots, errand risk |
| Racial Traits & Level Progression (Decisions 62-63) | 151-157 | Decisions 62-63: attribute bonuses, Thessyn adaptation |
| Social Encounter Resolution (Decisions 64-67) | 158-168 | Decisions 64-67: social tiers, disposition mechanics |
| Dramatic Dice System (Decision 68) | 169-173 | Decision 68: rare visible rolls, tension management |
| Travel, Exploration & Gathering (Decisions 69-71) | 174-182 | Decisions 69-71: travel modes, gathering, node discovery |
| Economy Reconciliation (Decision 72) | 183-187 | Decision 72: 1 gc = 10 sp, matching lore bible |
| Encounter Roles (Decisions 73-81) | 188-209 | Role modifiers on base stat blocks, minion/elite/boss rules, harvesting and drops |
| Faction Reputation Pricing (Decisions 82-86) | 210-223 | Faction price modifiers, reputation from economic activity, exclusive items, detection |
| Merchant Inventory & Restock (Decisions 87-95) | 224-245 | Three-tier stock, dawn restock, finite merchant gold, buyback limits, consignment |
| Supply & Demand Engine (Decisions 96-104) | 246-267 | Price bounds, multiplicative event modifiers, tag matching, event phases and recovery |
| Gold Sinks & Economy Balance (Decisions 105-113) | 268-289 | Eight sink categories, mitigations, death costs, endgame and lifestyle sinks, tolls, bribery |
| Inflation Targets & Controls (Decisions 114-121) | 290-309 | Phase 2+ inflation control, wealth curve, per-session targets, hidden god-agent levers |
| Player-to-Player Trade (Decisions 122-128) | 310-325 | Deferred P2P trade under world rules, voice-first, provenance, atomic transactions |
| Terrain (Decisions 129-132) | 326-351 | One closed terrain enum on Location; ten values and their derived properties |

---

## game_mechanics/game_mechanics_economy.md (275 lines)

Canonical economy specification: static pricing data. Dynamic systems live in subsystem docs under `economy/`.

| Section | Lines | What's There |
|---|---|---|
| Subsystem Documents | 9-25 | Index of six `economy/` subsystem docs + encounter_roles link |
| Currency System | 26-35 | Three-tier decimal: cp/sp/gc at 10:1 ratios |
| Economic Anchor | 36-48 | 1 sp = 1 day unskilled labor, wage scale benchmarks |
| Canonical Price Tables | 49-131 | 60+ items: food, weapons, armor, gear, spell components |
| NPC Services | 132-151 | Healing, research, identification, resurrection pricing |
| Workspace Rental | 152-164 | Workshop/forge/lab daily rates, disposition discounts |
| Crafting Commissions (NPC Blacksmith) | 165-183 | Commission tiers (smith), repair pricing by item tier |
| Mentor Training Fees | 184-195 | Fee ranges by mentor renown, quest-gated exceptions |
| Starting Gold | 196-206 | Per-archetype starting wealth, purchasing power analysis |
| Merchant Pricing Formula | 207-237 | Disposition modifiers, clamp bounds, pointers to other modifiers |
| Quest Reward Tiers | 238-249 | Tier 1/2/3 reward ranges by content difficulty |
| Hollow Material Values | 250-264 | Drift/Rend/Wrack sample pricing, named fragments |
| Currency Drops from Combat | 265-275 | Per-category drop rules; full framework in encounter_roles |

---

## game_mechanics/game_mechanics_encounter_roles.md (790 lines)

Encounter role system: creature stat/loot/XP modifiers, encounter budget math, narration guidance. Referenced by bestiary and economy for loot scaling and currency drops.

| Section | Lines | What's There |
|---|---|---|
| Role Definitions | 11-64 | Minion/Standard/Elite/Boss/Legendary role tags and intent |
| Combat Stat Modifiers | 65-123 | HP, attack, damage, AC, save modifiers per role |
| Loot Modifiers | 124-184 | Material/currency drop multipliers, role-based loot rules |
| XP Modifiers | 185-200 | XP scaling per role |
| Encounter Budget System | 201-256 | Budget math, party-size scaling, encounter composition |
| Worked Examples | 257-584 | Full encounter walk-throughs across regions and tiers |
| DM Narration Guidance | 585-655 | How to voice role differences in combat |
| Derivation Formula (Implementation Reference) | 656-769 | Algorithms for runtime stat/loot derivation |
| Design Decisions | 770-790 | Locked decisions for the role system |

---

## game_mechanics/game_mechanics_magic.md (542 lines)

Three magic sources, Resonance system, 87 spells.

| Section | Lines | What's There |
|---|---|---|
| Magic System — The Three Sources and Resonance | 9-296 | Arcane/Divine/Primal multipliers, Resonance states, Hollow Echo, Veil Wards, racial interactions |
| Arcane Spell Catalog | 297-377 | 30 arcane spells with Focus costs and Resonance generation |
| Divine Spell Catalog | 378-451 | 28 divine spells: healing, protection, anti-Hollow |
| Primal Spell Catalog | 452-528 | 29 primal spells: terrain manipulation, area denial |
| Three-Source Catalog Comparison | 529-542 | Side-by-side comparison of spell pools and Resonance profiles |

---

## game_mechanics/game_mechanics_npcs.md (885 lines)

NPC schemas, role archetypes, mentors, settlements, companions.

| Section | Lines | What's There |
|---|---|---|
| NPC Schema | 11-64 | Extended stat blocks with social/economic/schedule/mentor layers |
| Role Archetype Templates | 65-378 | 12 roles: Merchant(7 subtypes), Blacksmith, Innkeeper, Healer, Scholar, Guard, etc. |
| Mentor Registry | 379-543 | Named mentors teaching martial variants and spells across cultures |
| Settlement Templates | 544-596 | Hamlet/Village/Town/City/Capital NPC distribution |
| Encounter Design: Hostile NPC Groups | 597-629 | Bandit Ambush, Ashmark Patrol, Cult Cell, Hollow-Corrupted templates |
| Companion Mechanical Framework | 630-882 | 4 companions (Kael/Lira/Tam/Sable), 75% player HP scaling, relationship tiers |
| Design Decisions Log (NPCs & Companions) | 883-885 | NPC & companion decisions (30-35, 54-57) |

---

## game_mechanics/game_mechanics_patrons.md (366 lines)

10 divine patrons with 4-layer mechanical system.

| Section | Lines | What's There |
|---|---|---|
| Architecture | 11-22 | Each divine patron provides four mechanical layers. Any archetype can follow any god, but certain combinations have enhanced effects (Layer 4). |
| Divine Favor Tiers | 23-36 | Favor thresholds and mechanical effects |
| Veythar, the Lorekeeper | 37-66 | Knowledge and arcane arts; Lorekeeper's Insight, Arcane Amplification, favor tiers, archetype resonance |
| Kaelen, the Ironhand | 67-94 | War and valor; Iron Resolve, Martial Focus, favor tiers, archetype resonance |
| Aelora, the Hearthkeeper | 95-122 | Civilization and crafting; Hearthkeeper's Bond, Shared Burden, favor tiers, archetype resonance |
| Thyra, the Wildmother | 123-150 | Nature and seasons; Nature's Pulse, Veil Grounding, favor tiers, archetype resonance |
| Syrath, the Veilwatcher | 151-178 | Shadows and secrets; Shadow Veil, Hidden Casting, favor tiers, archetype resonance |
| Orenthel, the Dawnbringer | 179-206 | Light and healing; Dawn's Resilience, Purifying Light, favor tiers, archetype resonance |
| Valdris, the Scalebearer | 207-234 | Justice and truth; Weight of Truth, Ordered Magic, favor tiers, archetype resonance |
| Mortaen, the Threshold | 235-262 | Death and transition; Death's Awareness, Threshold Magic, favor tiers, archetype resonance |
| Nythera, the Tidecaller | 263-290 | Sea and exploration; Horizon Sense, Boundary Walker, favor tiers, archetype resonance |
| Zhael, the Fatespinner | 291-318 | Fate and luck; Fate's Thread, Pattern Weaving, favor tiers, archetype resonance |
| The Unbound Path (No Patron) | 319-351 | Self-sourced magic; Veil Clarity, Raw Channeling, self-reliance milestones, endgame relevance |
| Patron System Summary | 352-366 | Patron system mechanics and cross-patron comparison. |

---

## game_mechanics/veil_ward_scope_model.md (216 lines)

The Veil Ward's scope, duration, and multiplayer model (M24). Read before touching ward code.

| Section | Lines | What's There |
|---|---|---|
| 1. A ward is owned by a scope, never by a caster | 16-35 | Scope-owned ward; effects apply per-caster-in-scope; Resonance/Echo stay per-caster |
| 2. Two scope kinds, two homes | 36-75 | `encounter` on CombatState JSONB vs `location` in the `veil_wards` table; why not one table; why no world clock is needed |
| 3. Ward resolution: any covering scope | 76-105 | The OR rule; coexistence and single-scope-expiry HUD semantics |
| 4. Sources and durations | 106-146 | Five-source table; Paladin combat-only; the Artificer's small (1h) and large (permanent) anchors |
| 5. Dismissal | 147-154 | Any in-scope member; permanent wards are not dismissible |
| 6. Wire contract | 155-174 | `VEIL_WARD_CHANGED` carries resolved state, no raiser id; the deliberate asymmetry with `RESONANCE_CHANGED` |
| 7. Phase boundaries | 175-199 | Phase-10 Druid terrain gate; Phase-11 world-sim wards; the `sacred_site` hook |
| 8. Migration off the per-player boolean | 200-216 | Migration 057; first `players.data` key removal; no dual-state window |

---

# Prompts

## prompts/audio_prompts.md (362 lines)

Generation prompts for combat, music, interface, and environment sounds.

| Section | Lines | What's There |
|---|---|---|
| Combat Sound Effects | 7-136 | Sword, blunt, arrows, spells, hits, crits, status effects, enemy signatures (CMB-002–022) |
| Dice Sounds | 137-152 | Standard roll, skill check |
| Music Stems | 153-182 | Tension, combat boss, sorrow, title themes |
| Stingers | 183-252 | Quest, level up, faction, god whisper variants, death, session (STG-001–009) |
| UI Sounds | 253-303 | Cancel, error, async complete, menu, scroll, confirm (UI-002–010) |
| Sable's Sound Palette | 304-324 | 5 emotional states as animal sounds |
| Additional Missing Prompts | 325-362 | Millhaven variants, wilderness night (ENV-004–008) |

---

## prompts/image_prompt_library.md (379 lines)

Nano Banana 2 prompts for all art categories.

| Section | Lines | What's There |
|---|---|---|
| For Nano Banana 2 (Gemini 3.1 Flash Image) | 2-5 | Image model and prompt-library usage. |
| Style Foundation | 6-28 | Core keywords, always-include, avoid-list |
| Accent Color Rules | 29-42 | Three colors: Teal, Ember, Gold with hex and prompt language |
| Category 1: Character Portraits | 43-110 | Companion, NPC, player character prompts |
| Category 2: Location Illustrations | 111-177 | Town, wilderness, corrupted, interior prompts |
| Category 3: Item & Object Art | 178-223 | Weapon, artifact, quest item prompts |
| Category 4: Story Moment Illustrations | 224-275 | Combat, god contact, hollow encounter prompts |
| Category 5: UI & Marketing Assets | 276-318 | App store, social media, loading screen prompts |
| Consistency Tips for Nano Banana 2 | 319-353 | 6 tips, aspect ratio table |
| Production Pipeline Notes | 354-379 | Batch consistency, post-processing, priorities |

---

## prompts/map_generation_prompt.md (98 lines)

Single prompt for generating the Aethos world map.

Additional topics: Prompt: Full map generation prompt: regions, corruption gradient, style

| Section | Lines | What's There |
|---|---|---|
| Prompt for Image Generation AI | 7-57 | Full map prompt: regions north to south, map features, style, mood |
| Usage Instructions | 58-68 | How to use with AI generators |
| Variations to Try | 69-84 | Artistic, cartographic, darker, lighter |
| Expected Output | 85-98 | What a successful generated map shows |

---

# Operations

## ops/async-activity-reset.md (72 lines)

Runbook: reset a stuck async-activity resolution — when the worker loops replaying a poisoned narration cache past the revert-attempt threshold. Verified by `apps/agent/tests/acceptance/test_ops_async_reset_runbook.py`.

Additional topics: When to use: The "reverted N times" worker warning + why the cache traps the retry

| Section | Lines | What's There |
|---|---|---|
| 1. Find stuck activities | 23-32 | Detection query (resolve_attempts >= threshold) |
| 2. Reset one activity | 33-50 | The cache-clearing UPDATE that forces a clean re-resolution |
| 3. Verify recovery | 51-64 | Confirm resolved + the warning stops |
| Notes | 65-72 | Link to the verifying test + the deferred circuit-breaker |

---

## ops/production-deployment-architecture.md (76 lines)

Canonical target for how Divine Ruin rolls out in production: **DigitalOcean, all-managed** — managed Postgres + Valkey, LiveKit Cloud, DO Spaces for assets; agent + server as containers. Local infra maps to this target on unique dev ports (Postgres 55432, Valkey 56379). Resolves the AWS/GCP-vs-DO and LiveKit Cloud-vs-self-hosted contradictions.

| Section | Lines | What's There |
|---|---|---|
| Summary | 5-10 | DigitalOcean all-managed; cost-conscious/low-ops principle |
| Target architecture | 11-32 | Topology diagram + per-component prod hosting table |
| Local → production mapping | 33-47 | Containerized stand-ins; unique dev ports; env-only difference |
| Environment & secrets | 48-53 | Canonical required env set; platform secrets in prod |
| Migrations & seed on deploy | 54-59 | migrate.ts + seed_content.py as deploy steps |
| Asset storage | 60-63 | Defers to the object-storage migration spec (DO Spaces) |
| Contradictions this doc resolves | 64-71 | Provider, LiveKit hosting, cost-model follow-up |
| Open follow-ups | 72-76 | cost_model recompute, asset migration, Dockerfiles |

---

# Decisions

## decisions/0001-patron-roster-sot.md (173 lines)

---

## decisions/0002-agent-tool-error-shape.md (124 lines)

---

## decisions/0003-acceptance-llm-run-schedule.md (91 lines)

---

## decisions/0004-agent-tool-scaling.md (164 lines)

---

## decisions/0005-artificer-slot-deferred-to-phase-5.md (72 lines)

---

## decisions/0006-errand-risk-at-resolution.md (54 lines)

---

## decisions/0007-verb-stage-resolve-tooling-model.md (97 lines)

---

## decisions/0008-sum-typed-verbs-and-next-in-results.md (226 lines)

---

# Milestones and audits

## milestones/00_doc_updates.md (112 lines)

---

## milestones/01_core_systems.md (215 lines)

---

## milestones/02_archetypes.md (218 lines)

---

## milestones/03_magic.md (191 lines)

---

## milestones/04_combat.md (306 lines)

---

## milestones/05_crafting.md (358 lines)

---

## milestones/06_npcs.md (298 lines)

---

## milestones/07_bestiary.md (197 lines)

---

## milestones/08_patrons.md (180 lines)

---

## milestones/09_economy.md (533 lines)

---

## milestones/10_terrain.md (129 lines)

---

## milestones/11_world_loop.md (250 lines)

---

## milestones/12_story_content.md (222 lines)

---

## milestones/README.md (168 lines)

---

## milestones/REMAINING.md (203 lines)

---

## milestones/audit/README.md (395 lines)

---

## milestones/audit/dependency-versions.md (148 lines)

---

## milestones/audit/phase-0.md (63 lines)

---

## milestones/audit/phase-1-async.md (48 lines)

---

## milestones/audit/phase-1-characters.md (86 lines)

---

## milestones/audit/phase-1-rules-engine.md (41 lines)

---

## milestones/audit/phase-2-archetypes.md (218 lines)

---

## milestones/audit/phase-3-magic.md (189 lines)

---

## milestones/audit/phase-4-combat.md (294 lines)

---

## milestones/audit/phase-5-durability.md (98 lines)

---

## milestones/audit/phase-5-quality.md (84 lines)

---

## milestones/audit/phase-5-recipes-resolution.md (128 lines)

---

## milestones/audit/phase-6-companions.md (180 lines)

---

## milestones/audit/phase-6-mentors.md (198 lines)

---

## milestones/audit/phase-6-schema-archetypes.md (142 lines)

---

## milestones/audit/phase-6-settlements.md (164 lines)

---

## milestones/audit/phase-7-bestiary.md (244 lines)

---

## milestones/audit/phase-8-patrons.md (147 lines)

---

## milestones/audit/phase-9-economy.md (211 lines)

---

## milestones/audit/phase-9-faction-pricing.md (184 lines)

---

## milestones/audit/phase-9-gold-sink.md (245 lines)

---

## milestones/audit/phase-9-inflation.md (221 lines)

---

## milestones/audit/phase-9-p2p-trade.md (196 lines)

---

## milestones/audit/phase-9-restock.md (236 lines)

---

## milestones/audit/phase-9-supply-demand.md (189 lines)

---

## milestones/audit/phase-encounter-roles.md (94 lines)

---

# Ideas

## ideas/object-storage-migration.md (164 lines)

---

# Mockup notes

## mockups/source/README.md (30 lines)

---
