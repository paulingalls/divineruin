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

**Async Unlocks:** *Crafting:* Resupply at the market — choose between restocking basic supplies (1hr, safe) or commissioning a hollow-ward charm from Grimjaw (4hr, material-dependent outcome). *Training:* Train with a mentor NPC — brief voiced scene setting up the focus, 6hr timer, culmination scene with progression choice. *Companion errand:* Send companion to ask around about the Greyvale ruins — returns in 2-4 hours with local rumors and a lead.

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

**Async Unlocks:** *Crafting:* Help Millhaven fortify — choose where to allocate materials (north barricade vs. watchtower vs. evacuation supplies), outcome affects session 3 environment. *Companion errand:* Send companion to scout the road to the ruins — returns with route intel, potential ambush warnings, and something unexpected they found along the way. *World event:* Send word back to the Accord — triggers a god whisper from patron deity (pre-rendered audio, atmospheric, cryptic guidance about the ruins).

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

**Async Unlocks:** *Crafting:* Study the artifact — choose analytical approach (careful/slow = 8hr, thorough results vs. aggressive/fast = 3hr, partial understanding + risk of triggering something). Narrated outcome reveals partial understanding and raises new questions. *Companion errand:* Send companion back to Millhaven to check on the town — returns with thanks, a small reward, and news about whether the fortification decision mattered. *Training:* The dungeon revealed gaps in the player's abilities — a mentor offers targeted training based on what went wrong in combat.

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

**Async Unlocks:** *Faction follow-ups:* Different NPCs reach out based on the player's choices — each is a pending decision in the async hub with a voiced message and a response choice. *Crafting:* Deeper artifact study (longer timer, reveals more about Veythar's secret research, narrated by Scholar Emris). *God whisper:* Patron deity sends a more urgent message — not just cryptic anymore, but directional. *Companion errand:* Companion hears rumors about similar sites in other regions — returns with a lead that seeds the full game's content beyond MVP.

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
| **Async activities** | 3 types for MVP | **Crafting** (material choice → timer → narrated outcome with decision), **Companion errand** (send companion to scout/gather → timer → narrated return with intel), **Training** (mentor scene → timer → culmination with choice). Pre-rendered audio narration (not live voice sessions). REST-based decision inputs. See *Game Design — Asynchronous Play*. |
| **Catch-Up layer + Enter the World** | Integrated home screen | Top: Catch-Up feed (world news, resolved activities with narrated audio + decisions, pending decisions, activity launcher). Bottom: single "Enter the World" button that opens LiveKit voice connection — no mode selection, DM adapts to player behavior. Narrative push notifications ("Kael returned from the northern road. He looks worried."). See *Game Design — Session Types — No Mode Selection*. |
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
| **God whisper notifications** | Push notifications with narrative hooks for async re-engagement. Triggered by god-agent heartbeat. Part of the async hub's "pending decisions" section. |
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
| Full async loop | MVP includes crafting, training, companion errands, and god whispers. Deferred: mini-quests (live voice async sessions), territory/resource management, faction reputation slow burn, seasonal event timers, party coordination voice messages. |
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
16. **Async system.** Timer-based activities with real-time clock. Pre-rendered narration pipeline (LLM generates outcome text → TTS synthesizes → stored for playback). Async hub UI with world news, resolved activities, pending decisions, and activity launcher. REST endpoints for decision inputs. Push notification system with narrative hooks. See *Game Design — Asynchronous Play* for full design.

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

## Appendix: Starter Content Entities

The following JSON entities implement the MVP story arc using the schemas defined in *World Data & Simulation*. These are the tier 1 authored entities that form the backbone of the Greyvale Anomaly arc. Tier 2 filler (ambient NPCs, common items, connecting paths) can be generated from templates. Entity IDs are referenced across locations, NPCs, items, and quests to create a connected content graph.

### Tier 1 Locations

