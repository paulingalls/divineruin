# Divine Ruin: The Sundered Veil — MVP Specification

## About This Document

This document defines the **minimum viable product** for playtesting Divine Ruin: The Sundered Veil. It scopes the smallest slice of the full game design that can validate the core experience. The MVP is not the game — it's the proof that the game can work.

The full vision is documented in the *Game Design Document*. The world and narrative are in the *Aethos Lore Document*. The systems architecture is in the *Technical Architecture Document*. The content format and world simulation are in the *World Data & Simulation* document. Unit economics are validated in the *Cost Model*. This document answers: **what do we build first, and how do we know if it works?**

---

## What the MVP Must Prove

Six core questions the MVP needs to answer:

| # | Question | Why It Matters |
|---|---|---|
| 1 | **Does voice-first RPG gameplay work?** | Can players navigate, fight, and interact through conversation without frustration? |
| 2 | **Does the AI DM hold up?** | Can it manage pacing, narration, rules, and improvisation well enough to sustain immersion? |
| 3 | **Does combat feel good in audio?** | Does the phase-based system create tension and excitement without visual spectacle? |
| 4 | **Does the guidance system prevent players from getting stuck?** | Do escalating nudges and companion suggestions work in practice? |
| 5 | **Do players want to come back?** | After session 1, is there enough pull to return for session 2? |
| 6 | **Does the async loop engage?** | When players check in between sessions, does it feel meaningful? |

---

## MVP Scope Summary

**One starting culture.** Sunward Accord / Accord of Tides.
**One city.** The Accord of Tides (partial — one playable district).
**One wilderness zone.** The Greyvale (countryside north of the city).
**One story arc.** 3–5 sessions, self-contained but connected to the larger mystery.
**Subset of races.** 2–3 of the full 6.
**Subset of classes.** 4–5 of the full 16 archetypes.
**Subset of gods.** 3–4 of the full 10.
**Basic async.** 2–3 async activities to test the concept.
**Solo and small group.** 1 player + AI companion, scaling to 2–4 players in wave 2.

---

## MVP World

### The Accord of Tides — Playable District

Not the full city — a single district with enough locations to feel real and test core systems:

**Market Square**
- Navigation training (finding your way through a populated space)
- NPC interaction (vendors, passersby, quest-givers)
- Basic commerce (buying supplies, selling loot)
- Audio identity: bustling, multilingual, harbor sounds in the distance

**The Guild Hall**
- Quest hub (receive missions, report back)
- Party formation point (for multiplayer testing)
- Class trainers (basic ability upgrades)
- Audio identity: organized bustle, sparring sounds from the training yard, official conversations

**The Hearthstone Tavern**
- Social hub (NPC conversations, rumors, atmosphere)
- Companion interaction (deeper relationship moments)
- Bard content (if Bard archetype is included in MVP)
- Audio identity: warmth — fireplace, clinking mugs, low music, laughter

