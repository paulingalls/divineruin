# Divine Ruin — MVP Development Milestones

## How to Use This Document

Each milestone below is scoped for a focused development sprint. Feed this entire document into Claude Code's planning mode. Every milestone has:

- **Goal:** What we're building and why it matters
- **Inputs:** What must exist before starting (dependencies from prior milestones)
- **Deliverables:** Exactly what code/config/assets are produced
- **Acceptance criteria:** How to verify the milestone is complete — every criterion is testable
- **Key references:** Which sections of the design docs to consult

The milestones follow the dependency chain: infrastructure → voice pipeline → DM agent → game mechanics → content → client → multiplayer → async → polish.

## Design Document Reference Guide

The following design documents are available for detailed implementation guidance. Consult them when a milestone's key references point to specific sections. Read the relevant sections before writing code — the design decisions are already made.

| Document | Filename | Use it for... |
|---|---|---|
| **Product Overview** | `product_overview.md` | High-level vision, what we're building and why. Read first for context. |
| **Game Design Document** | `game_design_doc.md` | All player-facing systems: character creation, classes, combat, navigation, companions, async play, economy, death, PvP, monetization, the opening experience. **The most detailed document — 21,000+ words.** |
| **Technical Architecture** | `technical_architecture.md` | DM agent architecture (three-layer design), voice pipeline (LiveKit + Deepgram + Inworld), orchestration, tool system, session lifecycle, background process, multiplayer, testing strategy, latency budget. **The implementation blueprint.** |
| **Audio Design** | `audio_design.md` | Sound design philosophy, 7-layer audio stack, environmental soundscapes, Hollow audio (5-stage escalation), voice design (DM, companions, NPCs, gods), combat audio, adaptive music, UI sounds, async audio. Includes AI generation prompts for all asset types and a full MVP asset inventory. |
| **World Data & Simulation** | `world_data_simulation.md` | JSON entity schemas for all content types (locations, NPCs, quests, items), world simulation rules (time, weather, corruption, economy, god-agent heartbeat), content style guide (audio-first writing), database data model. |
| **MVP Specification** | `mvp_spec.md` | Scoped feature set, session-by-session content arc, success criteria, playtest structure. **Appendix contains buildable JSON entities** for all tier 1 MVP content. |
| **Aethos Lore Bible** | `aethos_lore.md` | World history, cosmology, 10 gods (personalities and domains), 6 races, 8 cultures, geography, the Hollow, the central mystery. Use for narrative consistency and NPC/quest content. |
| **Cost Model** | `cost_model.md` | Per-minute and per-session cost breakdowns, subscriber economics, async cost modeling. Reference when making technology choices that affect cost (LLM model selection, TTS provider, caching strategy). |

**When a milestone says "Key references: Technical Architecture — Tool System"**, open `technical_architecture.md` and search for the "Tool System" section. The design decisions, data formats, and implementation patterns are already specified there.

---

## Phase 1: Foundation

### Milestone 1.1 — Project Scaffolding and Infrastructure

**Goal:** Set up the monorepo, dev environment, database, and deploy pipeline so all subsequent milestones have a place to live.

**Inputs:** None (this is the starting point).

**Deliverables:**
- Monorepo structure: `/server` (Python), `/client` (Expo React Native), `/shared` (types/schemas), `/content` (JSON entities), `/scripts` (tooling)
- PostgreSQL database with initial schema: `players`, `characters`, `sessions`, `locations`, `npcs`, `quests`, `items`, `player_inventory`, `player_quest_progress`, `npc_dispositions`, `player_reputation`, `world_events` tables. Use JSONB for entity data columns.
- Redis instance configured for session caching
- Docker Compose for local development (PostgreSQL, Redis, server)
- Basic CI pipeline (lint, type check, test runner)
- Environment configuration (.env structure for API keys: Anthropic, Deepgram, Inworld, LiveKit)

**Acceptance criteria:**
- [ ] `docker compose up` starts PostgreSQL, Redis, and a stub Python server
- [ ] Database migrations run cleanly and create all tables
- [ ] A test script can INSERT and SELECT a sample location entity as JSONB
- [ ] Redis SET/GET works from the Python server
- [ ] CI runs on push and reports lint + type check results
- [ ] Expo dev client boots to a blank screen on iOS simulator or Android emulator

**Key references:**
- *Technical Architecture — Architecture Overview* (7-layer diagram)
- *World Data & Simulation — Data Model* (table schemas, JSONB structure)
- *Technical Architecture — Infrastructure Summary* (PostgreSQL, Redis, hosting)

---

### Milestone 1.2 — Content Database Seeding

**Goal:** Load the MVP's authored content into PostgreSQL so the DM agent has a world to query.

**Inputs:** Milestone 1.1 (database exists).

**Deliverables:**
- Content loader script that reads JSON entity files from `/content` directory and inserts into appropriate tables
- All MVP tier 1 entities loaded: 4 locations (Market Square, Millhaven, Greyvale Ruins Entrance, Hollow Breach), 3 NPCs (Guildmaster Torin, Elder Yanna, Scholar Emris), 1 quest (The Greyvale Anomaly with 5 stages), 2 items (Sealed Research Tablet, Hollow-Bone Fragment)
- Seed data for player-facing lookups: location connections (exits), NPC-location assignments, quest stage flow
- Tier 2 location stubs (10-15 generated locations with tags but minimal authored content) for areas between the tier 1 locations