```json
{
  "id": "accord_market_square",
  "name": "Market Square",
  "tier": 1,
  "district": "accord_central",
  "region": "sunward_coast",
  "tags": ["market", "social", "commerce", "starting_area"],
  "description": "The sound hits you first — a rolling wave of voices, cart wheels, and harbor bells. The market square of the Accord of Tides is a crossroads of the southern world. Vendors call prices in three languages. The smell of fried fish and foreign spices mingles in the salt air. Somewhere nearby, a street musician is losing a competition with the gulls.",
  "atmosphere": "bustling, warm, alive",
  "key_features": [
    "a central fountain where travelers wash road dust from their boots",
    "a guild noticeboard thick with postings and bounty notices",
    "the harbormaster's office with a line out the door"
  ],
  "hidden_elements": [
    {
      "id": "guild_notice_greyvale",
      "discover_skill": "perception",
      "dc": 10,
      "description": "a recent posting about disturbances in the Greyvale, partially covered by newer notices"
    }
  ],
  "exits": {
    "north": {"destination": "accord_guild_hall"},
    "east": {"destination": "accord_temple_row"},
    "south": {"destination": "accord_dockside"},
    "west": {"destination": "accord_hearthstone_tavern"}
  },
  "conditions": {
    "time_night": {
      "description_override": "The market square is emptied out. Lanterns swing on their chains. The fountain burbles to no one. A pair of city guards walk their circuit, boots echoing on wet stone.",
      "atmosphere": "quiet, reflective, distant harbor sounds",
      "npcs_remove": ["market_vendors_tier2"],
      "danger_level": 0
    },
    "quest:greyvale_anomaly:stage >= 1": {
      "key_features_add": ["a cluster of worried merchants discussing trade route disruptions to the north"]
    }
  },
  "ambient_sounds": "market_bustle",
  "ambient_sounds_night": "harbor_quiet"
}
```

```json
{
  "id": "millhaven",
  "name": "Millhaven",
  "tier": 1,
  "district": "millhaven_town",
  "region": "greyvale",
  "tags": ["town", "farming", "threatened", "quest_hub"],
  "description": "Millhaven used to be a quiet farming town. You can hear what it should sound like — wind through barley, a mill wheel turning, children somewhere. But there's a tension underneath. Conversations drop to whispers when strangers arrive. The mill wheel needs oiling and no one's bothered. Dogs bark at the northern tree line for no visible reason.",
  "atmosphere": "pastoral unease, normality fraying at the edges",
  "key_features": [
    "the old stone mill at the town's center, still running but neglected",
    "a makeshift notice board with warnings about traveling north alone",
    "a cluster of refugee families camped near the south road, recently arrived from further north"
  ],
  "hidden_elements": [
    {
      "id": "millhaven_tracks",
      "discover_skill": "investigation",
      "dc": 13,
      "description": "unusual tracks at the northern edge of town — not animal, not human, impressions in the earth that seem to resist being looked at directly"
    }
  ],
  "exits": {
    "south": {"destination": "greyvale_south_road"},
    "north": {"destination": "greyvale_wilderness_north"},
    "east": {"destination": "millhaven_inn"}
  },
  "conditions": {
    "quest:greyvale_anomaly:stage >= 3": {
      "atmosphere": "openly frightened, people preparing to evacuate",
      "key_features_add": ["townsfolk packing carts and arguing about whether to flee south"]
    }
  },
  "ambient_sounds": "rural_town_uneasy"
}
```