**Temple Row**
- Divine patronage interaction (speak with your god's representative)
- Healing and restoration
- God whispers (testing the divine favor system)
- Audio identity: bells, chanting, the distinct tones of different faiths

**Dockside Quarter**
- Residential area (NPC homes, personal story threads)
- Refugee quarter (Aelindran diaspora NPCs, lore and emotional grounding)
- Audio identity: quieter, waves against docks, domestic sounds, the melancholy undertone of displaced people

### The Greyvale — Wilderness Zone

Rolling countryside north of the Accord of Tides, transitioning into something darker as you head north. Contains:

**Millhaven**
- A small farming town under threat from recent Hollow activity
- NPC population with local concerns and information
- Defense and escort quest content
- Audio identity: pastoral turning anxious — birdsong, wind, distant worry

**The Greyvale Ruins**
- An ancient site predating the Sundering, possibly connected to Aelindra
- Dungeon exploration content (3–5 rooms/areas)
- Puzzle and skill challenge content
- The key discovery: an artifact bearing Veythar's seal or a journal fragment referencing "thinning the barrier"
- Audio identity: echoing stone, dripping water, ancient mechanisms, the faint wrongness of residual arcane energy

**The Hollow Incursion Site**
- A small breach where Hollow creatures have appeared far south of the Ashmark
- The land is visibly/audibly wrong: dead grass, still water, absent birdsong
- Primary combat encounter location
- Audio identity: the absence of natural sound, replaced by alien frequencies and the wrongness of the Hollow

**Greyvale Wilderness**
- Connecting paths between locations
- Points of interest for exploration and audio compass testing
- Random encounter potential
- Foraging and resource gathering for async crafting
- Audio identity: wind, grass, streams, the sounds of an open landscape that becomes more unsettling as you head north

---

## MVP Story Arc

### Arc: "The Greyvale Anomaly"

A self-contained story in 3–5 sessions that tests all core systems while planting seeds of the larger mystery.

### Session 1 — Arrival and Disruption (~30–45 min)

**Prologue** (60–90 seconds)
- Narrated introduction to Aethos, the Veil, the invasion
- Sets stakes and emotional tone
- Transitions into character creation

**Character Creation** (10–15 min)
- Narrated conversation with the DM
- Race → Class → Divine Patronage → Placement → Name & Backstory
- Player is placed in the Sunward Accord (the only MVP starting culture)

**Normalcy** (~5 min)
- The player explores the market square
- Meets 1–2 NPCs, performs a simple task (teaches navigation, interaction, skill checks)
- Meets their starting companion NPC
- The Accord of Tides feels warm, alive, worth protecting

**Disruption**
- A wounded rider arrives from the north. The market falls silent.
- News: the Ashmark has expanded. A Greyvale town is reporting Hollow creatures where none have been seen before.
- The rider collapses. The mood shifts permanently.

**Call to Action**
- The player's mentor/guild/patron asks them to investigate the Greyvale reports
- Class-appropriate framing: warrior sent to defend, seeker sent to investigate, cleric sent to heal, rogue sent to scout
- The player departs the city for the Greyvale with their companion

**Session End Hook:** The companion mentions hearing rumors about the Greyvale ruins — strange lights, old stories. Something to look into.

**Async Unlocks:** Resupply at the market (timer-based), train a skill (brief voiced scene + timer), check in with mentor (short narrative interaction).

---

### Session 2 — Investigation and First Contact (~30–45 min)

**Recap and Arrival**
- DM recaps session 1 and any async activity results
- The player arrives in Millhaven

**Investigation**
- Talk to townsfolk: gather information about the Hollow activity
- Something is off — the creatures are behaving differently here. More organized. Almost directed.
- Tracks and patterns suggest something beyond random incursion
- Tests: NPC conversation, information gathering, navigation in a new environment

**First Combat**
- Hollow creatures encountered near Millhaven
- 1–2 combat encounters testing the phase-based system
- The creatures are wrong in audio: sounds without source, alien frequencies
- Tests: combat pacing, dice rolls on HUD, companion behavior in combat, timer pressure on declarations

**Discovery**
- After combat, the player finds something unusual: residual arcane energy at the incursion site that doesn't match normal Hollow signatures
- A local elder mentions the Greyvale Ruins: "The old scholars' outpost. Been sealed for decades. But the lights started again last month."

**Session End Hook:** The ruins are clearly connected. The player needs to go there.

**Async Unlocks:** Help Millhaven fortify (strategic decision + timer), gather supplies from the Greyvale (short exploration encounter), send word back to the Accord (narrative interaction that may trigger a response from your patron god).

---

### Session 3 — The Ruins (~30–45 min)

**The Dungeon Experience**
- Exploration of the Greyvale Ruins
- 3–5 distinct areas with different challenges
- Navigation through audio cues and DM descriptions (dungeon micro-navigation test)
- Environmental storytelling: old research equipment, arcane markings, signs this was once an active scholarly outpost

**Puzzle / Skill Challenge**
- At least one non-combat challenge: a locked mechanism, a magical ward, an environmental hazard
- Tests creative problem-solving through voice interaction

**Escalating Combat**
- Hollow creatures inside the ruins, somehow feeding on or amplified by the residual arcane energy
- Harder than Greyvale encounters — tests combat scaling
- Environmental elements in combat: unstable structures, arcane energy surges

**The Discovery**
- At the deepest point: an artifact bearing Veythar's personal seal, or a journal fragment in the Lorekeeper's own notation, referencing "resonance thinning" and "the barrier's permeability"
- The player can't fully understand it, but the DM's narration makes it clear this is significant
- The companion reacts: "This... this is old. And it shouldn't be here. We need to show someone who understands."

**Session End Hook:** Return to the Accord with the discovery. Someone needs to see this.

**Async Unlocks:** Study the artifact (timer-based with a narrated result — partial understanding, more questions), the ruins remain accessible for further exploration, Millhaven sends thanks or a request for further help.

---

### Session 4 — Consequences (~30–45 min)

**The Reaction**
- Return to the Accord of Tides with the artifact/journal
- Present it to a knowledgeable NPC (an Aelindran scholar, a temple representative, a guild expert)
- The NPC's reaction raises more questions than it answers. Recognition, alarm, and then careful words: "Where exactly did you find this?"
- The NPC tries to take the artifact for "safekeeping" — the player can comply or resist

**Faction Interest**
- Word spreads. Different factions react:
  - A Veythar representative wants to "study it properly" (actually: suppress it)
  - A Syrath operative wants to know everything the player found (actually: piecing together the truth)
  - A Valdris investigator wants it entered into evidence (actually: building a case they don't yet understand)
  - An Aelora guild master wants to know if the Greyvale is safe for trade again (practical concern)
- The player navigates competing interests through conversation
- Tests: social encounters, reputation consequences, faction dynamics, player choice mattering

**Recognition**
- The player's actions are acknowledged — by the guild, their patron god, the NPCs they've helped
- A god whisper: their patron deity speaks directly to them about what they've found (tests divine favor and god interaction)
- The player's reputation in the Accord shifts based on how they handled the factions

**Session End Hook:** The ruins are part of a larger network. The artifact has implications beyond the Greyvale. Whatever was happening at that outpost wasn't isolated — and it wasn't recent. Someone set this in motion a long time ago.

**Async Unlocks:** Faction follow-ups (different NPCs reach out based on the player's choices), deeper study of the artifact (reveals more), rumors about similar sites in other regions (seeds the full game's content).

---

### Session 5 (Optional) — Escalation (~30–45 min)

**The Greyvale Escalates**
- The Hollow incursion in the Greyvale intensifies — possibly triggered by the disturbance at the ruins
- Millhaven is under direct threat
- The player must return and participate in a coordinated defense

**Group Combat Test** (if multiplayer wave)
- Multiple players defending Millhaven together
- Tests phase-based combat with multiple human players
- Tests multiplayer voice dynamics: do people talk over each other? Does the DM manage the group?

**The Arc Closes**
- The defense succeeds (or partially succeeds — consequences either way)
- Millhaven is saved or evacuated, with the player's choices determining the outcome
- The artifact/discovery is secured, but its implications remain open
- The player is recognized as someone who matters — not a hero of the world yet, but someone who's seen something important and acted on it

**The Larger World Opens**
- The DM hints at what's beyond the Greyvale: the ruins connect to the Umbral Deep, similar artifacts have been reported elsewhere, the investigation is just beginning
- The player's patron god speaks of larger concerns, broader missions
- The story arc is complete, but the mystery burns brighter than ever

**End of MVP content.** Players should be left wanting more.

---

## MVP Character Options

### Races (2–3 of 6)

| Race | Why Included | Audio Differentiation |
|---|---|---|
| **Human (Thael'kin)** | Universal baseline. Any player can relate. | Standard — the reference point |
| **Elari** | Veil-sense creates unique narrative hooks, tests race-specific audio cues | Can perceive Hollow wrongness earlier/differently |
| **Vaelti** | Sharp senses test the audio-gameplay connection most directly | Hears things others miss — early warnings, hidden details |

*Korath, Draethar, and Thessyn are deferred to post-MVP. Their unique traits (earth-sense, inner fire, deep adaptation) are compelling but not essential to validate the core experience.*

### Archetypes (4–5 of 16)

| Archetype | Category | Why Included |
|---|---|---|
| **Warrior** | Martial | Tests core combat. The straightforward entry point. |
| **Mage** | Arcane | Tests voice-based spellcasting. The most "voice-native" combat class. |
| **Rogue** | Shadow | Tests stealth, scouting, and non-combat problem solving. |
| **Cleric** | Divine | Tests healing, divine favor, and god interaction. Varies dramatically by patron. |
| **Bard** *(stretch)* | Support | Tests the most unique voice-first mechanic: performance as gameplay. Include if resources allow. |

*Remaining 11–12 archetypes deferred. The MVP four cover the essential playstyles: hit things, cast things, sneak past things, heal things.*

### Divine Patrons (3–4 of 10)

| God | Why Included |
|---|---|
| **Veythar, the Lorekeeper** | Essential — the mystery revolves around them. Their followers' quests contain the breadcrumbs. |
| **Kaelen, the Ironhand** | The martial god. Provides clear, action-oriented quest framing. Tests the "fight" path. |
| **Aelora, the Hearthkeeper** | The civilization god. Governs the Accord of Tides, the crafting system, the async economy. The "build" path. |
| **Syrath, the Veilwatcher** | The secrets god. Provides the investigation angle, tests the intrigue/information path. Essential for the faction tension in Session 4. |

*Remaining 6 gods deferred. These four create the essential tension: knowledge vs. secrets (Veythar/Syrath), action vs. building (Kaelen/Aelora), and the mystery triangle.*

---

## MVP Systems

### Must Have (Required for MVP)

| System | Scope | Implementation Reference |
|---|---|---|
| **Voice input → DM narration** | Core loop | `DungeonMasterAgent` in LiveKit `AgentSession` with Deepgram STT → Claude LLM → Inworld TTS pipeline. See *Tech Architecture — DM Agent Architecture*. |
| **AI DM engine** | Narrative + rules + tools | Three-layer architecture: voice agent (real-time), background process (prompt management), toolset (game mechanics). See *Tech Architecture — DM Agent Architecture*. |
| **DM tool system** | ~20 tools across 4 categories | World query, dice/mechanics (hybrid: LLM requests, rules engine validates and applies), game state mutation (smart validation, auto-push UI), client effects. See *Tech Architecture — Layer 3: The Toolset*. |
| **Background process** | World-aware prompt management | Event-driven + 60s timer. Rebuilds warm prompt layer via `update_instructions()`. Proactive speech with priority system (critical/important/routine). See *Tech Architecture — Layer 2: The Background Process*. |
| **Orchestration** | Output parsing, multiplayer input, session lifecycle | Strict `[CHARACTER, emotion]: "dialogue"` tags parsed by `tts_node`. 500ms multi-player input buffer. Async state persistence. Narrative session endings. See *Tech Architecture — Orchestration Design*. |
| **Conversational navigation** | City + wilderness + dungeon | Intent-based movement via `move_player` tool with path validation. DM narrates transitions. |
| **Phase-based combat** | 3–4 encounter types | Declaration → resolution → narration. `request_attack`, `request_skill_check`, `request_saving_throw` tools resolve atomically. Combat UI auto-pushes via LiveKit RPC. |
| **DM ventriloquism** | Multi-character voices | `tts_node` override routes character dialogue to Inworld TTS with per-character voiceId and emotion-driven expressiveness settings. |
| **HUD: combat UI** | HP bars, turn order, status effects | Auto-pushed by mutation tools. Updated in real-time during combat. Essential MVP client effect. |
| **HUD: item cards** | Loot popups on item discovery | Auto-pushed by `add_to_inventory` tool. Displays item image, stats, rarity. |
| **HUD: character sheet** | Basic stats, health, inventory | Glanceable. Not the primary interface. |
| **HUD: dice rolls** | Key rolls with animation + audio cue | Driven by `narrative_hint` from mechanics tools. |
| **HUD: simple map** | Fills in as you explore | Breadcrumb trail, current location, points of interest. |
| **Companion NPC** | 1 companion per player (ventriloquized) | Personality, combat participation, guidance suggestions. Voiced by the DM agent with distinct voice and personality tags. |
| **Escalating guidance** | All 4 levels | Ambient nudge → companion suggestion → DM guidance → explicit help. `global_hints` in quest schemas feed the guidance system. |
| **Divine favor** | Basic tracking | Increases through aligned actions. Triggers god whisper at milestone. God-agent heartbeat evaluates player alignment. |
| **Sound effects** | Combat + environment + Hollow | `play_sound` tool triggers named effects on client. Essential MVP client effect. |
| **Async activities** | 2–3 types | Timer-based crafting, skill training, one narrative check-in. Real-time clock (wall-clock = game-clock). |
| **World simulation** | Time-driven + simulation tick + basic god heartbeat | NPC schedules, corruption drift, economy tick, basic god-agent rules. See *World Data & Simulation — World Simulation Rules*. |
| **Content pipeline** | Tier 1 authored + tier 2 generated | JSON entity schemas. ~35-40 tier 1 entities, ~55-75 tier 2. On-demand generation for undefined areas. See *World Data & Simulation — Content Authoring Format*. |
| **Basic sound design** | Environments + combat + Hollow | Ambient soundscapes for each location. Combat audio. The Hollow's wrongness. |
| **Prologue narration** | Pre-recorded or high-quality TTS | The 60–90 second world introduction. Sets the tone. |

### Nice to Have (Include if Resources Allow)

| System | Notes |
|---|---|
| **Audio compass** | Directional audio for key destinations. Full spatial audio is post-MVP. |
| **Bard performance mechanic** | Player vocal input as gameplay. High impact but complex. |
| **Full spatial audio** | 3D positional sound in headphones. Incredible if achievable, but basic stereo directional audio suffices. |
| **NPC relationship memory** | NPCs remember previous interactions across sessions. Partially supported by `npc_dispositions` state table — full narrative memory is stretch. |
| **Faction reputation display** | Visual tracking of faction standing on HUD. Data exists in `player_reputation` table. |
| **God whisper notifications** | Push notifications with narrative hooks for async re-engagement. |
| **Dynamic tool sets** | Context-dependent tools via `update_tools()` — combat tools only during combat, merchant tools only at shops. Reduces tool count for LLM reliability. |

### Deferred (Post-MVP)

| System | Reason |
|---|---|
| Multiple starting cultures | Only Sunward Accord for MVP. |
| Full pantheon (10 gods) | 3–4 gods sufficient for testing. |
| Full class roster (16 archetypes) | 4–5 archetypes sufficient for testing. |
| PvP (all forms) | Cooperative experience only for MVP. |
| Territory control | No guild-level systems in MVP. |
| Property system | No housing or ownership in MVP. |
| Seasonal content / battle pass | No live service features in MVP. |
| Arena combat | No structured PvP in MVP. |
| Full async loop | Minimal async to test the concept only. |
| Macro travel between regions | Only one region exists in MVP. |
| God meta-agents (full Civilization layer) | Gods run basic rule-based heartbeats for MVP. Full LLM-driven god decisions and inter-god conflict are post-MVP. See *World Data & Simulation — God-Agent Heartbeat*. |

---

## Playtest Structure

### Wave 1 — Solo Playtests

**Format:** Single player + AI companion. No other humans.
**Purpose:** Isolate the core experience. Does the AI DM work? Does voice navigation work? Does combat feel good with one player? Is the guidance system sufficient?
**Duration:** 3–4 sessions over 1–2 weeks per tester.
**Tester pool:** 10–15 testers with varied RPG experience (from never-played to veteran).

### Wave 2 — Group Playtests

**Format:** 2–4 human players + optional AI companions.
**Purpose:** Test multiplayer dynamics. Does phase-based combat work with multiple voices? Do players talk over each other? Does the DM manage multiple players? Do social dynamics enhance the experience?
**Duration:** 3–5 sessions over 2–3 weeks per group.
**Tester pool:** 5–8 groups of varying size and RPG experience.

### Between Waves

Iterate on everything that broke. Prioritize fixes based on which of the six core questions are failing.

---

## Success Criteria

| Metric | Target | Measurement |
|---|---|---|
| **Voice navigation** | Players move through environments without being stuck for >30 seconds | Observation + post-session survey |
| **Combat engagement** | 80%+ of players rate combat as "exciting" or "fun" | Post-session survey |
| **DM immersion** | Players describe the DM as a character, not a system | Post-session interview |
| **Guidance effectiveness** | No player reports feeling "lost" or "stuck" for extended periods | Observation + survey |
| **Emotional engagement** | Players express attachment to companion and/or concern about threat | Post-session interview |
| **Return rate** | 80%+ of testers want to play session 2 after completing session 1 | Behavior tracking + survey |
| **Async engagement** | 60%+ of players with async activities check in at least once between sessions | Behavior tracking |
| **Mystery traction** | Players ask unprompted questions about the artifact/discovery | Post-session interview |
| **Session pacing** | Sessions feel complete in 30–45 min without rushing or dragging | Observation + survey |
| **Audio immersion** | 80%+ of players report headphones made a meaningful difference | Post-session survey |
| **Overall verdict** | "Would you pay for this experience?" — 70%+ yes | Post-playtest survey |

---

## MVP Development Priorities

Ordered by dependency and risk. Aligned with the detailed 18-step priority list in the *Technical Architecture Document — Development Priorities*.

**Phase 1 — Core Voice Loop (steps 1-4)**

1. **LiveKit integration + basic voice loop.** Client connects to a room, speaks, receives audio back. Prove the transport works, VAD feels natural, measure end-to-end latency.
2. **STT + TTS pipeline.** Deepgram Nova-3 in, Inworld TTS-1.5 Max out. Prove quality and latency meet the ~1.2-2.0s target.
3. **DM Agent — basic voice loop.** `DungeonMasterAgent` with static system prompt and Claude. Prove the AI DM can hold a freeform conversation.
4. **DM ventriloquism via tts_node.** Output parser splits `[CHARACTER, emotion]: "dialogue"` tags and routes to per-character voices. Prove multiple characters sound distinct.

**Phase 2 — Game Mechanics (steps 5-9)**

5. **World query tools.** `query_npc`, `query_location`, `query_lore`, `query_inventory` backed by the content DB. Prove the DM can look up information mid-conversation.
6. **Dice & mechanics tools.** `request_skill_check`, `request_attack`, `request_saving_throw` with hybrid validation. Prove the DM calls for checks appropriately and narrates outcomes.
7. **Game state mutation tools.** `move_player`, `add_to_inventory`, `update_quest`, `award_xp` with smart validation and auto-push client UI updates. Prove mutations enforce game rules.
8. **Background process.** Event bus + timer, `update_instructions()` for prompt management, proactive speech with priority classification. Prove the DM stays aware of world changes.
9. **Per-turn context injection.** `on_user_turn_completed` hook with combat state, pending events, contextual details. Prove ephemeral context improves DM quality.

**Phase 3 — Multiplayer & Combat (steps 10-11)**

10. **Multi-player room.** 2+ humans + DM agent. 500ms input buffer. Prove simultaneous VAD, player identity tracking, and DM managing multiple players.
11. **Combat system.** Phase-based with mechanics tool chain. Combat UI (HP bars, turn order, status effects). Sound effects. Prove combat is exciting in audio.

**Phase 4 — World & Content (steps 12-16)**

12. **Navigation and world.** Accord of Tides district + Greyvale. `move_player` driving location transitions with scene narration.
13. **Companion NPC** (ventriloquized). Distinct personality, combat participation, guidance suggestions.
14. **Guidance system.** Escalating nudges, companion suggestions, `global_hints` from quest schemas.
15. **Content: the Greyvale arc.** Tier 1 authored entities for the story. Tier 2 generated filler. The playtest experience.
16. **Async system.** Timer-based activities with real-time clock. Narrative check-ins.

**Phase 5 — Polish & Post-MVP (steps 17-18)**

17. **Companion extraction** (post-MVP). Promote companion to independent agent.
18. **God whisper system.** Divine favor tracking + god voice via temporary agent dispatch.

---

## Document Relationships

| Document | Purpose | Status |
|---|---|---|
| **Product Overview** | Executive summary, elevator pitch, document map | Living |
| **Game Design** | Full player experience, all game systems | Living |
| **Aethos Lore** | World, gods, peoples, narrative | Living |
| **MVP Specification** *(this document)* | Minimum testable slice | Living |
| **Technical Architecture** | DM agent architecture, orchestration, voice pipeline, multiplayer, infrastructure | Living |
| **World Data & Simulation** | Content authoring format (JSON schemas), world simulation rules, data model | Living |
| **Cost Model** | Per-session and subscriber unit economics | Living |

---

*This document is living — it will be refined as development planning continues.*