**Acceptance criteria:**
- [ ] `python scripts/seed_content.py` loads all entities without errors
- [ ] `SELECT * FROM locations WHERE id = 'loc_market_square'` returns the full JSON entity with description, ambient_audio, exits, hidden_elements, and conditions
- [ ] `SELECT * FROM npcs WHERE id = 'npc_torin'` returns personality, speech_style, knowledge tiers, and disposition data
- [ ] `SELECT * FROM quests WHERE id = 'quest_greyvale_anomaly'` returns all 5 stages with objectives, hints, completion conditions, and rewards
- [ ] Location exit references are valid (every exit's `destination` matches an existing location ID)
- [ ] NPC knowledge gating has at least 2 disposition tiers with different information per tier

**Key references:**
- *MVP Spec — Appendix: Starter Content Entities* (the actual JSON entities)
- *World Data & Simulation — Content Authoring Format* (entity schemas)
- *World Data & Simulation — Content Tiers* (tier 1 vs tier 2 distinction)

---

## Phase 2: Voice Pipeline

### Milestone 2.1 — LiveKit Room + Basic Audio Transport

**Goal:** A human speaks into the app and hears audio come back. Prove the transport layer works.

**Inputs:** Milestone 1.1 (server and client scaffolding exist).

**Deliverables:**
- LiveKit server integration (LiveKit Cloud or self-hosted) with room creation API
- Client-side LiveKit SDK integration in Expo app: connect to room, publish mic audio track, subscribe to remote audio tracks
- Client-side VAD using Silero model: detect speech start/end, visual indicator for mic state
- Server-side agent that joins the room and plays back a static audio clip when it detects a user has spoken (echo test)
- Token generation endpoint: client requests a room token, server creates room and returns token

**Acceptance criteria:**
- [ ] Client connects to a LiveKit room and publishes a mic audio track
- [ ] VAD correctly detects speech start and end (visual indicator toggles)
- [ ] Server agent receives audio, and the client receives audio back within 500ms
- [ ] Room cleanup occurs when the user disconnects (no orphaned rooms)
- [ ] Works on both iOS and Android (test on simulators minimum)

**Key references:**
- *Technical Architecture — LiveKit Voice Pipeline* (room architecture, SFU model)
- *Technical Architecture — Client Application — Voice Connection*
- *Technical Architecture — Latency Budget* (300-500ms VAD target)

---

### Milestone 2.2 — STT + TTS Pipeline

**Goal:** Speech goes in, text comes out, synthesized speech goes back. The full voice-to-voice chain.

**Inputs:** Milestone 2.1 (LiveKit room with audio transport).

**Deliverables:**
- Deepgram Nova-3 integration for streaming STT: audio frames from LiveKit → Deepgram WebSocket → transcript events
- Inworld TTS-1.5 Max integration for streaming TTS: text → Inworld API → audio frames streamed to LiveKit
- A simple echo agent: user speaks → STT transcribes → agent generates a static response (e.g., "I heard you say: [transcript]") → TTS synthesizes → user hears the response
- Latency measurement: log timestamps at each pipeline stage (VAD end → STT final → TTS first byte → user hears audio)

**Acceptance criteria:**
- [ ] User speaks a sentence and hears a synthesized voice repeat what they said within 2 seconds
- [ ] STT transcript accuracy is reasonable for clear English speech (>90% WER on simple sentences)
- [ ] TTS output is natural-sounding and intelligible
- [ ] Latency logs show: VAD (< 500ms) + STT (< 400ms) + TTS TTFB (< 300ms) = total < 1.5s for first audio byte
- [ ] Pipeline handles silence gracefully (no false triggers, no stuck states)
- [ ] Multiple sequential utterances work without degradation

**Key references:**
- *Technical Architecture — LiveKit Voice Pipeline* (Deepgram Nova-3, Inworld TTS-1.5 Max)
- *Technical Architecture — Latency Budget* (full breakdown of targets)
- *Cost Model — Per-Minute Cost Breakdown* (verify which service tiers to use)

---

### Milestone 2.3 — DM Agent: Basic Conversation

**Goal:** The AI DM can hold a freeform conversation in voice. The player talks, the DM responds in character.

**Inputs:** Milestone 2.2 (STT + TTS pipeline working).

**Deliverables:**
- `DungeonMasterAgent` class extending LiveKit's `Agent` base: receives transcripts, calls Claude API (Haiku 4.5), returns narrated responses
- Static system prompt establishing DM persona: narrator voice, fantasy world context, conversational style (warm, descriptive, audio-first)
- Conversation history management: rolling context window with token budget
- TTS voice selection: one `voice_id` for the DM narrator voice
- Basic interruption handling: if user speaks while DM is talking, DM stops and listens

**Acceptance criteria:**
- [ ] User can have a 5-minute freeform voice conversation with the DM
- [ ] DM maintains consistent persona across multiple exchanges (doesn't break character)
- [ ] DM responses are descriptive and audio-first (describes sounds and feelings, not visual details)
- [ ] Interruption works: speaking over the DM causes it to stop and acknowledge the new input
- [ ] Conversation history persists across turns (DM remembers what was said earlier in the conversation)
- [ ] Response latency stays under 2.5 seconds for 90% of turns

**Key references:**
- *Technical Architecture — DM Agent Architecture* (three-layer design, LLM selection)
- *Game Design — Session Structure* (DM persona and behavior)
- *World Data & Simulation — Content Style Guide* (audio-first writing principles)
- *Audio Design — Voice Design — The DM Voice* (voice characteristics and TTS direction)

---

### Milestone 2.4 — Ventriloquism: Multiple Character Voices

**Goal:** The DM can voice NPCs with distinct voices. The player hears different characters as different people.

**Inputs:** Milestone 2.3 (DM agent with conversation ability).

**Deliverables:**
- Output parser (`tts_node`) that detects `[CHARACTER_NAME, emotion]: "dialogue"` tags in LLM output
- Voice routing: narrator text → DM `voice_id`, character dialogue → character-specific `voice_id`
- At least 3 distinct voice configurations: DM narrator, Companion (Kael), one NPC (Guildmaster Torin)
- System prompt update: instruct the DM to use the `[CHARACTER, emotion]` format for all NPC dialogue
- Emotion tag support: TTS receives emotion hint alongside text (e.g., `weary`, `urgent`, `amused`)

**Acceptance criteria:**
- [ ] When the DM narrates, the player hears the DM voice
- [ ] When an NPC speaks (e.g., "Torin says..."), the player hears a distinctly different voice
- [ ] The companion (Kael) has a third distinct voice
- [ ] Transitions between narrator and character voices feel natural (no jarring gaps or overlaps)
- [ ] Emotion tags produce audible tonal shifts in TTS output (weary sounds different from urgent)
- [ ] LLM consistently uses the `[CHARACTER, emotion]` format without breaking it (>95% of NPC dialogue correctly tagged)

**Key references:**
- *Technical Architecture — Orchestration Design* (output parsing, ventriloquism tags)
- *Audio Design — Voice Design* (DM voice, companion voices, NPC differentiation)
- *Game Design — NPC Design* (NPC voice and personality design)

---

## Phase 3: Game Mechanics

### Milestone 3.1 — World Query Tools

**Goal:** The DM can look up information about the world mid-conversation — locations, NPCs, lore, items.

**Inputs:** Milestone 1.2 (content database seeded), Milestone 2.3 (DM agent conversational).

**Deliverables:**
- `query_location` tool: takes `location_id`, returns description, exits, ambient audio tag, condition-modified description based on current time/weather/quest state
- `query_npc` tool: takes `npc_id`, returns personality, speech_style, knowledge (filtered by current player disposition), and mannerisms
- `query_lore` tool: takes keyword/topic, returns relevant lore entries
- `query_inventory` tool: takes `player_id`, returns current inventory with item descriptions
- Redis caching layer: frequently accessed entities cached with TTL, rebuilt from PostgreSQL on miss
- Tool registration with the LLM: tools defined as `@function_tool` decorators that Claude can call

**Acceptance criteria:**
- [ ] DM can answer "where am I?" by calling `query_location` and narrating the description
- [ ] DM can answer "tell me about Torin" by calling `query_npc` and roleplaying using the returned personality/speech_style
- [ ] NPC knowledge gating works: at neutral disposition, `query_npc` for Torin returns only tier 1 knowledge; at friendly, returns tier 2
- [ ] `query_inventory` returns the player's current items and the DM can describe them
- [ ] Second call to same entity within TTL serves from Redis (verify with logs)
- [ ] DM naturally integrates queried information into narration (doesn't dump raw data)

**Key references:**
- *Technical Architecture — Tool System* (function_tool pattern, query vs. mutation tools)
- *World Data & Simulation — Entity Schemas* (what each entity contains)
- *MVP Spec — Appendix: Starter Content Entities* (the actual entities being queried)

---

### Milestone 3.2 — Dice and Mechanics Tools

**Goal:** The DM can call for skill checks, attacks, and saving throws. Dice roll, rules validate, DM narrates the outcome.

**Inputs:** Milestone 3.1 (query tools working, entities in database).

**Deliverables:**
- `request_skill_check` tool: LLM provides skill + context, rules engine determines DC, rolls d20 + modifier, returns `{success, margin, narrative_hint}`
- `request_attack` tool: attacker/defender stats, rolls to hit, calculates damage if hit, returns `{hit, damage, narrative_hint}`
- `request_saving_throw` tool: cause, stat, DC, rolls and returns result with narrative_hint
- Rules engine module: pure functions that calculate DCs, apply modifiers, determine outcomes — fully deterministic and testable
- Client-side dice roll sound effect triggered via LiveKit data channel when a roll occurs
- `play_sound` tool: sends a data channel message to the client to play a named sound effect

**Acceptance criteria:**
- [ ] DM appropriately calls for a skill check when the player attempts something uncertain (e.g., "I try to persuade the guard")
- [ ] Dice roll produces a valid d20 result with correct modifier application
- [ ] The player hears a dice roll sound effect on their device when a check occurs
- [ ] `narrative_hint` provides appropriate flavor text that the DM can weave into narration (e.g., "barely succeeded" or "critical failure")
- [ ] Rules engine unit tests pass for all 15 skills across the full modifier range
- [ ] DM never exposes raw numbers to the player — all mechanics are narrated

**Key references:**
- *Game Design — Game Mechanics* (core resolution, skill system, difficulty tiers)
- *Technical Architecture — Tool System — Dice and Mechanics Tools* (hybrid model)
- *Audio Design — Combat Audio — Dice Sounds* (DICE-001 through DICE-004)

---

### Milestone 3.3 — Game State Mutation Tools

**Goal:** The game world changes based on player actions — movement, inventory, quest progress, XP.

**Inputs:** Milestone 3.2 (dice/mechanics tools working).

**Deliverables:**
- `move_player` tool: validates destination is reachable from current location, updates player location, triggers scene narration, sends `location_changed` event to client
- `add_to_inventory` / `remove_from_inventory` tools: validates item exists, updates inventory, sends UI update to client
- `update_quest` tool: advances quest stage, validates completion conditions, triggers stage-specific narrative beats
- `award_xp` tool: adds XP, checks for level-up threshold, triggers level-up narration if crossed
- `update_npc_disposition` tool: modifies NPC disposition based on player actions
- Client UI data channel: server pushes state changes to client via LiveKit data messages, client updates HUD elements
- Async database writes with retry queue (mutations persist to PostgreSQL in background, not blocking the voice response)

**Acceptance criteria:**
- [ ] "I go to Millhaven" → DM calls `move_player` → player location updates → client receives `location_changed` event → DM narrates the new scene
- [ ] "I pick up the tablet" → `add_to_inventory` → item appears in player inventory → client HUD updates
- [ ] Quest stage advances when completion conditions are met (e.g., `location_reached: loc_millhaven`)
- [ ] When quest advances, the DM receives stage-specific narration beats and weaves them in
- [ ] XP awards trigger visible feedback on the client
- [ ] State mutations persist to PostgreSQL within 5 seconds (verify with DB query after mutation)
- [ ] If the database write fails, the retry queue picks it up (simulate failure and verify retry)
- [ ] NPC disposition changes affect subsequent `query_npc` results (higher disposition reveals more knowledge)

**Key references:**
- *Technical Architecture — Tool System — Game State Mutation Tools* (smart validation, auto-push)
- *Game Design — Progression System* (XP, leveling)
- *MVP Spec — Appendix: The Greyvale Anomaly Quest* (stage flow with completion conditions)

---

### Milestone 3.4 — Background Process and Per-Turn Context

**Goal:** The DM stays aware of world changes mid-session and has rich context for every response.

**Inputs:** Milestone 3.3 (state mutation tools working).

**Deliverables:**
- Background process (async coroutine running alongside the agent): subscribes to event bus, periodically updates the DM's system prompt via `update_instructions()`
- Event bus integration: state mutations publish events (location_changed, quest_advanced, combat_started, etc.) that the background process consumes
- `on_user_turn_completed` hook: injects per-turn ephemeral context (current location details, active quest stage hints, nearby NPCs, time of day, recent events) into the next LLM call
- Proactive speech system: background process can queue companion utterances (environmental observations, idle chatter, guidance nudges) with priority classification (critical / important / routine)
- Timer fallback: if no events arrive for 30 seconds, background process still refreshes context

**Acceptance criteria:**
- [ ] When the player moves to a new location, the DM's system prompt updates to reflect the new location within 2 seconds (without the player asking)
- [ ] Per-turn context injection includes current quest stage hints relevant to the player's location
- [ ] The companion occasionally speaks proactively — an environmental observation or a relevant comment — without being prompted by the player
- [ ] Proactive speech respects priority: critical interrupts (danger) override routine (idle chat)
- [ ] The DM references time of day appropriately (if the world clock says night, descriptions match)
- [ ] Background process doesn't degrade voice response latency (verify latency stays under 2.5s)

**Key references:**
- *Technical Architecture — Background Process* (event bus, timer fallback, proactive speech)
- *Technical Architecture — Per-Turn Context Injection* (on_user_turn_completed hook)
- *Game Design — Player Guidance* (escalating guidance system, companion suggestions)

---

## Phase 4: Combat and Multiplayer

### Milestone 4.1 — Combat System

**Goal:** Phase-based voice combat that's exciting and clear in audio.

**Inputs:** Milestone 3.2 (dice/mechanics tools), Milestone 3.3 (state mutation), Milestone 3.4 (background process).

**Deliverables:**
- Combat state machine: `idle` → `initiative` → `declaration` → `resolution` → `next_phase` (loop) → `combat_end`
- Player declaration handling: DM prompts "What do you do?", player speaks intent, DM interprets and calls appropriate mechanics tools
- Enemy AI: DM selects enemy actions from a defined action pool based on enemy type and combat state
- HP tracking for player, companion, and enemies with client HUD display (HP bars, status effects)
- Combat sound effects integration: weapon impacts, spell effects, hits taken, combat start/end stingers triggered via `play_sound`
- Phase transition narration: DM describes the evolving combat scene between each phase
- Death/fallen state: player HP reaches 0, triggers death saving throws sequence per game design

**Acceptance criteria:**
- [ ] A full combat encounter plays out from start to finish: DM describes enemies, initiative occurs, player declares actions, dice roll, DM narrates outcomes, enemies act, repeat until resolved
- [ ] Player hears distinct sound effects for their attacks (sword, spell, bow) and for enemy attacks
- [ ] Player heartbeat audio fades in as HP drops below 50% and increases in rate as it drops further
- [ ] Combat start and end stingers play at the right moments
- [ ] The companion participates in combat with their own actions and tactical callouts
- [ ] Falling to 0 HP triggers the death saving throw sequence
- [ ] Combat concludes with XP award and loot narration
- [ ] The full combat encounter is exciting and understandable in audio only (playtest validation)

**Key references:**
- *Game Design — Combat Design* (phase-based rounds, key mechanics, sound design as combat system)
- *Audio Design — Combat Audio* (weapon impacts, player feedback, enemy audio, combat music)
- *Game Design — Death and Resurrection* (fallen state, death saving throws)

---

### Milestone 4.2 — Multiplayer Room

**Goal:** Two human players and the DM agent share a voice room and play together.

**Inputs:** Milestone 4.1 (combat works for solo), Milestone 2.4 (ventriloquism working).

**Deliverables:**
- Multi-participant LiveKit room: 2 human audio tracks + 1 DM agent
- Player identity tracking: DM associates each audio track with a character name and addresses them individually
- 500ms input buffer: when multiple players speak in quick succession, DM processes both before responding
- Turn management in combat: DM prompts each player by name for their declaration
- Companion behavior in multiplayer: both companions present (ventriloquized), interacting with each other
- Session joining: second player can join an existing room mid-session

**Acceptance criteria:**
- [ ] Two players connect to the same room and both hear the DM
- [ ] DM correctly identifies which player is speaking and addresses them by character name
- [ ] In combat, DM prompts each player individually for their turn
- [ ] Both players hear all NPC/companion voices (shared audio output)
- [ ] If both players speak within 500ms, DM acknowledges both inputs
- [ ] Second player joining mid-session receives a brief recap from the DM
- [ ] Session remains stable for 15+ minutes with two players (no audio dropouts or state desync)

**Key references:**
- *Technical Architecture — Multiplayer Architecture* (SFU model, player identity, input buffer)
- *Game Design — Session Structure* (party size variants)
- *Game Design — The Companion in Multiplayer* (companion behavior with multiple players)

---

## Phase 5: Client Application

### Milestone 5.1 — Home Screen and Session Flow

**Goal:** The app has a real home screen with the Catch-Up layer and Enter the World flow.

**Inputs:** Milestone 2.1 (LiveKit connection works), Milestone 3.3 (state mutations push to client).

**Deliverables:**
- Home screen with two-layer design: Catch-Up section (top) and "Enter the World" button (bottom)
- Catch-Up layer: displays placeholder cards for resolved activities, pending decisions, and world news (real async data comes in Phase 6)
- "Enter the World" button: taps opens LiveKit connection and transitions to session screen
- Session screen: full-screen atmospheric background with HUD overlay areas
- Session end flow: DM narrative wrap-up → session summary → return to Home
- Character summary bar on Home: name, level, location, HP

**Acceptance criteria:**
- [ ] App opens to Home screen with character summary and Catch-Up area
- [ ] Tapping "Enter the World" connects to LiveKit and transitions to session screen within 3 seconds
- [ ] Session screen displays atmospheric background appropriate to current location
- [ ] Disconnecting (or DM ending session) returns to Home screen gracefully
- [ ] Character summary bar shows accurate current data (name, level, location)
- [ ] Home screen works in both portrait and landscape orientations

**Key references:**
- *Game Design — Session Types — No Mode Selection* (the two-layer home screen design)
- *Game Design — Silent Layer, Voiced Layer* (Catch-Up is silent-first, tap-based)
- *Technical Architecture — Client Application — Screen Architecture*

---

### Milestone 5.2 — HUD System

**Goal:** The contextual HUD displays game state information during active sessions.

**Inputs:** Milestone 5.1 (session screen exists), Milestone 3.3 (state changes push to client).

**Deliverables:**
- Layer 1 (Always visible): location name bar (top), active quest objective (bottom), companion status indicator
- Layer 2 (Contextual): combat HUD (HP bars, status effects, phase indicator), dice roll display (animated d20 with result), notification toasts (quest updates, XP awards, item pickups)
- Layer 3 (Player-initiated): pull-up panels for Map, Character Sheet, Inventory, Quest Log
- Data channel listener: receives server pushes and updates HUD elements in real-time
- Auto-dismiss logic: contextual HUD elements appear on trigger and fade after 5 seconds of no updates
- UI sound effects for HUD interactions (confirm, cancel, notification, menu open/close)

**Acceptance criteria:**
- [ ] Location name updates when `location_changed` event is received
- [ ] Combat HUD appears when combat starts, showing HP bars for player and enemies
- [ ] Dice roll animation plays when a roll occurs, showing the result briefly
- [ ] Notification toasts appear for quest progression, XP awards, and item pickups
- [ ] Pull-up panels (Map, Character Sheet, Inventory, Quest Log) open and close smoothly
- [ ] UI sounds play for interactions (confirm tap, menu open/close, notification arrival)
- [ ] HUD never obscures the session experience — elements are minimal and auto-dismiss
- [ ] All HUD updates occur within 200ms of the server push

**Key references:**
- *Technical Architecture — HUD System — Layered Overlays* (three-layer design)
- *Audio Design — UI and Feedback Audio* (UI-001 through UI-010)
- *Game Design — Combat Design — HUD in Combat*

---

### Milestone 5.3 — Audio Engine and Environmental Soundscapes

**Goal:** The client plays layered ambient audio that changes with location, time, and game state.

**Inputs:** Milestone 5.1 (session screen exists), Milestone 3.3 (location changes push to client), audio assets generated.

**Deliverables:**
- Client audio engine: 8-channel mixer with volume buses (Voice, Music, Ambience, Effects, UI)
- Environmental soundscape player: loads and loops location-appropriate ambient audio, crossfades on location change (2-3 second linear crossfade)
- Voice ducking: ambience and music duck by 40-60% when TTS audio is playing (50ms attack, 200ms release)
- Sound effect player: triggered by `play_sound` data channel messages, plays from local asset library
- Randomized texture layer: intermittent ambient sounds (bird calls, footsteps, creaks) fire at randomized intervals on top of the base soundscape
- Audio settings: 5 volume sliders (Voice, Music, Ambience, Effects, UI) persisted locally
- Audio asset bundle: at least 5 environmental soundscapes (Market Square day, Millhaven, Forest road, Ruins entrance, Tavern) and core combat/UI sound effects

**Acceptance criteria:**
- [ ] Entering the world plays the ambient soundscape for the player's current location
- [ ] Moving to a new location crossfades to the new soundscape over 2-3 seconds (no hard cut)
- [ ] When the DM speaks, ambient audio audibly ducks and returns smoothly when speech ends
- [ ] `play_sound` data messages trigger the correct sound effect on the client with < 100ms latency
- [ ] Randomized texture sounds (bird calls, etc.) play at varied intervals without noticeable pattern
- [ ] Volume sliders work and persist between sessions
- [ ] All 5 environmental soundscapes sound distinct and match their location identity
- [ ] The audio mix is clear at all times — voice is always understandable over ambience

**Key references:**
- *Audio Design — The Audio Stack* (7-layer hierarchy, mixing rules)
- *Audio Design — Environmental Soundscapes* (structure, specifications, AI generation prompts)
- *Audio Design — Audio Technical Requirements* (file formats, channel requirements, ducking specs)

---

## Phase 6: The World Experience

### Milestone 6.1 — Navigation and World Traversal

**Goal:** Players can move through the world by speaking, with the DM narrating transitions and scene-setting.

**Inputs:** Milestone 3.3 (move_player tool works), Milestone 5.3 (audio engine and soundscapes).

**Deliverables:**
- Voice-driven navigation: player says "I go to the market" or "let's head to Millhaven" → DM interprets intent → calls `move_player` → narrates the transition → client receives location_changed → soundscape crossfades → HUD updates
- Scene narration on arrival: DM reads location description (from entity data, condition-modified) as an atmospheric audio-first scene
- Exit awareness: DM knows available exits and can describe them when asked ("You could head north toward Millhaven or south back to the market")
- Travel narration: movement between distant locations includes brief travel narration (road description, companion commentary) rather than instant teleportation
- Hidden element discovery: DM can reveal hidden elements in locations when player investigates (skill check required for some)

**Acceptance criteria:**
- [ ] Player can navigate the full MVP map by voice: Market Square ↔ Road ↔ Millhaven ↔ Greyvale Ruins Entrance ↔ Ruins Interior ↔ Hollow Breach
- [ ] Each location has a unique scene narration that matches the audio design (leads with sound, then feeling)
- [ ] Moving between locations triggers soundscape crossfade and HUD location update
- [ ] DM describes available exits when the player asks "where can I go?"
- [ ] Travel between distant locations (Market Square → Millhaven) includes a brief journey narration
- [ ] Hidden elements can be discovered through investigation ("I examine the wall" → skill check → hidden passage revealed)
- [ ] Condition overlays work: visiting Market Square at night produces a different description than during the day

**Key references:**
- *Game Design — Navigation* (voice-first movement, scene narration, exit awareness)
- *World Data & Simulation — Content Style Guide — Location Descriptions* (audio-first writing, conditions as overlays)
- *MVP Spec — Appendix: Starter Content Entities — Locations* (the actual location data)

---

### Milestone 6.2 — Companion Implementation

**Goal:** The companion is a living presence — talking, reacting, guiding, fighting alongside the player.

**Inputs:** Milestone 2.4 (ventriloquism), Milestone 3.4 (background process with proactive speech), Milestone 4.1 (combat).

**Deliverables:**
- Companion personality layer in DM system prompt: Kael's personality, speech style, mannerisms, backstory hints, emotional state tracking
- Proactive companion speech: environmental observations, idle chatter, reactions to player decisions, post-combat check-ins (managed by background process)
- Guidance integration: companion delivers level 2 guidance hints (rephrased from quest `global_hints` in companion's voice)
- Combat companion: companion takes actions in combat, makes tactical callouts, can be knocked unconscious
- Companion meeting: scripted scene in session 1 where the player meets Kael (per the meeting scenario in game design doc)
- Companion emotional state: tracks relationship progression, adjusts warmth and openness of dialogue over sessions

**Acceptance criteria:**
- [ ] Companion speaks proactively during exploration (environmental comments, idle observations) without being prompted
- [ ] Companion has a distinctly different voice from the DM and all NPCs
- [ ] When the player is stuck, the companion offers hints after appropriate delay (level 2 guidance)
- [ ] Companion participates in combat with their own actions and tactical commentary
- [ ] Companion can be knocked unconscious in combat (the silence where their voice was is noticeable)
- [ ] The Kael meeting scene plays out naturally in session 1 and feels organic, not scripted
- [ ] Companion remembers previous interactions within the same session (references earlier events)
- [ ] Companion reacts emotionally to player decisions (pleased, concerned, annoyed — appropriate to Kael's personality)

**Key references:**
- *Game Design — The Companion — Your Other Voice in the Dark* (full companion design, Kael archetype, meeting scenario)
- *Audio Design — Voice Design — Companion Voices — Kael* (voice characteristics, emotional range)
- *Game Design — Player Guidance* (escalating nudge system, companion as level 2)

---

### Milestone 6.3 — The Greyvale Arc: Playable Content

**Goal:** The MVP story is playable from session 1 through session 4. A complete narrative experience.

**Inputs:** All of Phase 3 (game mechanics), Milestone 6.1 (navigation), Milestone 6.2 (companion).

**Deliverables:**
- Session 1 content: opening scene in Market Square, companion meeting, guild assignment, first exploration
- Session 2 content: travel to Millhaven, investigation, NPC conversations (Elder Yanna), first signs of Hollow activity
- Session 3 content: Greyvale Ruins dungeon — exploration, environmental puzzles, combat encounter, artifact discovery, Hollow Breach
- Session 4 content: return with artifact, faction reactions, Scholar Emris analysis, consequences and hooks
- NPC interactions: all 3 tier 1 NPCs fully functional with personality, gated knowledge, disposition tracking
- Quest progression: The Greyvale Anomaly advances through all 5 stages based on player actions
- Boss/set-piece encounter in the Ruins: multi-phase or environmental challenge
- Hollow audio design: corruption escalation stages audible as player goes deeper into ruins

**Acceptance criteria:**
- [ ] A playtester can complete sessions 1-4 in sequence with a coherent narrative
- [ ] Each NPC interaction feels like talking to a distinct character (voice, personality, knowledge appropriate to disposition)
- [ ] The Greyvale Ruins feel progressively more unsettling as the player goes deeper (Hollow audio stages 1→3)
- [ ] The artifact discovery is a meaningful narrative moment (companion reacts, DM narrates weight of the discovery)
- [ ] Session 4's faction reactions differ based on which faction the player aligns with
- [ ] Quest stages advance correctly based on completion conditions
- [ ] At least one combat encounter and one non-combat challenge (social/puzzle) occur across the 4 sessions
- [ ] The story ends with clear hooks for continued play (the mystery isn't resolved, the world is larger than the Greyvale)
- [ ] Total play time across 4 sessions: approximately 2-3 hours

**Key references:**
- *MVP Spec — Session-by-Session Content* (sessions 1-4 detailed arc)
- *MVP Spec — Appendix: Starter Content Entities* (all entity data)
- *Game Design — Boss Fights* (multi-phase encounters, set pieces)
- *Audio Design — The Sound of the Hollow* (5-stage escalation for ruins)

---

## Phase 7: Async System

### Milestone 7.1 — Async Activity Engine

**Goal:** Timer-based activities resolve in real time with pre-rendered narrated outcomes.

**Inputs:** Milestone 1.1 (database/Redis), Milestone 2.2 (TTS pipeline for pre-rendering).

**Deliverables:**
- Async activity tables: `async_activities` (player_id, type, parameters, start_time, duration, status, result, narration_audio_url)
- Activity creation endpoints: REST API for starting crafting, training, and companion errand activities with parameter choices
- Timer resolution: background worker checks for completed activities on a regular interval (every 5 minutes), generates outcomes using rules engine
- Narration generation pipeline: completed activity → LLM generates outcome narration (concise, in-character, presents a decision) → TTS synthesizes to audio → stored in player's async content bucket
- Companion errand system: errand type (scout/social/acquire/relationship) + destination → timer → outcome with narrative and information
- Soft timer ranges: actual completion time randomized within a range (e.g., "4-8 hours" completes at a random point within that window)

**Acceptance criteria:**
- [ ] Player starts a crafting activity via REST → activity appears in database with status "in_progress"
- [ ] After the timer expires, the background worker resolves the activity and generates a narrated outcome
- [ ] Narration audio is generated and stored (verify audio file exists at the URL)
- [ ] Outcome narration is in-character, concise (15-30 seconds), and ends with a decision point
- [ ] Companion errand returns with narrative information relevant to the errand type
- [ ] Soft timer ranges work: 10 activities set for "4-8 hours" resolve at varied times within that window
- [ ] Multiple concurrent activities can run simultaneously for one player (3-4 at once)
- [ ] Activity resolution cost is < $0.005 per activity (LLM + TTS)

**Key references:**
- *Game Design — Asynchronous Play — Async Activity Types* (crafting, training, companion errands)
- *Game Design — Async Technical Implementation* (pre-rendered audio, batch processing)
- *Cost Model — Async Cost Breakdown*

---

### Milestone 7.2 — Catch-Up Layer and Home Screen Integration

**Goal:** The home screen's Catch-Up layer shows real async data and supports the full check-in flow.

**Inputs:** Milestone 7.1 (async activities resolve), Milestone 5.1 (home screen exists).

**Deliverables:**
- Catch-Up feed API: endpoint returns all pending items for a player (resolved activities, pending decisions, world news, in-flight activity progress)
- Resolved activity cards: display text summary + play button for narrated audio + decision buttons
- Decision submission: tapping a choice sends REST request, updates activity state, triggers next step (new activity, state change, etc.)
- World news summary: pre-rendered audio clip summarizing simulation changes since last check-in (generated on simulation tick)
- In-flight activity progress: shows intermediate narrative states for activities still running
- Companion idle content: when nothing is pending, display companion idle chatter (pre-rendered audio from pool)
- Push notifications: narrative hooks for resolved activities, god whispers, significant world events
- New activity launcher: UI to start new crafting/training/errand with parameter selection

**Acceptance criteria:**
- [ ] Opening the app shows resolved activities with playable narrated audio
- [ ] Tapping a decision button resolves the activity and triggers the appropriate next step
- [ ] World news summary plays automatically if significant changes occurred (skipped if nothing changed)
- [ ] When nothing is pending, companion idle chatter or world micro-observations appear
- [ ] Push notifications arrive for resolved activities with narrative text (not "timer complete")
- [ ] Player can start new activities from the launcher with parameter choices
- [ ] In-flight activities show progress text (intermediate narrative state)
- [ ] The entire check-in flow completes in under 5 minutes
- [ ] The Catch-Up layer works silently — all functionality accessible via tap without any audio playback

**Key references:**
- *Game Design — The Catch-Up Layer (Home Screen Integration)* (silent-first design, feed organization)
- *Game Design — The Five-Minute Check-In* (the full check-in flow)
- *Game Design — The Frequent Checker* (companion idle, micro-observations, activity density)
- *Game Design — Silent Layer, Voiced Layer* (context-aware play)

---

## Phase 8: Polish and Integration

### Milestone 8.1 — Adaptive Music System

**Goal:** Music responds to game state — exploration, tension, combat, wonder, the Hollow — fading in and out appropriately.

**Inputs:** Milestone 5.3 (audio engine), audio assets generated (music stems).

**Deliverables:**
- Music state machine: silence → exploration → tension → combat → wonder → sorrow → hollow (transitions triggered by game state events)
- Stem-based playback: each music state has layered stems that can be mixed independently
- Crossfading between states: smooth 3-5 second transitions between music states
- Voice ducking on music: music ducks 50-70% when DM or companion speaks
- Hollow music dissolution: in corrupted areas, music degrades progressively (pitch drift, tempo instability, melody fragmentation)
- Combat music intensity scaling: lighter music for minor encounters, full intensity for boss fights

**Acceptance criteria:**
- [ ] Entering a calm exploration area fades in exploration music after a natural delay
- [ ] Approaching a Hollow-corrupted area transitions music to tension state
- [ ] Combat starting triggers combat music with an audible shift in energy
- [ ] Music ducks appropriately when the DM speaks — dialogue is always clear over music
- [ ] Hollow corruption degrades music audibly (pitch drift, rhythm instability)
- [ ] Music transitions are smooth, never jarring — crossfades feel natural
- [ ] Wonder stinger plays at key narrative revelation moments
- [ ] Silence is used deliberately — not every moment has music

**Key references:**
- *Audio Design — Music Design* (principles, states, cultural inflection, Hollow dissolution)
- *Audio Design — Music Stems — MVP Asset Inventory* (MUS-001 through MUS-008)

---

### Milestone 8.2 — Character Creation Flow

**Goal:** New players create their character through a voiced conversation with the DM — not a form.

**Inputs:** Milestone 2.3 (DM conversation), Milestone 5.1 (client app).

**Deliverables:**
- Prologue narration: 60-90 second pre-recorded/high-quality TTS world introduction (plays before character creation)
- Conversational creation flow: DM asks about race → class → patron deity → personality through natural voice dialogue
- Visual assist cards: client displays contextual cards (race options with brief descriptions, class archetypes, patron deity summaries) when the DM presents choices
- Character stat generation: backstory elements from the conversation map to starting stats, skills, and equipment
- Persistence: completed character saved to database, available for all subsequent sessions
- Starter culture placement: character placed in the Sunward Accord starting location

**Acceptance criteria:**
- [ ] Prologue plays and sets the world's tone before creation begins
- [ ] Player can create a full character through voice conversation (no text input required)
- [ ] Visual cards appear at appropriate moments showing available choices
- [ ] DM responds naturally to unusual or creative player inputs during creation
- [ ] Character creation takes 10-15 minutes (not rushed, not dragging)
- [ ] Created character has appropriate starting stats, equipment, and skills for their chosen class/patron
- [ ] Character persists and is loaded correctly on next session

**Key references:**
- *Game Design — Character Creation* (the narrated creation flow)
- *Game Design — Class System* (archetype options for MVP)
- *Game Design — The Opening Experience* (prologue, creation, placement, normalcy)

---

### Milestone 8.3 — Session Lifecycle and Persistence

**Goal:** Sessions start cleanly, persist state, handle disconnections, and end narratively.

**Inputs:** All prior milestones (this is integration work).

**Deliverables:**
- Session start: create room → dispatch agent → build prompt from persistent state → DM greets player with recap of last session
- Session persistence: all state mutations written to PostgreSQL during session, conversation history compressed and stored at session end
- Reconnection handling: if player disconnects, room stays alive for 2 minutes. Reconnecting player hears "Welcome back" and can continue
- Narrative session ending: DM detects low-engagement signals or player request → begins wrap-up narration → distributes rewards → plants hooks → session summary generated
- Session summary compression: full conversation history compressed to a structured summary (key events, decisions, outcomes) stored for next session's recap
- Graceful degradation: if LLM errors occur mid-session, agent retries with fallback behavior (simplified responses until recovery)

**Acceptance criteria:**
- [ ] Starting a new session loads the player's persistent state (location, inventory, quest progress, companion relationship)
- [ ] DM opens with a natural recap of the previous session based on the stored summary
- [ ] Disconnecting and reconnecting within 2 minutes resumes the session seamlessly
- [ ] Disconnecting for > 2 minutes ends the session and persists all state
- [ ] Player saying "I need to go" or "let's wrap up" triggers a narrative session ending
- [ ] Session summary is generated and stored (verify it contains key events and decisions)
- [ ] Next session's recap accurately reflects what happened in the previous session
- [ ] A simulated LLM error mid-session doesn't crash the agent (verify graceful fallback)

**Key references:**
- *Technical Architecture — Session Lifecycle* (room creation → state loading → gameplay → teardown)
- *Technical Architecture — Session Persistence and Recovery* (reconnection, summary compression)
- *Game Design — Session Structure — Session Flow* (Gathering through Hearth)

---

### Milestone 8.4 — God Whisper System

**Goal:** The patron deity reaches out to the player through atmospheric voiced messages.

**Inputs:** Milestone 7.1 (async narration pipeline), Milestone 5.3 (audio engine).

**Deliverables:**
- Divine favor tracking: accumulates based on player actions aligned with patron deity's domain
- God whisper trigger: when divine favor crosses a threshold, or at story-critical moments, a whisper is generated
- God voice synthesis: each patron deity has a distinct `voice_id` and audio treatment (see audio design doc)
- Audio treatment layer: god whispers have environmental audio processing (Kaelen = reverb/stone hall, Syrath = close/intimate/stereo shift, Veythar = harmonic shimmer)
- Async delivery: god whispers appear as pending decisions in the Catch-Up layer with pre-rendered audio
- Sync delivery: god whispers can also occur during active sessions at dramatic moments (DM triggers the whisper)
- God whisper stinger: the STG-006 audio cue plays before the god speaks

**Acceptance criteria:**
- [ ] Accumulating divine favor through aligned actions triggers a god whisper
- [ ] The god's voice sounds distinctly different from the DM and all NPCs (unique voice_id + audio treatment)
- [ ] The whisper content is atmospheric and cryptic — guidance without explicit instruction
- [ ] The god whisper stinger plays before the god speaks, creating an "other-worldly" audio transition
- [ ] God whispers in async appear in the Catch-Up layer with playable audio
- [ ] God whispers in sync sessions are triggered at appropriate dramatic moments
- [ ] At least 3 patron deities are supported for MVP (Kaelen, Syrath, Veythar) with distinct voices

**Key references:**
- *Audio Design — Voice Design — God Voices* (Kaelen, Syrath, Veythar, Aelora, Mortaen)
- *Game Design — Asynchronous Play — World Events and God Whispers*
- *Aethos Lore — The Pantheon* (god personalities and domains)

---

## Phase 9: End-to-End Validation

### Milestone 9.1 — Internal Playtest: Full Arc

**Goal:** The complete MVP experience is played start-to-finish by internal testers and evaluated against quality rubrics.

**Inputs:** All prior milestones.

**Deliverables:**
- Playtest protocol: structured rubric for evaluating DM quality (6 categories), system quality (6 categories), session quality (4 categories) — all scored 1-5
- 3 complete playthroughs of sessions 1-4 by different testers
- Bug list triaged by severity
- Quality scores recorded per rubric category
- Async loop tested: testers use the Catch-Up layer between sessions and verify activities resolve with narrated outcomes
- Latency audit: measure actual end-to-end latency across all sessions, verify it meets the 1.2-2.0s target for 90% of turns

**Acceptance criteria:**
- [ ] All 3 playthroughs complete sessions 1-4 without blocking bugs
- [ ] Average DM quality score ≥ 3.5/5 across all rubric categories
- [ ] Average system quality score ≥ 4.0/5 (mechanics, state persistence, audio, HUD)
- [ ] No critical bugs (crashes, state loss, stuck states) in any playthrough
- [ ] Async check-ins between sessions feel meaningful (testers report value, not emptiness)
- [ ] Latency meets target: 90% of voice turns complete within 2.0 seconds
- [ ] At least one tester reports an emotional moment (connection with companion, Hollow dread, narrative satisfaction)
- [ ] All identified bugs documented with reproduction steps

**Key references:**
- *Technical Architecture — Testing and Quality Strategy — Tier 4* (structured rubrics, playtest protocol)
- *Technical Architecture — Latency Budget*
- *MVP Spec — Success Criteria* (the 7 core questions)

---

## Summary

| Phase | Milestones | Description |
|---|---|---|
| **1: Foundation** | 1.1, 1.2 | Project setup, database, content seeding |
| **2: Voice Pipeline** | 2.1, 2.2, 2.3, 2.4 | LiveKit, STT/TTS, DM conversation, ventriloquism |
| **3: Game Mechanics** | 3.1, 3.2, 3.3, 3.4 | World queries, dice/mechanics, state mutation, background process |
| **4: Combat & Multiplayer** | 4.1, 4.2 | Phase-based combat, multi-player rooms |
| **5: Client App** | 5.1, 5.2, 5.3 | Home screen, HUD, audio engine |
| **6: World Experience** | 6.1, 6.2, 6.3 | Navigation, companion, Greyvale arc content |
| **7: Async** | 7.1, 7.2 | Activity engine, Catch-Up layer |
| **8: Polish** | 8.1, 8.2, 8.3, 8.4 | Music, character creation, session lifecycle, god whispers |
| **9: Validation** | 9.1 | Internal playtest with quality rubrics |

**Total: 9 phases, 19 milestones.** Each milestone is scoped for focused Claude Code execution with clear acceptance criteria. Dependencies flow strictly downward — no milestone requires work from a later phase.