```json
{
  "id": "greyvale_ruins_entrance",
  "name": "Greyvale Ruins — Entrance Hall",
  "tier": 1,
  "district": "greyvale_ruins",
  "region": "greyvale",
  "tags": ["dungeon", "ancient", "aelindran", "mystery"],
  "description": "The stairs descend into stone that predates everything above it. The air changes — cool, still, tasting of dust and something faintly metallic. Your footsteps echo in a way that suggests a large space ahead. Light from above fades quickly. Then you hear it — a low, almost subliminal hum, as if the stone itself is vibrating at a frequency just below hearing.",
  "atmosphere": "ancient, hushed, subtly wrong",
  "key_features": [
    "Aelindran script carved into the archway — partially defaced but legible to a scholar",
    "old sconces that once held arcane lights, now dark",
    "a research station with scattered papers and broken glass, more recent than the ruins themselves"
  ],
  "hidden_elements": [
    {
      "id": "ruins_journal_fragment",
      "discover_skill": "investigation",
      "dc": 15,
      "description": "a journal page wedged beneath a fallen shelf — handwriting in academic Aelindran, referencing 'resonance thinning' and a 'controlled aperture'"
    },
    {
      "id": "veythar_seal_mark",
      "discover_skill": "arcana",
      "dc": 16,
      "description": "a ward-seal on the inner door bearing Veythar's personal sigil — not a temple mark, a private one"
    }
  ],
  "exits": {
    "up": {"destination": "greyvale_ruins_exterior"},
    "deeper": {"destination": "greyvale_ruins_inner", "requires": "veythar_seal_mark.discovered || skill_check:arcana:14"}
  },
  "conditions": {
    "hollow_corruption >= 3": {
      "atmosphere_add": "the hum is louder now, oscillating, and you feel it in your teeth",
      "danger_level_add": 2
    }
  },
  "ambient_sounds": "dungeon_ancient_hum"
}
```

```json
{
  "id": "hollow_incursion_site",
  "name": "The Hollow Breach",
  "tier": 1,
  "district": "greyvale_north",
  "region": "greyvale",
  "tags": ["combat", "hollow", "dangerous", "corruption"],
  "description": "You know you've arrived because the world stops. The birdsong cuts off mid-phrase. The wind dies. The grass beneath your feet is grey and brittle, crumbling at the edges like ash. And then you hear it — not a sound, exactly. An absence shaped like sound. A pressure in your ears that has no source. Something is here. Something that doesn't belong in any world you understand.",
  "atmosphere": "deeply wrong, alien silence, sensory inversion",
  "key_features": [
    "a circle of dead earth roughly thirty paces across, the grass grey and crumbling",
    "a shimmer in the air at the center — not light, not darkness, something the eyes refuse to process",
    "the remains of what might have been animals, but they're wrong — too many joints, fur growing inward"
  ],
  "hidden_elements": [
    {
      "id": "breach_residual_energy",
      "discover_skill": "arcana",
      "dc": 14,
      "description": "arcane residue at the breach's edge that doesn't match normal Hollow signatures — it's structured, almost deliberate, as if something was opened rather than broken through"
    }
  ],
  "exits": {
    "south": {"destination": "greyvale_wilderness_north"}
  },
  "conditions": {},
  "ambient_sounds": "hollow_wrongness"
}
```

### Tier 1 NPCs

```json
{
  "id": "guildmaster_torin",
  "name": "Guildmaster Torin",
  "tier": 1,
  "role": "guild hall master, quest giver",
  "species": "human",
  "gender": "male",
  "age": "late 50s",
  "appearance": "broad-shouldered but desk-softened, ink-stained fingers, a face built for authority now creased with worry",
  "personality": ["pragmatic", "decisive", "privately exhausted", "cares more than he shows"],
  "speech_style": "direct, wastes no words, occasional dry humor that surfaces when he forgets to be worried, calls everyone 'recruit' until they earn a name",
  "mannerisms": ["drums fingers on desk when thinking", "sighs before delivering bad news"],
  "backstory_summary": "Twenty years running the Accord guild. Has seen every type of adventurer and threat. The Greyvale reports are the first thing in years that genuinely scares him — not the Hollow itself, but how far south they've appeared.",
  "knowledge": {
    "free": [
      "general guild operations and available contracts",
      "the Greyvale reports — Hollow creatures sighted far south of the Ashmark"
    ],
    "disposition >= friendly": [
      "he's sent three scouts north already — two returned shaken, one hasn't returned",
      "the temple authorities are downplaying the reports and he's furious about it"
    ],
    "disposition >= trusted": [
      "he suspects someone in the temple hierarchy is suppressing information about the Greyvale",
      "his missing scout's last report mentioned the old ruins and 'lights that moved wrong'"
    ]
  },
  "schedule": {
    "07:00-22:00": "accord_guild_hall",
    "22:00-07:00": "torin_quarters"
  },
  "default_disposition": "neutral",
  "disposition_modifiers": {
    "completed_greyvale_quest_stage": 3,
    "reported_findings": 2,
    "lied_about_findings": -4,
    "defended_millhaven": 3
  },
  "inventory_pool": null,
  "secrets": [
    "his missing scout is someone he personally trained — the worry is personal, not just professional"
  ],
  "faction": "accord_guild",
  "voice_id": "torin_v1",
  "voice_notes": "deep baritone, clipped delivery, softens slightly when genuinely worried"
}
```

