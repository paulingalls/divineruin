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
| **Player Resonance System** | `player_resonance_system.md` | Voice affect analysis: speech rate, energy, engagement detection from Deepgram word timestamps and raw audio. stt_node override pattern, affect vector schema, DM behavioral adaptation. **Phased implementation plan (A-D) that hooks into milestones 2.3, 5.4, 6.2, and 9.1.** |

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
- [x] `docker compose up` starts PostgreSQL, Redis, and a stub Python server
- [x] Database migrations run cleanly and create all tables
- [x] A test script can INSERT and SELECT a sample location entity as JSONB
- [x] Redis SET/GET works from the Python server
- [x] CI runs on push and reports lint + type check results
- [x] Expo dev client boots to a blank screen on iOS simulator or Android emulator

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
- [x] `python scripts/seed_content.py` loads all entities without errors
- [x] `SELECT * FROM locations WHERE id = 'loc_market_square'` returns the full JSON entity with description, ambient_audio, exits, hidden_elements, and conditions
- [x] `SELECT * FROM npcs WHERE id = 'npc_torin'` returns personality, speech_style, knowledge tiers, and disposition data
- [x] `SELECT * FROM quests WHERE id = 'quest_greyvale_anomaly'` returns all 5 stages with objectives, hints, completion conditions, and rewards
- [x] Location exit references are valid (every exit's `destination` matches an existing location ID)
- [x] NPC knowledge gating has at least 2 disposition tiers with different information per tier

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
- [x] Client connects to a LiveKit room and publishes a mic audio track
- [x] VAD correctly detects speech start and end (visual indicator toggles)
- [x] Server agent receives audio, and the client receives audio back within 500ms
- [x] Room cleanup occurs when the user disconnects (no orphaned rooms)
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
- [x] User speaks a sentence and hears a synthesized voice repeat what they said within 2 seconds
- [ ] STT transcript accuracy is reasonable for clear English speech (>90% WER on simple sentences)
- [x] TTS output is natural-sounding and intelligible
- [x] Latency logs show: VAD (< 500ms) + STT (< 400ms) + TTS TTFB (< 300ms) = total < 1.5s for first audio byte
- [x] Pipeline handles silence gracefully (no false triggers, no stuck states)
- [x] Multiple sequential utterances work without degradation

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
- [x] User can have a 5-minute freeform voice conversation with the DM
- [x] DM maintains consistent persona across multiple exchanges (doesn't break character)
- [x] DM responses are descriptive and audio-first (describes sounds and feelings, not visual details)
- [x] Interruption works: speaking over the DM causes it to stop and acknowledge the new input
- [x] Conversation history persists across turns (DM remembers what was said earlier in the conversation)
- [ ] Response latency stays under 2.5 seconds for 90% of turns

**Key references:**
- *Technical Architecture — DM Agent Architecture* (three-layer design, LLM selection)
- *Game Design — Session Structure* (DM persona and behavior)
- *World Data & Simulation — Content Style Guide* (audio-first writing principles)
- *Audio Design — Voice Design — The DM Voice* (voice characteristics and TTS direction)
- *Player Resonance System — Phase A* (transcript-only affect baseline: add stt_node override, engagement detection, affect injection into hot layer. This milestone is the hook point.)

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
- [x] When the DM narrates, the player hears the DM voice
- [x] When an NPC speaks (e.g., "Torin says..."), the player hears a distinctly different voice
- [x] The companion (Kael) has a third distinct voice
- [x] Transitions between narrator and character voices feel natural (no jarring gaps or overlaps)
- [x] Emotion tags produce audible tonal shifts in TTS output (weary sounds different from urgent)
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
- [x] DM can answer "where am I?" by calling `query_location` and narrating the description
- [x] DM can answer "tell me about Torin" by calling `query_npc` and roleplaying using the returned personality/speech_style
- [x] NPC knowledge gating works: at neutral disposition, `query_npc` for Torin returns only tier 1 knowledge; at friendly, returns tier 2
- [x] `query_inventory` returns the player's current items and the DM can describe them
- [x] Second call to same entity within TTL serves from Redis (verify with logs)
- [x] DM naturally integrates queried information into narration (doesn't dump raw data)

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
- [x] DM appropriately calls for a skill check when the player attempts something uncertain (e.g., "I try to persuade the guard")
- [x] Dice roll produces a valid d20 result with correct modifier application
- [x] The player hears a dice roll sound effect on their device when a check occurs
- [x] `narrative_hint` provides appropriate flavor text that the DM can weave into narration (e.g., "barely succeeded" or "critical failure")
- [x] Rules engine unit tests pass for all 15 skills across the full modifier range
- [x] DM never exposes raw numbers to the player — all mechanics are narrated

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
- [x] "I go to Millhaven" → DM calls `move_player` → player location updates → client receives `location_changed` event → DM narrates the new scene
- [x] "I pick up the tablet" → `add_to_inventory` → item appears in player inventory → client HUD updates
- [x] Quest stage advances when completion conditions are met (e.g., `location_reached: loc_millhaven`)
- [x] When quest advances, the DM receives stage-specific narration beats and weaves them in
- [x] XP awards trigger visible feedback on the client
- [x] State mutations persist to PostgreSQL within 5 seconds (verify with DB query after mutation)
- [ ] If the database write fails, the retry queue picks it up (simulate failure and verify retry)
- [x] NPC disposition changes affect subsequent `query_npc` results (higher disposition reveals more knowledge)

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
- [x] When the player moves to a new location, the DM's system prompt updates to reflect the new location within 2 seconds (without the player asking)
- [x] Per-turn context injection includes current quest stage hints relevant to the player's location
- [x] The companion occasionally speaks proactively — an environmental observation or a relevant comment — without being prompted by the player
- [x] Proactive speech respects priority: critical interrupts (danger) override routine (idle chat)
- [x] The DM references time of day appropriately (if the world clock says night, descriptions match)
- [ ] Background process doesn't degrade voice response latency (verify latency stays under 2.5s)

**Key references:**
- *Technical Architecture — Background Process* (event bus, timer fallback, proactive speech)
- *Technical Architecture — Per-Turn Context Injection* (on_user_turn_completed hook)
- *Game Design — Player Guidance* (escalating guidance system, companion suggestions)

---

## Phase 4: Combat

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
- [x] A full combat encounter plays out from start to finish: DM describes enemies, initiative occurs, player declares actions, dice roll, DM narrates outcomes, enemies act, repeat until resolved
- [x] Player hears distinct sound effects for their attacks (sword, spell, bow) and for enemy attacks
- [x] Player heartbeat audio fades in as HP drops below 50% and increases in rate as it drops further
- [x] Combat start and end stingers play at the right moments
- [x] The companion participates in combat with their own actions and tactical callouts
- [x] Falling to 0 HP triggers the death saving throw sequence
- [x] Combat concludes with XP award and loot narration
- [ ] The full combat encounter is exciting and understandable in audio only (playtest validation)

**Key references:**
- *Game Design — Combat Design* (phase-based rounds, key mechanics, sound design as combat system)
- *Audio Design — Combat Audio* (weapon impacts, player feedback, enemy audio, combat music)
- *Game Design — Death and Resurrection* (fallen state, death saving throws)

---

---

## Phase 5: Client Application

### Milestone 5.1 — Home Screen, Session Flow, and Client Foundation

**Goal:** The app has a brand-compliant home screen with the Catch-Up layer, Enter the World flow, complete session lifecycle (start → play → end → summary), and reconnection handling. This milestone establishes the full screen map and navigation skeleton that all subsequent client milestones build on.

**Inputs:** Milestone 2.1 (LiveKit connection works), Milestone 3.3 (state mutations push to client).

**Deliverables:**

*Home Screen — Two-Layer Design*
- **Title Bar** (top of home): "DIVINE | RUIN" centered in Cormorant Garamond 400, `ash`, letter-spacing 8px, with 1.5px teal (`hollow-muted`) vertical divider. Thin `charcoal` hairline rule underneath for separation.
- **Character Summary Bar** (below title): character name as uppercase label above the bar (Crimson Pro 400, `textSecondary`), settings gear icon right-aligned on name row. Bar shows level (IBM Plex Mono 400), class (capitalized, flex-fill), and compact HP bar with "HP" label right-aligned. Background: `backgroundElement` surface, `md` border radius.
- **Catch-Up Section** (scrollable, upper area): vertical feed of placeholder cards on `ink` surface with `charcoal` borders. Card types for MVP placeholders (real async data comes in Phase 7):
  - *Resolved activity card*: icon + title (Crimson Pro 400, `bone`) + summary text (`ash`) + play button for narrated audio + decision buttons (teal border, `hollow` text)
  - *Pending decision card*: NPC portrait placeholder + message preview + response options
  - *World news card*: timestamp (`caption` style) + summary + optional play button
  - *In-flight activity card*: title + progress indicator (teal bar on `charcoal` track) + time remaining (`ash`)
  - *Empty state*: companion idle chatter text (Crimson Pro 300 italic, `bone` at 0.7 opacity): "Kael is sharpening his blade and humming something off-key."
  - All cards are tap-based, completely silent by default — audio play buttons are opt-in, never auto-play
- **"Enter the World" Button** (bottom, always visible): prominent full-width button. Background: `hollow-faint` with 1px `hollow-muted` border. Text: "ENTER THE WORLD" in IBM Plex Mono 400, `hollow`, uppercase, `letter-spacing: 2px`. On press: subtle `hollow-glow` pulse animation. When no character exists, button text changes to "BEGIN YOUR JOURNEY" and flows into character creation.
- **Session History** (below Enter button, scrollable): compact list of recent sessions — date (`caption` style), duration, location, key events. Tapping opens session summary.

*Session Screen*
- Full-screen atmospheric background: dark, ambient-lit, color-tinted to match current location mood. Not a literal scene render — abstract/atmospheric. Uses `void` base with subtle radial gradient reflecting environment (warm amber tones for tavern, cool blue for night, muted green for forest, teal undertone for Hollow-corrupted areas).
- Grain overlay applied at 3% opacity (the SVG fractalNoise pattern from brand spec)
- HUD overlay areas reserved (implemented in 5.2): safe zones at top and bottom for persistent bar, clear center for contextual overlays
- Voice connection status indicator: 6px circle (`hollow` when connected + `glow-hollow` shadow, `ember` when disconnected, `slate` when connecting) with label (IBM Plex Mono 10px)
- Transcript view (optional, toggled): scrolling DM narration text in Crimson Pro 300, `bone` at 0.6 opacity, fading older lines. Hidden by default — available for accessibility or noisy environments.

*Session Start Flow*
1. Player taps "Enter the World"
2. Button shows loading state (pulsing `hollow` glow, text changes to "CONNECTING...")
3. Client sends `session_start` RPC to backend API
4. Backend creates LiveKit room, dispatches DM agent, returns room token
5. Client connects to LiveKit room with token — audio tracks bind
6. Client receives initial state push on data channel: `{ type: "session_init", character, location, quests, inventory, map_progress, world_state }`
7. Local cache (zustand stores) populated from state push — character-store, session-store
8. Atmospheric background transitions to match current location
9. Ambient soundscape begins (location's `ambient_sounds` tag → local audio file)
10. DM opening narration arrives on voice track
11. Screen transitions from Home → Session (cross-dissolve, 400ms)
12. Target: tapping button to hearing DM voice < 4 seconds

*Session End Flow*
1. Player says "let's stop" / "I need to go" OR taps end-session button (small, top-right, `ash` icon) OR DM initiates wrap-up (low engagement detected)
2. DM narrates brief closing (2-3 sentences, natural stopping point)
3. Server sends `session_end` event: `{ type: "session_end", summary, xp_earned, items_found, quest_progress, duration, next_hooks }`
4. Session screen transitions to **Session Summary Screen**:
   - Title: "Session Complete" (Cormorant Garamond 300, `parchment`)
   - Duration and date (`caption` style)
   - Recap text: key events in Crimson Pro 400, `bone` (generated by DM, 3-5 sentences)
   - Stats row: XP earned, items found, quest stages advanced (IBM Plex Mono, `hollow` for values)
   - Next hooks: 1-2 teaser sentences about what's ahead (Crimson Pro 300 italic, `ash`)
   - "Return Home" button: same style as Enter the World but text reads "RETURN HOME"
5. Tapping Return Home → Home screen. LiveKit room disconnects. Catch-Up layer may now show new async activity options.

*Reconnection Handling*
- On connection drop: "Reconnecting..." overlay with translucent `void` background, pulsing `hollow` indicator, ambient audio continues playing
- Client attempts automatic reconnection to the same LiveKit room (room stays alive for 5 minutes)
- On reconnect: server pushes current state snapshot → client resyncs all stores → DM acknowledges naturally ("Where were we...")
- If 5-minute grace period expires: server runs end-of-session flow. Next app open shows session summary on Home screen.
- If player force-quits mid-session: same 5-minute grace → auto-end. State is preserved to last DB write.

*Navigation Skeleton*
- expo-router file-based routing: `index.tsx` (Home), `session.tsx` (Active Session), session summary as a modal — no bottom tab navigation
- Settings screen: audio levels (5 sliders — Voice, Music, Ambience, Effects, UI), mic mode toggle (VAD vs tap-to-speak), notification preferences, account/logout
- All screens use `void` background, grain overlay, brand typography

*Zustand Stores*
- `session-store`: room connection state, session ID, session phase (idle/connecting/active/ending/summary), reconnection state
- `character-store`: name, level, class, race, patron, HP (current/max), location, divine favor, status effects — populated from server push, read by HUD and pull-ups
- `catchup-store`: array of catch-up cards (type, title, summary, audio URL, decisions, status) — populated from REST API
- `transcript-store`: rolling array of DM utterances for optional transcript view

*Data Channel Event Router*
- Single listener on the LiveKit data channel that receives JSON payloads
- Routes events by `type` field to the appropriate zustand store action
- Event types handled in this milestone: `session_init`, `session_end`, `location_changed`, `character_update`
- Extensible for Phase 5.2 events: `combat_ui_update`, `dice_result`, `item_acquired`, `quest_update`, `xp_awarded`, `status_effect`, `sound_effect`, `creation_cards`

**Acceptance criteria:**
- [x] App opens to Home screen with character summary and Catch-Up area
- [x] Tapping "Enter the World" connects to LiveKit and transitions to session screen within 3 seconds
- [x] Session screen displays atmospheric background appropriate to current location
- [x] Disconnecting (or DM ending session) returns to Home screen gracefully
- [x] Character summary bar shows accurate current data (name, level, class, HP)
- [x] Home screen works in both portrait and landscape orientations
- [x] Catch-Up section displays placeholder cards in correct brand styling (ink surface, charcoal borders, correct typography per text role)
- [x] Empty Catch-Up state shows companion idle chatter placeholder
- [x] Session Summary screen displays after session end with recap, XP, items, and next hooks
- [x] Reconnection overlay appears on connection drop and auto-reconnects within 5-minute window
- [x] Data channel event router correctly dispatches `session_init` and `location_changed` events to stores
- [x] Settings screen has 5 audio volume sliders that persist values to AsyncStorage (MMKV deferred — requires native prebuild)
- [x] All screens use brand tokens: `void` background, `parchment`/`bone`/`ash` text hierarchy, `hollow` accent, grain overlay
- [x] Session start flow completes (tap to DM voice) in under 4 seconds on device
- [x] Character-store, session-store, and catchup-store have unit tests covering server push → state update

**Key references:**
- *Technical Architecture — Client Architecture* (full section: screen map, data flow, session flow, performance targets, audio mixing)
- *Game Design — Session Types — No Mode Selection* (two-layer home screen, fluid entry, DM behavioral modes)
- *Game Design — Silent Layer, Voiced Layer* (Catch-Up is silent-first, tap-based; seamless handoff to voiced)
- *Brand Spec — Design Tokens* (colors, typography, spacing) and *UI Patterns* (surface hierarchy, text roles, HUD elements)

---

### Milestone 5.2 — HUD: Persistent Bar and Contextual Overlays

**Goal:** The server-pushed, reactive HUD — a persistent glance bar (Layer 1) and contextual overlays that appear and auto-dismiss (Layer 2). These are the elements the server pushes at the player during gameplay: combat state, dice rolls, item pickups, quest updates, XP gains, and character creation cards. The HUD is smartwatch-level: minimal, informational, never competing with audio. Every element uses brand tokens and feels like part of the world, not a game UI bolted on top.

**Inputs:** Milestone 5.1 (session screen, data channel router, stores), Milestone 3.3 (state mutations push to client).

**Deliverables:**

*Layer 1 — Persistent Bar (always visible during session)*

A thin strip (<10% screen height) at the top of the session screen. `ink` background at 85% opacity with `charcoal` bottom border. Contains:

- **Location name** (left): current location in IBM Plex Mono 400, 10px, uppercase, `ash`, `letter-spacing: 2px`. Updates on `location_changed` event. Example: `GREYVALE · MARKET DISTRICT`
- **Voice state indicator** (right of location): 6px circle — `hollow` + `glow-hollow` shadow when DM is speaking, `hollow-muted` when listening/idle, pulsing when processing. "LIVE" label in IBM Plex Mono 10px, `hollow` when voice connection active.
- **HP bar** (right side): compact horizontal bar, 3px height, 60px wide. Track: `charcoal`. Fill: gradient from `ember` (low) through `parchment` (full). Updates on `character_update` event. No number label — color tells the story. When HP < 30%, bar pulses subtly.
- **Status effect icons** (right, next to HP): small icons (16px) for active effects (poisoned, blessed, burning, etc.). `hollow` tint for buffs, `ember` tint for debuffs. Appear/disappear on `status_effect` events with 200ms fade.
- **Active quest objective** (bottom strip, optional): single-line quest hint in Crimson Pro 300, 13px, `bone` at 0.7 opacity, with `hollow` arrow prefix. Example: `▸ Find the cartographer`. Updates on `quest_update` event. Auto-hides after 10 seconds of no quest change, reappears on new update. Can be dismissed by tap.

*Layer 2 — Contextual Overlays (server-pushed, auto-dismiss)*

These overlays appear over the session screen center when triggered by data channel events. They use `react-native-reanimated` for 60fps entrance/exit animations. Each overlay type has specific behavior:

- **Dice Roll Overlay** — Triggered by `dice_result` event: `{ type: "dice_result", roll, modifier, total, dc, success, narrative_hint }`
  - Centered card, `ink` background with `charcoal` border, `radius-md`
  - Animated d20 icon that "tumbles" (rotate + scale spring animation, 600ms) then lands on the result
  - Roll value: IBM Plex Mono 400, 32px, `parchment`. Modifier shown smaller: "+3" in `ash`
  - Result label: "SUCCESS" in `hollow` or "FAILURE" in `ember`, IBM Plex Mono 400, 11px, uppercase
  - `narrative_hint` text below: Crimson Pro 300 italic, 13px, `ash` (e.g., "barely succeeded", "critical failure")
  - Entrance: scale from 0.8 → 1.0 + fade in (200ms spring). Exit: fade out (300ms) after 3.5 seconds
  - Haptic feedback: light impact on roll, medium impact on success, heavy on critical
  - Audio: dice roll sound (DICE-001) on appearance, success/fail sting on result

- **Combat Tracker** — Triggered by `combat_ui_update` event: `{ type: "combat_ui_update", phase, combatants[], active_turn, round }`
  - Appears at bottom of screen, slides up (300ms spring). Stays visible for entire combat. Slides down on `combat_end`.
  - `ink` background at 90% opacity, `charcoal` top border, `radius-lg` top corners
  - Phase indicator: current phase name in IBM Plex Mono 400, 10px, uppercase, `hollow`. "DECLARATION" / "RESOLUTION" / "OUTCOME"
  - Round counter: "ROUND 3" in IBM Plex Mono 300, 10px, `ash`
  - Combatant rows: each shows name (Crimson Pro 400, 14px, `bone` for allies, `ember` for enemies), HP bar (same 3px style as persistent bar), and status effect icons
  - Active turn highlight: combatant whose turn it is gets `hollow-faint` background highlight
  - Player's combatant row is always visible; enemy details collapse to name + HP bar to save space
  - Height: max 30% of screen. If more combatants than fit, scrollable within the panel.
  - Updates in-place on each `combat_ui_update` push — HP bars animate smoothly (300ms ease-out)

- **Item Card Popup** — Triggered by `item_acquired` event: `{ type: "item_acquired", item_id, name, rarity, description, type, stats }`
  - Centered card, `ink` background, border color by rarity: `charcoal` (common), `hollow-muted` (uncommon), `hollow` (rare), `divine` (legendary)
  - Item name: Cormorant Garamond 400, 18px, `parchment`
  - Rarity label: IBM Plex Mono 300, 9px, uppercase, rarity color, `letter-spacing: 3px`
  - Description: Crimson Pro 300, 14px, `bone`, max 3 lines
  - Key stats (if any): IBM Plex Mono 400, 11px, `ash`
  - Entrance: slide up from bottom + fade (250ms spring). Exit: fade out after 5 seconds or on tap.
  - Haptic: light impact on appearance

- **Quest Update Toast** — Triggered by `quest_update` event: `{ type: "quest_update", quest_name, stage_name, objective }`
  - Top notification bar, full width, `ink` background at 90% opacity
  - "QUEST UPDATED" label: IBM Plex Mono 400, 9px, `hollow`, uppercase, `letter-spacing: 2px`
  - Quest + stage name: Crimson Pro 400, 14px, `bone`. New objective below in 13px, `ash`
  - Entrance: slide down from top (200ms spring). Exit: slide up after 3 seconds.
  - Audio: quest update sting (STG-001)

- **XP / Level-Up Notification** — Triggered by `xp_awarded` event: `{ type: "xp_awarded", amount, total, level_up, new_level }`
  - *XP gain (no level-up)*: subtle bottom toast. "+75 XP" in IBM Plex Mono 400, 12px, `hollow`. Fade in/out, 2.5 seconds. No haptic.
  - *Level-up*: larger centered overlay. "LEVEL UP" in Cormorant Garamond 300, 28px, `parchment` with `text-glow-hollow`. New level number below in IBM Plex Mono 400, 48px, `hollow`. Class title in IBM Plex Mono 300, 11px, `ash`, uppercase. Entrance: scale 0.5 → 1.0 + fade (400ms spring). Stays 5 seconds. Heavy haptic pulse. Audio: level-up stinger (STG-002).

- **Character Creation Cards** — Triggered by `creation_cards` event: `{ type: "creation_cards", category, options[] }`
  - Horizontally scrollable row at bottom third of screen
  - Each card: `ink` background, `charcoal` border, `radius-md`, 140px wide
  - Card illustration area (top): placeholder for race/class/patron art (dark `slate` rectangle for now)
  - Card title: Cormorant Garamond 400, 16px, `parchment`, centered
  - Card description: Crimson Pro 300, 12px, `ash`, 3-4 lines max
  - Selected card: border transitions to `hollow`, subtle `glow-hollow` shadow. Unselected cards fade to 50% opacity.
  - Player speaks their choice; server sends `creation_card_selected` event to highlight the chosen card
  - Dismissed when server advances to next creation step

*Data Channel Event Handling (extending 5.1 router)*
- New event types routed to HUD: `combat_ui_update`, `combat_end`, `dice_result`, `item_acquired`, `quest_update`, `xp_awarded`, `status_effect`, `sound_effect`, `creation_cards`, `creation_card_selected`
- Overlay manager: zustand store (`hud-store`) that tracks active overlays, manages stacking (max 2 simultaneous overlays — newer replaces older except combat tracker which persists), and handles auto-dismiss timers
- Events that update persistent bar (location, HP, status effects) go directly to `character-store` and `session-store`
- Events that trigger overlays create entries in `hud-store` with type, payload, and TTL

*UI Sound Effects*
- Triggered client-side by overlay lifecycle events (not server-pushed)
- Sounds: dice roll (DICE-001), quest sting (STG-001), level-up sting (STG-002), item pickup chime (UI-001), menu open/close (UI-006/UI-007), notification arrival (UI-003), confirm tap (UI-001), cancel (UI-002), error (UI-003)
- Played through the UI Audio channel at full volume (not ducked)
- Sound file lookup via `sound-registry.ts`, playback via `sfx-player.ts`

*Haptic Feedback*
- `expo-haptics` integration at key moments:
  - Dice roll landing: `Haptics.impactAsync(ImpactFeedbackStyle.Light)`
  - Dice success: `Haptics.impactAsync(ImpactFeedbackStyle.Medium)`
  - Critical hit: `Haptics.impactAsync(ImpactFeedbackStyle.Heavy)`
  - Level-up: `Haptics.notificationAsync(NotificationFeedbackType.Success)`
  - Item acquired: `Haptics.impactAsync(ImpactFeedbackStyle.Light)`
  - HP below 30%: subtle periodic pulse `Haptics.impactAsync(ImpactFeedbackStyle.Light)` every 5 seconds

**Acceptance criteria:**
- [x] Location name updates when `location_changed` event is received
- [x] All HUD updates occur within 200ms of the server push
- [x] Persistent bar displays location, HP bar, voice state, and status effects — always visible during session, <10% screen height
- [x] Active quest objective appears on persistent bar and auto-hides after 10 seconds of inactivity
- [x] Combat tracker slides up when combat starts, shows combatant HP bars and phase indicator, stays for duration, slides away on combat end
- [x] Combat tracker HP bars animate smoothly when damage is dealt (no jumps)
- [x] Dice roll overlay shows animated die, result, modifier, and narrative hint — auto-dismisses after 3.5 seconds
- [x] Dice roll triggers correct haptic feedback (light on roll, medium on success, heavy on crit)
- [x] Item card popup appears with correct rarity border color and auto-dismisses after 5 seconds or on tap
- [x] Quest update toast slides down from top with quest name and new objective, auto-dismisses after 3 seconds
- [x] XP toast appears subtly for normal gains; level-up gets full centered overlay with stinger audio and heavy haptic
- [x] Character creation cards display as horizontally scrollable row; selected card highlights with `hollow` border
- [x] Overlay stacking works correctly: max 2 simultaneous (combat tracker + one other), newer non-persistent overlays replace older ones
- [x] UI sounds play for: dice roll, quest update, level-up, item pickup, notification arrival
- [x] All HUD elements use brand tokens: IBM Plex Mono for data/labels, Crimson Pro for narrative text, correct color roles per brand spec
- [x] HUD never obscures >30% of screen during normal play (combat tracker is the maximum overlay)
- [x] `hud-store` has unit tests covering overlay lifecycle (create, stack, auto-dismiss, manual dismiss)

**Key references:**
- *Technical Architecture — HUD System — Layered Overlays* (three-layer design, specific overlay types, auto-dismiss behavior)
- *Technical Architecture — Client Architecture — Data Flow* (data channel event types and payload shapes)
- *Technical Architecture — Client Architecture — Performance Targets* (overlay render <100ms)
- *Game Design — Combat Design — HUD in Combat* (simplified tactical view, dice roll animations, boss fight HUD)
- *Audio Design — UI and Feedback Audio* (UI-001 through UI-010, dice sounds DICE-001 through DICE-004, stingers STG-001, STG-002)
- *Brand Spec — UI Patterns* (surface hierarchy, text roles, HUD element styling, special treatments for combat/divine/Hollow)

---

### Milestone 5.3 — Pull-Up Panels (Player-Initiated HUD)

**Goal:** The four player-initiated information panels — Character Sheet, Inventory, Quest Log, and Map — slide over the session screen on demand. These are the "glance down and check something" surfaces: reading stats, browsing inventory, reviewing quest objectives, or checking the map. They read from local zustand stores (populated by server pushes in 5.1) so they open instantly with no loading state. The voice connection stays active while panels are open — the player can talk to the DM while browsing.

**Inputs:** Milestone 5.1 (session screen, zustand stores populated by server pushes), Milestone 5.2 (persistent bar with panel access icons).

**Deliverables:**

*Panel Shell (shared by all four panels)*
- Accessed by swipe-up gesture from bottom edge, or by tapping panel icons on the persistent bar (4 small icons: sword/shield for character, sack for inventory, scroll for quests, compass for map — all in `ash`, `hollow` when panel is open)
- Slides over session screen as a bottom sheet modal (bottom → up, 300ms spring via `react-native-reanimated`)
- `ink` background, `charcoal` top border, `radius-lg` top corners
- Drag handle: 40px wide, 4px tall, `slate`, centered at top. Dragging down dismisses.
- Max 75% screen height — session audio and atmospheric background remain visible/audible above
- Close button: small "×" in `ash` at top-right
- Tab bar at top of panel shell: four tabs to switch between panels without closing. Active tab label in `hollow`, inactive in `ash`. IBM Plex Mono 400, 10px, uppercase.
- Haptic: light impact on open (`Haptics.impactAsync(ImpactFeedbackStyle.Light)`)
- UI audio: menu open sound (UI-006) on open, menu close (UI-007) on dismiss

*Character Sheet Panel*
- **Header section**: character name in Cormorant Garamond 300, 22px, `parchment`. Race + class + level below in IBM Plex Mono 400, 10px, `ash`, uppercase. Example: `LEVEL 4 · ELARI · VEILWARDEN`
- **HP section**: current/max in large type. Current HP: IBM Plex Mono 400, 32px, `parchment`. Slash + max: 18px, `slate`. Full-width HP bar below (4px height, `charcoal` track, `ember → parchment` gradient fill). If status effects active, small icons displayed next to HP with tooltip on tap.
- **Stats grid**: 6 core stats (STR, DEX, CON, INT, WIS, CHA) in a 3×2 grid. Each cell: stat abbreviation in IBM Plex Mono 300, 9px, `ash`, uppercase. Value in IBM Plex Mono 400, 24px, `parchment`. Modifier below in 11px — `hollow` if positive ("+2"), `ember` if negative ("-1"), `ash` if zero ("+0"). Cells separated by `charcoal` borders.
- **Skills section** (scrollable): grouped by category (Physical, Mental, Social). Category header in IBM Plex Mono 300, 9px, `ash`, uppercase. Each skill: name in Crimson Pro 400, 14px, `bone`, modifier value in IBM Plex Mono 400, `ash`, right-aligned. Proficient skills marked with small `hollow` dot.
- **Divine Favor section**: patron deity name in Cormorant Garamond 300 italic, 16px, `divine`. Favor bar below: `divine-faint` track, `divine` fill. Favor level label in IBM Plex Mono 300, 9px, `ash`.
- **Equipment summary** (bottom): currently equipped weapon and armor names in Crimson Pro 400, 13px, `bone`. Tap to see item detail card (same as inventory item detail).
- Data source: `character-store` — all fields populated from `session_init` and kept current by `character_update` events

*Inventory Panel*
- **Grid layout**: 3 columns of item tiles on `ink` backgrounds with `radius-sm` corners
- **Item tile**: square aspect ratio. Placeholder icon area (dark `slate` with item type icon in `ash` — sword, potion, scroll, gem, etc.). Rarity border: `charcoal` (common), `hollow-muted` (uncommon), `hollow` (rare), `divine` (legendary). Item name below in IBM Plex Mono 300, 10px, `bone`, centered, max 1 line with ellipsis truncation. Quantity badge (top-right corner) if stackable: IBM Plex Mono 400, 9px, `parchment` on `charcoal` circle.
- **Item detail card** (on tap): slides in from right (250ms spring), covering the grid. Full item card matching the `item_acquired` popup design but persistent: name (Cormorant Garamond 400, 18px, `parchment`), rarity label, full description (Crimson Pro 300, 14px, `bone`), all stats (IBM Plex Mono 400, 11px, `ash`), lore text if available (Crimson Pro 300 italic, 13px, `ash`). "Back" button (top-left, `ash`) returns to grid.
- **Empty slots**: `charcoal` background with 1px dashed `slate` border. Fill from top-left.
- **Weight/capacity** (bottom bar): "12/30" in IBM Plex Mono 400, 11px, `ash`. Bar visualization matching HP bar style.
- **Sort options** (top-right): small dropdown — "Type" / "Rarity" / "Recent". IBM Plex Mono 300, 9px, `ash`.
- Data source: `character-store.inventory`

*Quest Log Panel*
- **Active quests section** (top, expanded by default):
  - Section header: "ACTIVE" in IBM Plex Mono 400, 9px, `hollow`, uppercase, `letter-spacing: 2px`
  - Each quest as a collapsible row. Collapsed: quest name in Crimson Pro 400, 15px, `bone`. Current stage name in 13px, `ash`. `hollow` dot indicator for active stage. Chevron icon (right, `ash`) to expand.
  - Expanded: current objective in Crimson Pro 300 italic, 14px, `bone`, indented. Stage history below: completed stages with `hollow` checkmarks and stage names in `ash`. Current stage highlighted with `hollow-faint` background. If hints are available (from `global_hints`), a subtle "Hint" button in `ash` reveals the level 1 hint text.
  - Main quest pinned to top with a subtle `hollow-faint` left border accent
- **Completed quests section** (bottom, collapsed by default):
  - Section header: "COMPLETED" in IBM Plex Mono 400, 9px, `ash`, uppercase
  - Tap to expand. Completed quests listed with names in `slate`, completion date in `caption` style
- Data source: `character-store.quests` (active) and a `completed_quests` array

*Map Panel*
- **Node-based map** rendered with `react-native-svg` or `@shopify/react-native-skia`:
  - Each location is a node. Connections between locations drawn as lines.
  - **Current location**: `hollow` filled circle (12px radius) with `glow-hollow` shadow, pulsing subtly
  - **Visited locations**: `bone` stroke circle (10px radius) with `charcoal` fill. Location name label in IBM Plex Mono 300, 9px, `ash`
  - **Known but unvisited**: `slate` dashed-stroke circle (8px radius). No label until visited.
  - **Undiscovered**: not rendered — fog of war by omission. Map grows as the player explores.
  - **Connections**: `charcoal` lines between connected locations. The most recently traveled path highlighted in `hollow-muted`.
  - **Quest objective marker**: small `hollow` diamond icon on the location where the current quest objective is located
  - **Region labels**: larger text in Cormorant Garamond 300, 14px, `ash` at 0.5 opacity, positioned near clusters of locations. "THE GREYVALE", "ACCORD OF TIDES"
- **Interactions**: pinch to zoom (0.5x to 3x), drag to pan. Double-tap to re-center on current location. Tap a visited location node to see its name and a one-line description in a tooltip (Crimson Pro 300, 12px, `bone` on `ink` surface).
- **Legend** (small, bottom-left): minimal — current location dot, visited dot, quest marker. IBM Plex Mono 300, 8px, `ash`.
- **Map state**: stored in `character-store.map_progress` — array of `{ location_id, visited: bool, connections: [] }`. Updated by `location_changed` events (newly visited locations added).
- **Performance**: map is pre-laid-out (node positions defined in location entity data or a separate map layout config). Rendering is static SVG/Skia with only the pulse animation on current location. Should render in <100ms even with 30+ nodes.

**Acceptance criteria:**
- [x] Panel shell opens via swipe-up gesture or persistent bar icon tap with spring animation
- [x] Panels open in <200ms with no loading spinner (reads from local stores)
- [x] Tab bar allows switching between all four panels without closing the sheet
- [x] Voice connection remains active while any panel is open — player can talk to DM while browsing
- [x] Swipe-down gesture and close button both dismiss panels smoothly
- [x] Character Sheet displays all stats, HP, skills, divine favor, and equipment correctly from store data
- [x] Character Sheet stat modifiers show correct color: `hollow` for positive, `ember` for negative
- [x] Inventory grid displays items with correct rarity borders; tapping opens detail card
- [x] Inventory item detail card shows full description, stats, and lore text
- [x] Quest Log shows active quests with expandable stages; completed stages have checkmarks
- [x] Quest Log hint button reveals level 1 hint text from `global_hints`
- [x] Map renders visited locations as nodes with connections; current location pulses in `hollow`
- [x] Map supports pinch-to-zoom and drag-to-pan; double-tap re-centers on current location
- [x] Map fills in as player explores — newly visited locations appear on `location_changed` events
- [x] Quest objective marker appears on the correct map node
- [x] All panel text uses brand typography: Cormorant Garamond for headers, Crimson Pro for body, IBM Plex Mono for data
- [x] Panel open/close triggers UI sounds (UI-006/UI-007) and light haptic
- [x] Panel components have unit or interaction tests covering data display and tab switching

**Key references:**
- *Technical Architecture — Client Architecture — Screen Map* (pull-up screens: Map, Character Sheet, Inventory, Quest Log)
- *Technical Architecture — Client Architecture — Performance Targets* (pull-up open <200ms, reads from local cache)
- *Game Design — Game Mechanics* (skill list, stat structure for Character Sheet content)
- *Game Design — Navigation* (map design, breadcrumb trail, points of interest)
- *Brand Spec — UI Patterns* (surface hierarchy, text roles) and *Design Tokens* (all typography and color specs)

---

### Milestone 5.4 — Audio Engine and Environmental Soundscapes

**Goal:** The client plays layered ambient audio that changes with location, time, and game state. Four independent audio channels (Voice, Ambience, Effects, UI) mix cleanly with automatic voice ducking. The audio engine is the foundation for immersion — when the player enters the world, they hear where they are before the DM says a word.

**Inputs:** Milestone 5.1 (session screen, data channel router), Milestone 3.3 (location changes push to client), audio assets generated.

**Deliverables:**

*Audio Session Configuration*
- iOS: `AVAudioSession` configured for `.playAndRecord` category with `.mixWithOthers` and `.duckOthers` options. This allows LiveKit WebRTC audio (Voice channel) to coexist with local playback (Ambience, Effects, UI). Must be set before LiveKit room connection.
- Android: `AudioManager` focus strategy configured to allow concurrent streams. `AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK` for voice, standard playback for local channels.
- This is the highest-risk client-side integration point — if WebRTC + local playback don't coexist cleanly, nothing else in the audio stack works. Validate early.

*Four-Channel Mixer Architecture*
- **Voice channel**: LiveKit WebRTC audio track. Not controlled by the mixer — controlled by LiveKit SDK. The mixer monitors it (detects when DM is speaking) to trigger ducking on other channels.
- **Ambience channel**: looping environmental soundscapes. Managed by `soundscape-player` module. Supports two simultaneous streams for crossfading (outgoing + incoming during transitions).
- **Effects channel**: one-shot sound effects triggered by `sound_effect` data channel events. Managed by `sfx-player`. Supports overlapping playback (multiple effects at once). Fire-and-forget.
- **UI Audio channel**: one-shot sounds triggered by client-side events (overlay appearance, user actions). Same `sfx-player` module, different volume bus.
- Each channel has an independent volume level (0.0–1.0) controlled by the corresponding slider in Settings. Master volume multiplier applies to all channels.
- Volume levels persisted to MMKV via `volume.ts`, loaded on app start.

*Voice Ducking*
- When LiveKit audio track is active (DM speaking, NPC dialogue, companion speech): Ambience ducks to 40% of its set volume. Music (future, Milestone 8.1) will duck to 30%.
- Ducking envelope: 50ms attack (fade down quickly when voice starts), 200ms release (fade back up smoothly when voice stops).
- Detection method: monitor LiveKit audio track activity via the SDK's `TrackEvent` or audio level callbacks. When voice audio level exceeds a threshold → duck. When it drops below for >150ms → release.
- Effects and UI Audio do NOT duck — they're brief and informational, designed to layer with voice.

*Environmental Soundscape Player*
- Subscribes to `location_changed` events from `session-store`
- Each location entity's `ambient_sounds` field maps to a local audio file: `market_bustle.mp3`, `rural_town_uneasy.mp3`, `dungeon_ancient_hum.mp3`, `hollow_wrongness.mp3`, etc.
- On location change: start new soundscape at 0% volume, linear crossfade over 2-3 seconds (incoming fades up, outgoing fades down), then release the old audio resource.
- Soundscapes are loopable audio files (seamless loop points authored into the asset). File format: MP3 or AAC, 44.1kHz, stereo, 128-192kbps.
- Time-of-day variants: some locations have alternate soundscapes (e.g., `market_bustle.mp3` for day, `harbor_quiet.mp3` for night). The `location_changed` event includes the active `ambient_sounds` tag based on current world time. The client plays whatever tag the server sends.
- On session start: load and play the soundscape for the player's current location immediately after LiveKit connection establishes.
- On session end: fade out soundscape over 1 second.

*Randomized Texture Layer*
- On top of the base soundscape, intermittent one-shot sounds fire at randomized intervals to add organic life.
- Each location can define a `texture_sounds` array: `[ { sound: "bird_call_01", min_interval: 15, max_interval: 45 }, { sound: "cart_wheel", min_interval: 30, max_interval: 90 } ]`
- A lightweight scheduler picks random intervals within the range and plays the texture sound through the Effects channel at 60-80% volume (softer than explicit sound effects).
- Texture sounds change with location (forest gets bird calls, market gets cart wheels, ruins get dripping water).
- The scheduler pauses during combat (combat has its own audio layer) and resumes after.

*Sound Effect Player*
- Handles `sound_effect` data channel events: `{ type: "sound_effect", effect_name, intensity? }`
- Looks up `effect_name` in `sound-registry.ts` to find the local file path
- Plays immediately through the Effects channel. Multiple effects can overlap (e.g., sword clash + enemy grunt).
- Optional `intensity` parameter (0.0–1.0) scales the playback volume relative to the Effects channel level. Default: 1.0.
- File format: MP3 or AAC, 44.1kHz, mono or stereo, short duration (<5 seconds).

*Audio Asset Bundle*
- Bundled with the app (or downloaded on first launch to reduce app binary size):
  - **Environmental soundscapes** (minimum 7 for MVP locations):
    - `market_bustle.mp3` — Market Square day: crowd chatter, cart wheels, harbor bells, gulls
    - `harbor_quiet.mp3` — Market Square night: distant waves, wind, lantern creak
    - `rural_town_uneasy.mp3` — Millhaven: wind through barley, mill wheel, distant dogs, underlying tension
    - `forest_road.mp3` — Greyvale wilderness: birdsong, stream, wind in trees, footsteps on dirt
    - `dungeon_ancient_hum.mp3` — Greyvale Ruins: dripping water, stone echoes, subliminal hum, metallic taste in the air
    - `hollow_wrongness.mp3` — Hollow Breach: absence of natural sound, alien frequencies, pressure, sensory inversion
    - `tavern_warm.mp3` — Hearthstone Tavern: fireplace, clinking mugs, low music, laughter, warmth
  - **Texture sounds** (minimum 10): bird calls (2-3 variants), cart wheel, water drip, footstep on stone, wind gust, dog bark (distant), insect buzz, branch crack, fire crackle
  - **Core sound effects** (from existing `sound-registry.ts` + gaps): sword clash (CMB-001), spell cast, arrow loose, hit taken, critical hit sting, shield block, potion use, door open/creak, ambient discovery chime
  - **UI sounds**: already handled in Milestone 5.2's `sfx-player` — dice rolls, stingers, and menu sounds. This milestone ensures the Effects and UI channels are properly separated in the mixer.
- Total estimated asset size: 15-25 MB for MVP (soundscapes ~2-3 MB each, effects <500KB each)

*Audio Settings UI (in Settings screen from 5.1)*
- 5 labeled sliders: Voice, Music, Ambience, Effects, UI
- Each slider: `charcoal` track, `hollow` fill, `parchment` thumb. Label in IBM Plex Mono 400, 10px, `ash`, uppercase.
- "Music" slider exists but has no effect until Milestone 8.1 (adaptive music). Shows as present but `slate` colored with "(Coming Soon)" label.
- Master volume: system-level, not in-app. Noted in settings with text: "Use device volume for master level."
- Preview: tapping a slider label plays a 1-second sample of that channel type so the player can hear the effect of their adjustment.
- Values persist to MMKV. Loaded into the mixer on app start.

**Acceptance criteria:**
- [x] iOS audio session configured for `.playAndRecord` + `.mixWithOthers` — LiveKit voice and local playback coexist without cutting each other off
- [ ] Android AudioManager allows concurrent WebRTC + local audio streams
- [x] Entering the world plays the ambient soundscape for the player's current location within 1 second of voice connection
- [x] Moving to a new location crossfades to the new soundscape over 2-3 seconds (no hard cut, no silence gap)
- [x] When the DM speaks, ambient audio audibly ducks to ~40% and returns smoothly when speech ends (50ms attack, 200ms release)
- [x] Ducking does not affect Effects or UI audio channels
- [x] `play_sound` data messages trigger the correct sound effect on the client with < 100ms latency
- [x] Multiple sound effects can play simultaneously without cutting each other off
- [x] Randomized texture sounds (bird calls, drips, etc.) play at varied intervals without noticeable pattern
- [x] Texture sounds pause during combat and resume after
- [x] Volume sliders work and persist between sessions
- [x] Each volume slider independently controls its channel (moving Ambience doesn't affect Effects)
- [x] Tapping a slider label plays a preview sample of that channel
- [x] All 7 environmental soundscapes are present, loop seamlessly, and sound distinct
- [ ] Hollow Breach soundscape feels fundamentally different from natural environments — wrong, alien, unsettling
- [ ] The audio mix is clear at all times — DM voice is always understandable over ambience and effects
- [x] Session end fades out soundscape over 1 second (no hard cut)
- [x] Audio engine memory footprint stays reasonable — only the active soundscape + crossfade target loaded simultaneously, not all 7
- [x] Audio integration tests verify: channel independence, ducking trigger/release, crossfade timing, volume persistence

**Key references:**
- *Technical Architecture — Client Architecture — Audio Mixing Architecture* (four channels, ducking rules, iOS/Android audio session config, ambient sound library, sound effect library)
- *Audio Design — The Audio Stack* (7-layer hierarchy, mixing rules, ducking specs)
- *Audio Design — Environmental Soundscapes* (layered structure: foundation + detail + motion + seasonal, corruption audio behavior)
- *Audio Design — Sound of the Hollow* (Hollow breaks audio rules: reversed sounds, impossible frequencies, absence as presence)
- *Audio Design — AI Generation Prompts* (prompts for generating each soundscape and effect category)
- *Audio Design — MVP Asset Inventory* (ENV-001 through ENV-008, CMB-001 through CMB-022, UI-001 through UI-010)

---

## Phase 6: The World Experience

### Milestone 6.1 — Navigation and World Traversal

**Goal:** Players can move through the world by speaking, with the DM narrating transitions and scene-setting.

**Inputs:** Milestone 3.3 (move_player tool works), Milestone 5.4 (audio engine and soundscapes).

**Deliverables:**
- Voice-driven navigation: player says "I go to the market" or "let's head to Millhaven" → DM interprets intent → calls `move_player` → narrates the transition → client receives location_changed → soundscape crossfades → HUD updates
- Scene narration on arrival: DM reads location description (from entity data, condition-modified) as an atmospheric audio-first scene
- Exit awareness: DM knows available exits and can describe them when asked ("You could head north toward Millhaven or south back to the market")
- Travel narration: movement between distant locations includes brief travel narration (road description, companion commentary) rather than instant teleportation
- Hidden element discovery: DM can reveal hidden elements in locations when player investigates (skill check required for some)

**Acceptance criteria:**
- [x] Player can navigate the full MVP map by voice: Market Square ↔ Road ↔ Millhaven ↔ Greyvale Ruins Entrance ↔ Ruins Interior ↔ Hollow Breach
- [x] Each location has a unique scene narration that matches the audio design (leads with sound, then feeling)
- [x] Moving between locations triggers soundscape crossfade and HUD location update
- [x] DM describes available exits when the player asks "where can I go?"
- [x] Travel between distant locations (Market Square → Millhaven) includes a brief journey narration
- [x] Hidden elements can be discovered through investigation ("I examine the wall" → skill check → hidden passage revealed)
- [x] Condition overlays work: visiting Market Square at night produces a different description than during the day

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
- [x] Companion speaks proactively during exploration (environmental comments, idle observations) without being prompted
- [x] Companion has a distinctly different voice from the DM and all NPCs
- [x] When the player is stuck, the companion offers hints after appropriate delay (level 2 guidance)
- [x] Companion participates in combat with their own actions and tactical commentary
- [x] Companion can be knocked unconscious in combat (the silence where their voice was is noticeable)
- [x] The Kael meeting scene plays out naturally in session 1 and feels organic, not scripted
- [x] Companion remembers previous interactions within the same session (references earlier events)
- [x] Companion reacts emotionally to player decisions (pleased, concerned, annoyed — appropriate to Kael's personality)

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
- [x] A playtester can complete sessions 1-4 in sequence with a coherent narrative
- [x] Each NPC interaction feels like talking to a distinct character (voice, personality, knowledge appropriate to disposition)
- [x] The Greyvale Ruins feel progressively more unsettling as the player goes deeper (Hollow audio stages 1→3)
- [x] The artifact discovery is a meaningful narrative moment (companion reacts, DM narrates weight of the discovery)
- [x] Session 4's faction reactions differ based on which faction the player aligns with
- [x] Quest stages advance correctly based on completion conditions
- [x] At least one combat encounter and one non-combat challenge (social/puzzle) occur across the 4 sessions
- [x] The story ends with clear hooks for continued play (the mystery isn't resolved, the world is larger than the Greyvale)
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
- [x] Player starts a crafting activity via REST → activity appears in database with status "in_progress"
- [x] After the timer expires, the background worker resolves the activity and generates a narrated outcome
- [x] Narration audio is generated and stored (verify audio file exists at the URL)
- [x] Outcome narration is in-character, concise (15-30 seconds), and ends with a decision point
- [x] Companion errand returns with narrative information relevant to the errand type
- [x] Soft timer ranges work: 10 activities set for "4-8 hours" resolve at varied times within that window
- [x] Multiple concurrent activities can run simultaneously for one player (3-4 at once)
- [x] Activity resolution cost is < $0.005 per activity (LLM + TTS)

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
- [x] Opening the app shows resolved activities with playable narrated audio
- [x] Tapping a decision button resolves the activity and triggers the appropriate next step
- [x] World news summary plays automatically if significant changes occurred (skipped if nothing changed)
- [x] When nothing is pending, companion idle chatter or world micro-observations appear
- [x] Push notifications arrive for resolved activities with narrative text (not "timer complete")
- [x] Player can start new activities from the launcher with parameter choices
- [x] In-flight activities show progress text (intermediate narrative state)
- [x] The entire check-in flow completes in under 5 minutes
- [x] The Catch-Up layer works silently — all functionality accessible via tap without any audio playback

**Key references:**
- *Game Design — The Catch-Up Layer (Home Screen Integration)* (silent-first design, feed organization)
- *Game Design — The Five-Minute Check-In* (the full check-in flow)
- *Game Design — The Frequent Checker* (companion idle, micro-observations, activity density)
- *Game Design — Silent Layer, Voiced Layer* (context-aware play)

---

## Phase 8: Polish and Integration

### Milestone 8.1 — Adaptive Music System

**Goal:** Music responds to game state — exploration, tension, combat, wonder, the Hollow — fading in and out appropriately.

**Inputs:** Milestone 5.4 (audio engine), audio assets generated (music stems).

**Deliverables:**
- Music state machine: silence → exploration → tension → combat → wonder → sorrow → hollow (transitions triggered by game state events)
- Stem-based playback: each music state has layered stems that can be mixed independently
- Crossfading between states: smooth 3-5 second transitions between music states
- Voice ducking on music: music ducks 50-70% when DM or companion speaks
- Hollow music dissolution: in corrupted areas, music degrades progressively (pitch drift, tempo instability, melody fragmentation)
- Combat music intensity scaling: lighter music for minor encounters, full intensity for boss fights

**Acceptance criteria:**
- [x] Entering a calm exploration area fades in exploration music after a natural delay
- [x] Approaching a Hollow-corrupted area transitions music to tension state
- [x] Combat starting triggers combat music with an audible shift in energy
- [x] Music ducks appropriately when the DM speaks — dialogue is always clear over music
- [x] Hollow corruption degrades music audibly (pitch drift, rhythm instability)
- [x] Music transitions are smooth, never jarring — crossfades feel natural
- [x] Wonder stinger plays at key narrative revelation moments
- [x] Silence is used deliberately — not every moment has music

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
- [x] Prologue plays and sets the world's tone before creation begins
- [x] Player can create a full character through voice conversation (no text input required)
- [x] Visual cards appear at appropriate moments showing available choices
- [x] DM responds naturally to unusual or creative player inputs during creation
- [ ] Character creation takes 10-15 minutes (not rushed, not dragging)
- [x] Created character has appropriate starting stats, equipment, and skills for their chosen class/patron
- [x] Character persists and is loaded correctly on next session

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
- [x] Starting a new session loads the player's persistent state (location, inventory, quest progress, companion relationship)
- [x] DM opens with a natural recap of the previous session based on the stored summary
- [x] Disconnecting and reconnecting within 2 minutes resumes the session seamlessly
- [x] Disconnecting for > 2 minutes ends the session and persists all state
- [x] Player saying "I need to go" or "let's wrap up" triggers a narrative session ending
- [x] Session summary is generated and stored (verify it contains key events and decisions)
- [x] Next session's recap accurately reflects what happened in the previous session
- [x] A simulated LLM error mid-session doesn't crash the agent (verify graceful fallback)

**Key references:**
- *Technical Architecture — Session Lifecycle* (room creation → state loading → gameplay → teardown)
- *Technical Architecture — Session Persistence and Recovery* (reconnection, summary compression)
- *Game Design — Session Structure — Session Flow* (Gathering through Hearth)

---

### Milestone 8.4 — God Whisper System

**Goal:** The patron deity reaches out to the player through atmospheric voiced messages.

**Inputs:** Milestone 7.1 (async narration pipeline), Milestone 5.4 (audio engine).

**Deliverables:**
- Divine favor tracking: accumulates based on player actions aligned with patron deity's domain
- God whisper trigger: when divine favor crosses a threshold, or at story-critical moments, a whisper is generated
- God voice synthesis: each patron deity has a distinct `voice_id` and audio treatment (see audio design doc)
- Audio treatment layer: god whispers have environmental audio processing (Kaelen = reverb/stone hall, Syrath = close/intimate/stereo shift, Veythar = harmonic shimmer)
- Async delivery: god whispers appear as pending decisions in the Catch-Up layer with pre-rendered audio
- Sync delivery: god whispers can also occur during active sessions at dramatic moments (DM triggers the whisper)
- God whisper stinger: the STG-006 audio cue plays before the god speaks

**Acceptance criteria:**
- [x] Accumulating divine favor through aligned actions triggers a god whisper
- [x] The god's voice sounds distinctly different from the DM and all NPCs (unique voice_id + audio treatment)
- [x] The whisper content is atmospheric and cryptic — guidance without explicit instruction
- [x] The god whisper stinger plays before the god speaks, creating an "other-worldly" audio transition
- [x] God whispers in async appear in the Catch-Up layer with playable audio
- [x] God whispers in sync sessions are triggered at appropriate dramatic moments
- [x] At least 3 patron deities are supported for MVP (Kaelen, Syrath, Veythar) with distinct voices

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

## Phase 10: Visual Art Integration

*This phase brings the ink wash art direction to life across the app. The image_prompt_library.md defines the visual language — dissolving edges, monochrome ink on dark paper, selective color accents. This phase builds the pipeline to generate art with Gemini, integrates it into existing UI surfaces (replacing placeholders), and adds new visual moments that complement the audio-first experience. Art supplements the DM's voice — it never replaces it. Every image is atmospheric, partially unfinished, and feels like it belongs in the world.*

### Milestone 10.1 — Image Generation Pipeline and Asset Management

**Goal:** Build the server-side infrastructure to generate images from the prompt library using Gemini, store them, and serve them efficiently to the client. This is the foundation that all subsequent art milestones build on.

**Inputs:** Milestone 1.1 (server infrastructure), Milestone 5.1 (client app with data channel).

**Deliverables:**
- Image generation service (`apps/server/src/services/image-gen.ts`): wrapper around the Gemini API (Nano Banana 2 / Gemini image generation) that accepts a prompt template key + variable substitutions and returns a generated image
- Prompt template registry: structured version of the prompts from `image_prompt_library.md` — each template has an ID, category, base prompt text, variable slots, aspect ratio, and accent color rule
- Asset storage: generated images stored in a persistent location (local filesystem for dev, cloud storage bucket for prod) with content-addressable naming (hash of prompt + variables)
- Asset serving: REST endpoint (`GET /api/assets/images/:id`) serves generated images with cache headers. CDN-friendly URLs.
- Client-side image caching: `expo-image` integration with disk caching — images download once and persist across sessions. Cache key is the asset ID.
- Generation queue: image generation requests are queued and processed asynchronously (not blocking voice/gameplay). Results pushed to client via data channel when ready: `{ type: "image_ready", asset_id, url, category, context }`
- Batch generation script (`scripts/generate_art.ts`): CLI tool that pre-generates a set of images from the prompt library for MVP content (run once to seed the art assets, regenerate as needed)
- Post-processing pipeline: after generation, images are auto-adjusted — background darkened to near-black (#0A0A0B), color-corrected to brand palette, cropped to target aspect ratio

**Acceptance criteria:**
- [x] `bun run scripts/generate_art.ts --template companion_portrait --vars '{"name":"Kael","class":"ranger"}'` generates an image and stores it
- [x] Generated images match the ink wash style described in `image_prompt_library.md` (manual review — dissolving edges, dark background, monochrome with selective accent)
- [x] Asset serving endpoint returns images with proper cache headers (24h cache, ETag)
- [ ] `expo-image` on the client loads and caches images from the asset endpoint
- [ ] Generation queue processes requests without blocking the voice pipeline (verify voice latency unchanged during generation)
- [x] Post-processing darkens backgrounds and corrects accent colors to within 10% of brand hex values
- [x] Batch generation script can produce all MVP companion + location + item art in a single run
- [x] Duplicate requests (same template + variables) return the cached asset instead of regenerating

**Key references:**
- *Image Prompt Library* (all templates, style foundation, consistency tips, aspect ratios)
- *Brand Spec — Art Direction* (ink wash style, accent color rules, art categories)
- *Cost Model* (monitor image generation costs per asset)

---

### Milestone 10.2 — Character Portraits and Creation Cards

**Goal:** Replace placeholder rectangles with real ink wash art. Character creation cards show race, class, and patron illustrations. Companion and NPC portraits appear during encounters and in the character sheet. The player's own character gets a generated portrait.

**Inputs:** Milestone 10.1 (image generation pipeline), Milestone 8.2 (character creation flow), Milestone 5.2 (creation card UI), Milestone 5.3 (character sheet panel).

**Deliverables:**

*Character Creation Art*
- Race illustration cards: one ink wash portrait per MVP race (Solari, Duskari, Elari, Tideborn, Ashfolk, Verdani) generated from the "Player Character — Creation Screen" template. 3:4 aspect ratio, monochrome, front-facing bust with race-defining features.
- Class illustration cards: one ink wash illustration per MVP class archetype showing the class in action — not a portrait, but a figure/scene that evokes the class fantasy. 3:4 aspect ratio.
- Patron deity cards: one illustration per MVP patron (Kaelen, Syrath, Veythar) using the "God Contact" template adapted — atmospheric, abstract, showing the deity's domain rather than a literal face. Divine gold accent for all.
- Creation card component update: replace `artPlaceholder` View in `creation-card-row.tsx` with `expo-image` loading pre-generated art by card ID. Fallback to slate placeholder if image hasn't loaded yet.

*Companion Portrait*
- Kael portrait: primary (neutral) and variant (alert/concerned) generated from the "Companion Portrait" templates. 3:4 aspect ratio.
- Companion portrait display: new `CompanionPortrait` component shown as a small (48px) circular avatar in the persistent bar when the companion speaks, with a brief fade-in/fade-out (matches ventriloquism voice timing).
- Character sheet integration: companion section shows Kael's portrait alongside relationship status.

*NPC Portraits*
- Tier 1 NPC portraits: Guildmaster Torin, Elder Yanna, Scholar Emris — generated from the "NPC Portrait — Brief Encounter" template. 1:1 aspect ratio, rough/impressionistic style.
- NPC portrait display: when the DM voices an NPC (ventriloquism tag detected), a small portrait fades in at the top of the screen for the duration of the NPC's dialogue. Subtle entrance (200ms fade), holds during speech, subtle exit (300ms fade). Non-intrusive — positioned near the voice state indicator.

*Player Character Portrait*
- Dynamic generation: after character creation completes, the server generates a portrait using the "Player Character — Creation Screen" template with the player's chosen race, class, and key features as variables.
- The portrait generates asynchronously — player doesn't wait for it. It appears on the home screen character summary and character sheet panel once ready.
- Regeneration option: settings screen includes "Regenerate Portrait" button that generates a new portrait with the same parameters (variation in output).

**Acceptance criteria:**
- [ ] Character creation cards display ink wash art instead of slate rectangles for all MVP races, classes, and patrons
- [ ] Art style is visually consistent across all creation cards (same ink wash treatment, same dark background, same dissolving edges)
- [ ] Kael's portrait appears as a small avatar when the companion speaks during sessions
- [ ] NPC portraits appear during NPC dialogue and fade away when the NPC stops speaking
- [ ] Player character portrait generates after creation and appears on the home screen within 30 seconds
- [ ] Portrait regeneration produces a visibly different (but stylistically consistent) result
- [ ] All portraits use the correct aspect ratios from the prompt library (3:4 for companions/player, 1:1 for NPCs)
- [ ] Images load gracefully — slate placeholder shown during load, cross-fade to image on ready
- [ ] No image display blocks or delays the voice pipeline or DM narration

**Key references:**
- *Image Prompt Library — Category 1: Character Portraits* (all portrait templates)
- *Image Prompt Library — Accent Color Rules* (when to use teal, ember, gold)
- *Brand Spec — Art Direction — Character Art* (companion: most finished, NPC: impressionistic)
- *Game Design — Character Creation* (creation flow steps)

---

### Milestone 10.3 — Location Art and Atmospheric Visuals

**Goal:** Location illustrations replace the pure-gradient atmospheric backgrounds during sessions. The session screen gets a layered visual treatment: ink wash location art as a base, grain overlay on top, HUD elements floating above. Loading screens use abstract ink compositions. The Hollow gets special visual corruption treatment.

**Inputs:** Milestone 10.1 (image generation pipeline), Milestone 5.1 (session screen with atmospheric background), Milestone 5.4 (audio engine with location changes).

**Deliverables:**

*Location Illustrations*
- One 16:9 ink wash illustration per MVP location: Market Square (ember accent from lanterns), Millhaven (no color — monochrome unease), Forest Road (no color — monochrome ancient quiet), Greyvale Ruins Entrance (faint teal wash beginning), Ruins Interior (teal corruption spreading), Hollow Breach (heavy teal — art style itself corrupting), Hearthstone Tavern (warm ember from fireplace).
- Night variants for locations with time-of-day differences: Market Square at night (no ember, deeper shadows), Millhaven at night.
- Atmospheric background upgrade: `atmospheric-background.tsx` enhanced to layer the location illustration beneath the existing gradient. The gradient becomes a semi-transparent overlay (30-50% opacity) that tints the art to match game state, rather than being the sole visual. Art is displayed at low brightness (40-60% of full) so it never competes with HUD elements.
- Location transition: when the player moves, the new location illustration cross-fades in over 2-3 seconds (synced with the audio soundscape crossfade). The old illustration fades out simultaneously.

*Hollow Visual Corruption*
- Progressive corruption: as the player moves deeper into Hollow-influenced areas, the location art itself degrades visually. This mirrors the audio corruption stages.
  - Stage 1 (Ruins Entrance): art is normal ink wash with subtle teal stain at edges
  - Stage 2 (Ruins Interior): teal bleeds more prominently, image has slight distortion (CSS/shader-based — subtle hue shift, noise overlay increase)
  - Stage 3 (Hollow Breach): heavy teal saturation, grain overlay intensity increases to 8-10%, subtle animated noise/static effect overlaid on the art. The screen itself feels corrupted.
- Corruption effects are applied as client-side post-processing overlays on top of the base art (not baked into the generated image) — this allows smooth transitions between corruption stages.

*Loading and Transition Screens*
- App launch: abstract ink composition (from "Loading Screen — Abstract" template) displayed during app initialization, fading into the home screen.
- Session connecting: while waiting for LiveKit room connection, display an abstract atmospheric ink wash that cross-fades into the location art once the session initializes.
- Session summary: location illustration from the session's final location displayed as a dimmed background behind the summary text.

*Static Asset Bundling*
- Bundle pre-generated MVP art assets directly into the Expo app (via `apps/mobile/assets/images/`) so they load instantly without network round-trips. This includes: loading screen abstract, all MVP location illustrations, companion portraits, NPC portraits, and item art.
- Server-served images (`/api/assets/images/:id`) remain available for dynamically generated art (player portraits, new content created during gameplay).
- Use `expo-asset` for bundled images, `expo-image` with URL caching for server-served images. Bundled assets take priority — only fall back to server if the asset isn't in the bundle.

*Home Screen Enhancement*
- Session history entries: small thumbnail of the session's primary location art (48px square, rounded corners) next to each session in the history list.

**Acceptance criteria:**
- [ ] Each MVP location displays its ink wash illustration as the session background (visible through semi-transparent gradient)
- [ ] Location art is atmospheric and non-distracting — HUD text and overlays remain clearly readable over the art
- [ ] Location transitions cross-fade art and audio simultaneously — the visual and audio shifts feel unified
- [ ] Night variants display for locations when the world clock indicates nighttime
- [ ] Hollow corruption stages 1-3 produce progressively more unsettling visual effects (teal bleed, distortion, noise)
- [ ] Corruption visual effects transition smoothly as the player moves between corruption stages (no hard cuts)
- [ ] App launch shows an ink wash loading screen that fades into the home screen
- [ ] Session connecting state shows atmospheric art that transitions to location art on session init
- [ ] Session summary screen displays final location art as a dimmed background
- [ ] Session history entries on home screen show location art thumbnails
- [ ] All location art matches the ink wash style (dark background, dissolving edges, correct accent colors per location)
- [ ] Static MVP art assets are bundled in the app binary — loading screen, locations, portraits, and items display without network requests
- [ ] Dynamically generated art (player portraits) loads from the server endpoint and caches locally after first fetch
- [ ] Art display does not impact session performance — images are pre-cached, transitions run at 60fps

**Key references:**
- *Image Prompt Library — Category 2: Location Illustrations* (all location templates)
- *Image Prompt Library — Accent Color Rules* (ember for firelight/forge, teal for Hollow, no color for natural spaces)
- *Audio Design — The Sound of the Hollow* (5-stage escalation — visual corruption mirrors audio corruption)
- *Brand Spec — Art Direction — Location Art* (wide, atmospheric, center defined, edges fade)

---

### Milestone 10.4 — Item Art, Story Moments, and Marketing Assets

**Goal:** Complete the visual layer. Inventory items get ink wash specimen-plate illustrations. Key narrative moments get dramatic story illustrations shown during session recaps. Marketing assets are generated for app store presence.

**Inputs:** Milestone 10.1 (image generation pipeline), Milestone 5.3 (inventory panel), Milestone 5.1 (session summary screen).

**Deliverables:**

*Item Art*
- Item illustrations for all MVP items: Sealed Research Tablet (quest item template — monochrome), Hollow-Bone Fragment (corrupted artifact template — teal accent), plus key weapons and armor the player can acquire during the Greyvale arc.
- Inventory panel upgrade: item tiles in the grid display their ink wash illustration instead of the generic type icon on slate background. 1:1 aspect ratio, centered on dark background with generous negative space.
- Item detail card: the full item card (shown on tap) displays a larger version of the item illustration above the description text.
- Item acquisition popup: the `item_acquired` overlay (from Milestone 5.2) displays the item illustration in the card, replacing the rarity-colored placeholder area.
- Corrupted items: items with Hollow corruption show the teal-bleeding-beyond-lines treatment from the "Corrupted Artifact" template. The illustration itself communicates danger before the DM describes it.

*Story Moment Illustrations*
- Key narrative beat illustrations for the Greyvale arc's major moments: first combat encounter, Hollow Breach discovery, artifact recovery, god contact moment (if triggered).
- Story moment display: during session recap (session summary screen), 1-2 story illustrations are shown alongside the recap text. Each illustration corresponds to a key event from that session.
- The DM agent tags significant narrative moments during play: `{ type: "story_moment", moment_key, description }`. The server uses the moment key to select or generate the appropriate illustration.
- Story moments use the 2:3 portrait aspect ratio — dramatic, graphic-novel-panel feeling.

*Marketing and App Store Assets*
- App icon treatment: ink wash version of the app icon generated from the brand's visual language.
- App store screenshot backgrounds: 4-5 atmospheric ink wash compositions (from "App Store Screenshot Background" template) suitable as backgrounds behind overlaid UI screenshots. 9:16 aspect ratio.
- Social media teaser: the "eye" composition from the prompt library — a single detailed eye with teal reflection, the rest dissolving into ink marks. 1:1 for social sharing.
- These are generated once via the batch script and stored as static marketing assets — not served through the dynamic pipeline.

**Acceptance criteria:**
- [ ] MVP items display ink wash specimen-plate illustrations in the inventory grid (no more generic type icons)
- [ ] Tapping an item shows its illustration in the detail card at a larger size
- [ ] Item acquisition popup displays the item's illustration
- [ ] Corrupted items (Hollow-Bone Fragment) visually show teal bleed — communicating corruption through art alone
- [ ] Session summary screen displays 1-2 story moment illustrations that correspond to actual events from that session
- [ ] Story moment illustrations match the dramatic ink wash style (2:3, bold brushwork, accent color appropriate to scene)
- [ ] App store screenshot backgrounds are generated and ready for use (5 variants, 9:16, atmospheric)
- [ ] Social media teaser image is generated (1:1, the eye composition)
- [ ] All item art uses the 1:1 specimen-plate style consistently (centered, negative space, naturalist quality)
- [ ] Art generation for story moments doesn't delay session summary — illustrations are generated during the session and cached

**Key references:**
- *Image Prompt Library — Category 3: Item & Object Art* (weapon, corrupted artifact, quest item templates)
- *Image Prompt Library — Category 4: Story Moment Illustrations* (combat, god contact, Hollow encounter templates)
- *Image Prompt Library — Category 5: UI & Marketing Assets* (screenshot backgrounds, social teaser, loading screen)
- *Image Prompt Library — Production Pipeline Notes* (batch consistency, post-processing, asset priority)

---

## Phase 11: Multiplayer (Wave 2 Prep)

*This phase is post-MVP solo validation. It should only begin after Wave 1 solo playtests (Milestone 9.1) confirm the core experience works. Multiplayer adds complexity that is not worth building until the single-player DM, combat, companion, and session lifecycle are proven.*

### Milestone 11.1 — Multiplayer Room

**Goal:** Two human players and the DM agent share a voice room and play together.

**Inputs:** Milestone 9.1 (solo experience validated), Milestone 4.1 (combat works for solo), Milestone 2.4 (ventriloquism working).

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
- *MVP Spec — Wave 2 Group Playtests* (multiplayer test protocol)

---

### Milestone 11.2 — Multiplayer Conversation Awareness

**Goal:** The DM knows when players are talking to each other vs. talking to the game, and stays quiet during player-to-player conversation instead of trying to respond to every utterance.

**The problem:** In solo play, every player utterance is directed at the DM. The pipeline fires on end-of-speech and generates a response. In multiplayer, players talk to each other constantly — strategizing, joking, debating what to do. If the DM responds to every utterance, it becomes an intrusive third wheel that interrupts natural player interaction. A great human DM reads the room and knows when to stay quiet. Our DM needs the same awareness.

**Inputs:** Milestone 11.1 (multiplayer room working).

**Approach — LLM judgment via system prompt and context:**

The DM's system prompt includes explicit guidance for multiplayer conversation awareness:

```
## Multiplayer Awareness

In multiplayer sessions, players will talk to each other as well as to you.
Your job is to recognize the difference and respond accordingly:

STAY QUIET when:
- Players are strategizing with each other ("should we go left or right?")
- Players are having side conversation or joking around
- A player responds to something another player said, not to your narration
- Players are debating a decision — let them reach consensus

SPEAK when:
- A player addresses you directly or addresses the game world ("I open the door")
- Players reach a decision and are waiting for you ("okay, let's do it")
- An uncomfortable silence suggests players are waiting for you to continue
- A game event demands your narration (combat phase advances, timer fires)
- You can add a brief, natural companion interjection that enhances the moment
  without interrupting (use sparingly)

When players finish conferring, you have heard everything they discussed.
Reference their discussion naturally: "So you're going with the left passage —
good. As you turn the corner..." Don't repeat their conversation back to them.
Don't summarize what they decided. Just act on it.

If you're unsure whether players are done talking to each other, wait.
Silence is better than interruption. A player will address you when they're ready.
```

The `on_user_turn_completed` hook adds multiplayer context to help the LLM decide:

```python
async def on_user_turn_completed(self, turn_ctx, new_message):
    if self._is_multiplayer:
        # Include recent speaker pattern so LLM can see conversation flow
        recent = self._speaker_tracker.get_recent_turns(5)
        # e.g. "Last 5 turns: Player_A → Player_B → Player_A → Player_B → Player_A"
        # (rapid alternation between humans = they're talking to each other)
        turn_ctx.add_message(
            role="assistant",
            content=format_speaker_context(recent, new_message.speaker_id)
        )
    
    # ... existing hot layer injections ...
```

The LLM sees the speaker pattern and the transcript content together. If the last 3 turns are rapid human-to-human exchanges about strategy, and the latest utterance is "yeah I agree," Claude will recognize this as player conferral and either stay quiet or respond minimally. If the next utterance is "I attack the goblin," it recognizes the pivot to game-directed speech and narrates.

**Why LLM judgment first, not heuristics:** Player-to-player and player-to-DM speech blend together fluidly in real tabletop play. Hard rules (like "if two humans spoke within 3 seconds, suppress") will misfire constantly. The LLM can read conversational intent from context in ways a state machine can't. The cost is some tokens spent on "decide to stay quiet" turns, but this is acceptable at multiplayer scale.

**Future optimization (post Wave 2):** If token cost on quiet turns becomes significant, add a lightweight pre-filter in `on_user_turn_completed` that uses `StopResponse` to suppress LLM calls entirely when speaker pattern strongly indicates player-to-player conversation (e.g., 4+ rapid human-to-human turns with no DM address cues). This saves tokens but risks over-suppression, so it should only be tuned against real Wave 2 playtest data.

**Deliverables:**
- DM system prompt additions for multiplayer conversation awareness (the guidance above)
- Speaker tracking in `on_user_turn_completed`: recent speaker pattern injected as context
- Speaker identity labels: each utterance tagged with player name so the LLM sees who said what
- Quiet turn handling: when the LLM decides not to speak, the response is suppressed cleanly (no awkward silence acknowledgment, no "...")
- Companion interjection rules: companions can occasionally react to player-to-player conversation naturally ("Kael chuckles at your plan") but sparingly — max once per conferral period

**Acceptance criteria:**
- [ ] When two players discuss strategy for 30+ seconds, the DM stays quiet throughout
- [ ] When a player pivots from player-to-player conversation to a game action ("okay I open the door"), the DM responds naturally within normal latency
- [ ] The DM references player discussion when it does respond ("So you're going with the stealth approach...")
- [ ] The DM never interrupts mid-sentence of a player-to-player exchange
- [ ] The DM doesn't generate a "..." or empty response during quiet periods — it simply doesn't speak
- [ ] In combat, the DM correctly intervenes when it's a player's turn even if players are chatting ("Kira — it's your turn. What do you do?")
- [ ] Companions occasionally react to player conversation in a way that feels natural, not intrusive
- [ ] Playtesters report the DM "knows when to shut up" (qualitative, Wave 2 survey)

**Key references:**
- *Technical Architecture — Multiplayer Architecture* (input buffer, speaker identity)
- *Game Design — The Companion in Multiplayer* (companion behavior during player interaction)
- *Player Resonance System* (future extension: per-player affect in multiplayer enables detecting which player is disengaged while others dominate conversation)

---

## Summary

| Phase | Milestones | Description |
|---|---|---|
| **1: Foundation** | 1.1, 1.2 | Project setup, database, content seeding |
| **2: Voice Pipeline** | 2.1, 2.2, 2.3, 2.4 | LiveKit, STT/TTS, DM conversation, ventriloquism |
| **3: Game Mechanics** | 3.1, 3.2, 3.3, 3.4 | World queries, dice/mechanics, state mutation, background process |
| **4: Combat** | 4.1 | Phase-based voice combat |
| **5: Client App** | 5.1, 5.2, 5.3, 5.4 | Home screen, reactive HUD, pull-up panels, audio engine |
| **6: World Experience** | 6.1, 6.2, 6.3 | Navigation, companion, Greyvale arc content |
| **7: Async** | 7.1, 7.2 | Activity engine, Catch-Up layer |
| **8: Polish** | 8.1, 8.2, 8.3, 8.4 | Music, character creation, session lifecycle, god whispers |
| **9: Validation** | 9.1 | Internal playtest — solo Wave 1 with quality rubrics |
| **10: Visual Art** | 10.1, 10.2, 10.3, 10.4 | Image pipeline, portraits, location art, items & story moments |
| **11: Multiplayer** | 11.1, 11.2 | Wave 2 prep — multi-player rooms, conversation awareness |

**Total: 11 phases, 25 milestones.** Phases 1–9 (19 milestones) deliver the complete solo MVP through Wave 1 playtesting. Phase 10 brings the ink wash visual art direction to life across the app. Phase 11 extends to multiplayer only after solo validation succeeds. Dependencies flow strictly downward — no milestone requires work from a later phase.

## Cross-Cutting: Accounts & Authentication

Added as a prerequisite for multiplayer and persistent player identity. Email + 6-digit verification code flow (no passwords). JWT-based session tokens (30-day expiry). New `accounts` and `auth_codes` DB tables; `players` table linked via `account_id`. Server routes gated with `requireAuth` middleware. Mobile auth screen with SecureStore token persistence. See `apps/server/src/auth.ts` and `apps/mobile/src/stores/auth-store.ts`.