```json
{
  "id": "elder_yanna",
  "name": "Elder Yanna",
  "tier": 1,
  "role": "Millhaven elder, local authority",
  "species": "human",
  "gender": "female",
  "age": "mid 60s",
  "appearance": "wiry, sun-weathered, moves with the deliberate economy of someone who's worked hard their entire life",
  "personality": ["stubborn", "protective", "distrustful of outsiders", "hiding deep fear"],
  "speech_style": "short sentences, farmland dialect, doesn't answer questions she doesn't like, asks her own instead",
  "mannerisms": ["looks north involuntarily when anyone mentions the Hollow", "grips her walking stick when stressed"],
  "backstory_summary": "Born in Millhaven, will die in Millhaven. Has watched the town slowly empty as younger people move south. The Hollow reports are the final threat to everything she's spent her life protecting. Won't leave. Won't ask for help easily.",
  "knowledge": {
    "free": [
      "the Hollow creatures were first spotted two weeks ago near the northern fields",
      "three farms have been abandoned"
    ],
    "disposition >= friendly": [
      "the creatures are behaving strangely — almost organized, moving in patterns",
      "her neighbor Aldric went to the ruins last month and came back different — won't speak, barely eats"
    ],
    "disposition >= trusted": [
      "Aldric told her one thing before going silent: 'The lights know you're looking'",
      "she found a strange stone in his pocket — smooth, warm, and it hums when you hold it near a candle"
    ]
  },
  "schedule": {
    "05:00-20:00": "millhaven",
    "20:00-05:00": "yanna_farmhouse"
  },
  "default_disposition": "wary",
  "disposition_modifiers": {
    "helped_townsfolk": 2,
    "mentioned_evacuation": -2,
    "defended_millhaven_from_hollow": 5,
    "showed_respect_for_millhaven": 1
  },
  "inventory_pool": null,
  "secrets": [
    "Aldric's stone is in her pocket right now — she's afraid to show anyone because she doesn't know what it means"
  ],
  "faction": "independent",
  "voice_id": "yanna_v1",
  "voice_notes": "alto, gravelly, speaks slowly and deliberately, rural accent"
}
```

```json
{
  "id": "scholar_emris",
  "name": "Emris of the Diaspora",
  "tier": 1,
  "role": "Aelindran scholar, artifact expert",
  "species": "elari",
  "gender": "non-binary",
  "age": "appears mid 30s (Elari — actually much older)",
  "appearance": "thin, precise movements, eyes that focus too intensely, ink-stained fingers, always carrying a satchel of notes",
  "personality": ["brilliant", "socially awkward", "haunted by Aelindra's fall", "desperately hopeful that the old knowledge can be recovered"],
  "speech_style": "rapid and precise when discussing scholarship, halting and uncertain in casual conversation, occasionally slips into Aelindran academic terminology without realizing",
  "mannerisms": ["adjusts spectacles that aren't there (lost in the fall of Aelindra, still reaches for them)", "speaks to artifacts as if they can hear"],
  "backstory_summary": "Survived the fall of Aelindra as a junior archivist. Has spent thirty years cataloging recovered artifacts in the Accord of Tides, searching for any clue about why the city fell. When the player brings the Greyvale artifact, Emris recognizes the notation style immediately — and it terrifies them.",
  "knowledge": {
    "free": [
      "general Aelindran history and the Voidfall narrative",
      "identification of common Aelindran artifacts"
    ],
    "disposition >= friendly": [
      "the Greyvale ruins were an Aelindran research outpost — one that was officially shut down before the fall",
      "the artifacts the player found use a notation system only a handful of scholars ever used"
    ],
    "disposition >= trusted": [
      "the notation is Veythar's personal system — not temple standard, private",
      "Emris recognizes it because their mentor used the same system — and their mentor disappeared before the fall of Aelindra"
    ],
    "quest_triggered": {
      "quest": "greyvale_anomaly",
      "stage": 4,
      "reveals": "the journal fragment references 'controlled aperture experiments' — someone was deliberately weakening the Veil at that site, and the research predates the Sundering by centuries"
    }
  },
  "schedule": {
    "08:00-23:00": "accord_dockside",
    "23:00-08:00": "emris_study"
  },
  "default_disposition": "cautious",
  "disposition_modifiers": {
    "brought_aelindran_artifact": 4,
    "showed_interest_in_scholarship": 2,
    "dismissed_aelindran_history": -3,
    "mentioned_veythar_connection": 3
  },
  "inventory_pool": null,
  "secrets": [
    "Emris suspects their missing mentor was working on the same project documented in the Greyvale ruins",
    "they have a letter from their mentor — the last one — that mentions 'a discovery that changes everything' but gives no details"
  ],
  "faction": "aelindran_diaspora",
  "voice_id": "emris_v1",
  "voice_notes": "soft, quick, slightly breathless when excited, Elari accent — elongated vowels, precise consonants"
}
```

### Tier 1 Quest: The Greyvale Anomaly

```json
{
  "id": "greyvale_anomaly",
  "name": "The Greyvale Anomaly",
  "tier": 1,
  "type": "main",
  "description": "Reports of Hollow creatures far south of the Ashmark. A farming town frightened. An ancient ruin that's started glowing at night. Something is wrong in the Greyvale — and it's not a random incursion.",
  "giver": "guildmaster_torin",
  "stages": [
    {
      "id": "stage_1_investigate",
      "name": "The Road North",
      "objective": "Travel to Millhaven and investigate the Hollow reports.",
      "hints": [
        "Your companion mentions hearing that Millhaven is a day's travel north of the Accord.",
        "Your companion suggests talking to Guildmaster Torin before leaving — he might have more details about what the scouts found.",
        "Your companion says directly: 'Torin said the town's called Millhaven. Let's head north along the trade road.'"
      ],
      "completion_conditions": {
        "type": "location_reached",
        "location": "millhaven"
      },
      "on_complete": {
        "xp": 50,
        "world_effects": ["torin_disposition +1"],
        "narrative_beat": "You arrive in Millhaven. It's quieter than a farming town should be."
      }
    },
    {
      "id": "stage_2_gather_intel",
      "name": "Something Wrong",
      "objective": "Talk to Millhaven's residents and learn what they've seen.",
      "hints": [
        "Your companion notices a woman watching you from near the mill — she looks like she's in charge.",
        "Your companion suggests asking at the inn — 'Barkeeps always know what's going on.'",
        "Your companion says: 'That's Elder Yanna. She runs this town. We should talk to her.'"
      ],
      "completion_conditions": {
        "type": "knowledge_acquired",
        "required_info": ["hollow_sighting_details", "ruins_light_reports"],
        "sources": ["elder_yanna", "millhaven_inn_npcs"]
      },
      "on_complete": {
        "xp": 75,
        "world_effects": [],
        "narrative_beat": "The pieces are forming a picture. The creatures aren't random. The ruins are connected. You need to go there."
      }
    },
    {
      "id": "stage_3_first_contact",
      "name": "First Blood",
      "objective": "Engage the Hollow creatures near Millhaven and survive.",
      "hints": [
        "Your companion's attention snaps north. 'Do you hear that? That... silence?'",
        "Your companion draws their weapon. 'Something's moving out there. This is it.'",
        "Your companion says: 'The tracks lead toward the northern fields. Ready up.'"
      ],
      "completion_conditions": {
        "type": "combat_completed",
        "encounter": "hollow_patrol_greyvale",
        "outcome": "survived"
      },
      "on_complete": {
        "xp": 150,
        "rewards": [{"item": "hollow_bone_fragment", "quantity": 1}],
        "world_effects": ["millhaven_morale +2", "yanna_disposition +2"],
        "narrative_beat": "The creatures are dead — or gone, or dispersed, you're not sure anything that wrong can really die. At the incursion site, you notice something. The residual energy doesn't match normal Hollow signatures. It's structured. Almost deliberate."
      }
    },
    {
      "id": "stage_4_the_ruins",
      "name": "What Lies Beneath",
      "objective": "Explore the Greyvale Ruins and discover what's causing the disturbance.",
      "hints": [
        "Your companion keeps glancing at the hills to the northeast. 'The elder mentioned the old ruins. And the lights.'",
        "Your companion says: 'Whatever's happening with the Hollow, those ruins are connected. I'd bet on it.'",
        "Your companion says directly: 'We need to go to the Greyvale Ruins. The answer's there.'"
      ],
      "completion_conditions": {
        "type": "item_discovered",
        "items": ["ruins_journal_fragment"],
        "location": "greyvale_ruins_entrance"
      },
      "on_complete": {
        "xp": 200,
        "rewards": [{"item": "veythar_sealed_artifact", "quantity": 1}],
        "world_effects": ["greyvale_corruption +1", "event:ruins_discovery_ripple"],
        "narrative_beat": "You hold the journal page. The notation is academic, precise. You can't read all of it, but some phrases are clear: 'resonance thinning,' 'controlled aperture,' 'acceptable threshold.' Someone was doing this on purpose. Your companion is very quiet."
      },
      "branches": {
        "keep_artifact": {
          "description": "Keep the artifact. Don't show it to anyone yet.",
          "effects": ["player_has_veythar_artifact: true"],
          "next_stage": "stage_5_return"
        },
        "show_companion": {
          "description": "Show the artifact to your companion immediately.",
          "effects": ["companion_knows_artifact: true", "companion_disposition +3"],
          "next_stage": "stage_5_return"
        }
      }
    },
    {
      "id": "stage_5_return",
      "name": "The Weight of Discovery",
      "objective": "Return to the Accord of Tides and report what you found.",
      "hints": [
        "Your companion says: 'We need to get this to someone who can read it. Back to the Accord.'",
        "Your companion mentions the Aelindran scholars in the Dockside Quarter. 'If anyone can read old academic notation, it's them.'",
        "Your companion says: 'Emris — the Aelindran archivist in the Dockside Quarter. They'd know what this means.'"
      ],
      "completion_conditions": {
        "type": "npc_interaction",
        "npc": "scholar_emris",
        "topic": "greyvale_artifact"
      },
      "on_complete": {
        "xp": 200,
        "world_effects": [
          "emris_disposition +4",
          "event:faction_interest_triggered",
          "event:god_whisper:player_patron"
        ],
        "narrative_beat": "Emris takes the journal page with trembling hands. They read it once. Then again. Their face goes through recognition, confusion, and something that looks a lot like fear. 'Where did you find this?' they ask, very quietly. 'Where exactly?'"
      }
    }
  ],
  "failure_conditions": {
    "player_death_in_ruins": {
      "consequence": "respawn at Millhaven, ruins remain accessible, Hollow corruption +1"
    }
  },
  "global_hints": {
    "stuck_stage_1": "Your companion might suggest checking with Torin at the guild hall, or simply heading north.",
    "stuck_stage_2": "Your companion suggests talking to Elder Yanna or visiting the inn.",
    "stuck_stage_3": "Your companion notices disturbing signs to the north and suggests investigating.",
    "stuck_stage_4": "Your companion reminds you about the ruins. 'The lights. The connection to the Hollow. It's all there.'",
    "stuck_stage_5": "Your companion suggests finding someone in the Accord who understands old Aelindran scholarship."
  }
}
```

### Tier 1 Items

```json
{
  "id": "veythar_sealed_artifact",
  "name": "Sealed Research Tablet",
  "tier": 1,
  "type": "quest_item",
  "rarity": "rare",
  "description": "A smooth stone tablet the size of your palm. It's warm to the touch and covered in precise, tiny notation that shifts when you're not looking directly at it. A seal mark on the reverse — not a temple seal. Something personal.",
  "tags": ["aelindran", "veythar", "mystery", "quest"],
  "weight": 0.5,
  "effects": [
    {"type": "passive_detect", "trigger": "near_veil_weakness", "description": "the tablet grows warmer and the notation glows faintly"}
  ],
  "value_base": 0,
  "value_modifiers": {},
  "lore": "Research notes from an Aelindran outpost that was sealed long before the Sundering. The notation system is non-standard — personal, not academic. Whoever wrote this didn't want it found in the official archives.",
  "found_in": ["greyvale_ruins_entrance"]
}
```

```json
{
  "id": "hollow_bone_fragment",
  "name": "Hollow-Bone Fragment",
  "tier": 1,
  "type": "material",
  "rarity": "uncommon",
  "description": "A shard of something that might be bone. It's cold — not room-temperature cold, actively cold, as if it's drawing heat from the air around it. It makes a sound like a tuning fork when struck, but the pitch is wrong. Not a frequency you've heard before.",
  "tags": ["hollow", "material", "unsettling", "crafting"],
  "weight": 0.3,
  "effects": [
    {"type": "passive_aura", "description": "nearby plants wilt slowly; animals avoid the carrier"}
  ],
  "value_base": 50,
  "value_modifiers": {
    "faction:aelindran_diaspora": 2.0,
    "npc:scholar_emris": 3.0
  },
  "lore": "Salvaged from a Hollow creature after combat. Scholars in the Accord would pay well for a sample — intact Hollow material is rare this far south.",
  "found_in": ["hollow_incursion_site"]
}
```

### Entity Summary

| Category | Tier 1 (Authored) | Tier 2 (Generated) | Notes |
|---|---|---|---|
| **Locations** | 4 shown above + guild hall, tavern, temple row, dockside, ruins inner chambers, ruins exterior, greyvale wilderness paths (~12 total) | Connecting paths, ambient market stalls, residential streets (~15-20) | Tier 1 locations have full descriptions, hidden elements, and conditions |
| **NPCs** | 3 shown above + companion (Kael/Lira/Tam/Sable), tavern keeper, temple representative, missing scout (~8-10 total) | Market vendors, guards, townsfolk, travelers (~15-20) | Tier 1 NPCs have gated knowledge and disposition modifiers |
| **Items** | 2 shown above + healing supplies, basic weapons, guild contract scroll, Yanna's strange stone (~8-10 total) | Common potions, basic gear, trade goods, food (~25-30) | Tier 1 items have narrative descriptions and lore |
| **Quests** | The Greyvale Anomaly (5 stages, shown above) + 2-3 side quests (defend Millhaven, investigate Aldric, Emris's research) | Repeatable bounties (Hollow patrols, foraging) (~3-5) | Main quest has branches and world effects |
| **Events** | Disruption at market (session 1), Hollow patrol encounter, ruins discovery, faction interest trigger, god whisper (~8-10) | Ambient events (weather changes, NPC schedule moments) (~5-8) | Tier 1 events have dm_instructions with mood and key beats |
| **Total** | ~35-40 | ~65-80 | Within MVP scope of ~110 entities |

---

*This document is living — it will be refined as development planning continues.*
