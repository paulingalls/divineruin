# Agent Handoffs, Scenes, and Structured Play

> Design document for refactoring the DM agent from a single monolithic agent to a
> multi-agent architecture using LiveKit's native handoff mechanism.

## Problem Statement

The current DM agent is a single `DungeonMasterAgent` that handles everything: prologue
playback, character creation, exploration, combat, companion interactions, and scripted
narrative events. This creates several problems:

1. **Prompt bloat.** The creation agent carries gameplay tool descriptions it never uses.
   The gameplay agent carries creation tool definitions it will never use again. Every
   phase pays the token cost of every other phase.

2. **Awkward phase transitions.** Character creation and gameplay are actually two
   separate sessions — the player must disconnect and reconnect. The "welcome to the
   world" narration happens in creation mode without hot context, background process,
   or gameplay tools.

3. **Fragile event triggers.** The companion meeting only fires on location *change* to
   `accord_market_square`, but first-session players *start* there. The player must leave
   and return to trigger it — a bug that makes the core onboarding moment unreliable.

4. **No structural guidance.** The LLM is responsible for pacing, quest gating, and
   narrative progression with no scaffolding. Early sessions lack direction because the
   companion (the designed hint-giver) isn't reliably present.

## LiveKit Agent Handoffs

LiveKit's Python agents framework provides two handoff mechanisms:

### Tool-Return Handoff (LLM-Driven)

A `@function_tool` returns a new `Agent` instance. The framework detects this and
switches automatically. Best for transitions the LLM should decide (e.g., starting
combat).

```python
class WildernessAgent(Agent):
    @function_tool()
    async def start_combat(self, context: RunContext, ...):
        """Begin combat encounter."""
        # ... set up combat state ...
        sd = self.session.userdata
        sd.pre_combat_agent_type = "wilderness"
        return CombatAgent(chat_ctx=self.chat_ctx), "Entering combat"
```

### Programmatic Handoff (Code-Driven)

Call `session.update_agent(new_agent)` directly. Best for deterministic transitions
(e.g., creation complete, prologue skipped).

```python
# Player skipped the prologue — switch immediately
session.update_agent(CreationAgent())
```

### Key Properties

- **Each agent gets its own** `instructions`, `tools`, `llm`, `tts`, `stt`.
- **STT stream survives handoffs** — no audio gap on the input side. The STT pipeline
  is detached from the old agent and reattached to the new one without interruption.
- **Chat context does not auto-carry.** You choose: pass `chat_ctx`, truncate, summarize,
  or start fresh. `session.userdata` (our `SessionData`) persists across all handoffs.
- **Draining behavior.** The old agent's buffered speech plays out before the new agent
  starts. For interrupts (prologue skip), stop playback explicitly before handoff.
- **`AgentHandoff` item** is automatically inserted into session history, giving the
  framework visibility into transitions.

## Proposed Agent Architecture

```
PrologueAgent
  │  (programmatic: prologue ends or player skips)
  ▼
CreationAgent  [Sonnet, creation tools only]
  │  (programmatic: finalize_character completes)
  ▼
OnboardingAgent  [Haiku, city tools + scripted beats]
  │  (programmatic: onboarding objectives complete)
  ▼
┌──────────────────────────────────────────────────────┐
│              Gameplay-Type Agents                     │
│                                                      │
│  CityAgent ◄──► WildernessAgent ◄──► DungeonAgent   │
│     │                │                    │           │
│     └───────────┬────┘────────────────────┘           │
│                 │                                     │
│                 ▼                                     │
│           CombatAgent                                │
│                 │                                     │
│                 ▼                                     │
│       (returns to previous gameplay agent)            │
└──────────────────────────────────────────────────────┘
```

Gameplay-type agents replace the generic `ExplorationAgent`. Each agent is tuned
for a distinct *mode of play*, not a specific quest or location. Quests and scenes
inject narrative context into whichever gameplay agent is active — the agent
provides the *how* (tools, pacing, tone), the scene provides the *what* (objectives,
beats, NPC focus).

The handoff between gameplay-type agents is **programmatic, triggered by
`move_player`**. When the player moves to a location in a different region type,
the system hands off to the appropriate agent. Movement within the same region type
stays on the current agent.

### PrologueAgent

**Purpose:** Play the prologue audio. No LLM needed.

- **Tools:** None (audio playback only).
- **Transition:** Programmatic handoff to `CreationAgent` when audio finishes or player
  speaks (skip).
- **On skip:** Stop audio playback, then `session.update_agent(CreationAgent())`.
  STT survives, so the player's "skip" utterance doesn't get lost.

This is the simplest agent — it doesn't even need an LLM. It just manages audio
playback and listens for voice activity as an interrupt signal.

### CreationAgent

**Purpose:** Guide character creation through five phases (awakening, calling,
devotion, identity, finalize).

- **Model:** Claude Sonnet (creative, patient guidance).
- **Tools:** `push_creation_cards`, `set_creation_choice`, `finalize_character`,
  `play_sound`, `set_music_state`.
- **System prompt:** `CREATION_SYSTEM_PROMPT` only. No gameplay rules, no world
  context, no navigation instructions.
- **Transition:** When `finalize_character` succeeds, it returns `OnboardingAgent`
  with a summarized chat context (race, class, deity, name, backstory choices —
  everything the next agent needs to narrate the transition).

The creation agent never sees combat tools, location queries, or quest state. Its
prompt is small and focused.

### OnboardingAgent

**Purpose:** Guide the player through their first 10-15 minutes of gameplay with
reliable, structured narrative beats.

This is the key new agent — it solves the "dropped in the market with nothing
happening" problem. It has a scripted sequence of beats that it drives the player
through, while still allowing natural conversation and exploration within each beat.

- **Model:** Claude Haiku.
- **Tools:** City-appropriate tools (`enter_location`, `query_location`, `query_npc`,
  `move_player`, `request_skill_check`, `play_sound`, `set_music_state`,
  `discover_hidden_element`, `record_story_moment`). No combat tools — combat
  doesn't happen during onboarding. No wilderness/dungeon tools.
- **System prompt:** Focused onboarding instructions with the scripted beat sequence.
- **Background process:** Active, but with onboarding-specific event logic.

The onboarding agent is essentially a specialized `CityAgent` with a rigid beat
sequence. After onboarding completes, it hands off to a standard `CityAgent` — the
player is still in the Accord, just no longer on rails.

#### Onboarding Beat Sequence

The onboarding agent drives a fixed sequence of narrative beats. Each beat has a
trigger condition and completion condition. The agent narrates naturally within each
beat but reliably advances through them.

```
Beat 1: Arrival
  The mist clears. The player materializes in the Market Square of the
  Accord of Tides. Evening. Sensory-first description. End with an
  invitation to look around.
  ─ Completes: After initial narration delivered.

Beat 2: The Market
  The player explores the market square. Ambient life, vendors, sounds.
  The agent responds to player exploration naturally. Hidden perception
  check on the guild noticeboard (DC 10) — if noticed, plants the seed
  of Greyvale.
  ─ Completes: After 2-3 player exchanges OR player attempts to leave.

Beat 3: Companion Meeting
  A commotion erupts. Vendor being hassled. Kael is watching, hesitating.
  Player decides whether to intervene. Kael joins regardless of approach
  (different flavor based on player action, but same outcome — he's
  joining either way during onboarding).
  ─ Completes: Kael has introduced himself. Companion state initialized.

Beat 4: Kael's Suggestion
  Kael suggests heading to the guild hall or the tavern. Natural
  dialogue, not a menu. He mentions hearing about trouble up north
  (Greyvale seed). If the player already noticed the noticeboard,
  Kael reinforces it.
  ─ Completes: Player indicates a direction or asks Kael to lead.

Beat 5: First Destination
  Player arrives at their chosen location (guild hall or tavern).
  NPC introduction (Guildmaster Torin or tavern keep). Greyvale quest
  hook delivered through conversation.
  ─ Completes: Greyvale quest accepted OR player has heard the hook.
```

After Beat 5 completes, the onboarding agent hands off to `CityAgent` via
programmatic handoff. The player is still in the Accord, just no longer on rails.
They now have a companion, a quest, and a mental model of how the world works.

**Why a separate agent?** The onboarding beat sequence is rigid enough that it
benefits from a focused prompt. The city agent shouldn't carry "make sure the
player meets Kael" instructions for the entire rest of the game. And the onboarding
agent doesn't need combat tools, quest progression tools, or the full warm layer —
it has a fixed, small world (the market square area).

#### Returning Players

The onboarding agent is only used for first-session players. Returning players who
have already met Kael go directly to the appropriate gameplay-type agent (based on
their saved location) with a recap instruction.

Players who disconnected mid-onboarding resume where they left off. The beat sequence
state is tracked in `SessionData.onboarding_beat` and persisted to the database, so
reconnection can restore the correct beat.

### CityAgent

**Purpose:** Social gameplay in settlements — NPC dialogue, commerce, quest givers,
companion conversations, crafting, rest.

- **Model:** Claude Haiku.
- **Tools:** `enter_location`, `query_location`, `query_npc`, `move_player`,
  `request_skill_check`, `discover_hidden_element`, `update_quest`, `award_xp`,
  `award_divine_favor`, `add_to_inventory`, `remove_from_inventory`,
  `update_npc_disposition`, `query_inventory`, `query_lore`, `record_story_moment`,
  `play_sound`, `set_music_state`, `end_session`.
- **System prompt:** Social/exploration rules, NPC dialogue guidance, companion
  prompt, warm layer. No combat rules, no survival mechanics.
- **Narration style:** Warm, detailed, conversational. Room for NPC banter, ambient
  city life, overheard conversations.
- **Warm layer rendering:** Emphasizes NPCs present and their dispositions, social
  context, commerce availability. De-emphasizes corruption and hazards.
- **Background process:** Full warm layer rebuilds, proactive companion speech,
  world news events, god whispers.
- **Transition out:** `move_player` to a wilderness or dungeon location triggers
  programmatic handoff. The CityAgent narrates the departure ("The market noise
  fades behind you. The road stretches north.") before handing off. `start_combat`
  (if city combat is possible — bar fights, ambushes) returns `CombatAgent`.

**Locations:** `accord_market_square`, `accord_guild_hall`, `accord_temple_row`,
`accord_dockside`, `accord_hearthstone_tavern`, `accord_forge`, `emris_study`,
`torin_quarters`, `millhaven`, `millhaven_inn`.

Millhaven is classified as city-type despite being a small town — it has NPCs, an
inn, a quest giver (Yanna), and social interactions. The difference from the Accord
is atmosphere (foreboding, isolated), not mode of play. The warm layer handles this
via location-specific atmosphere data.

### WildernessAgent

**Purpose:** Travel, exploration, and encounters in open terrain — roads, forests,
fields.

- **Model:** Claude Haiku.
- **Tools:** `enter_location`, `query_location`, `move_player`,
  `request_skill_check`, `discover_hidden_element`, `update_quest`, `roll_dice`,
  `start_combat`, `query_inventory`, `query_lore`, `record_story_moment`,
  `play_sound`, `set_music_state`.
- **System prompt:** Travel pacing, encounter rules, environmental hazards,
  survival-flavored narration. Companion prompt (Kael is especially active during
  travel — pointing things out, sharing stories, warning about danger).
- **Narration style:** Paced, atmospheric, tension-aware. Longer descriptions of
  landscape, weather, distance. Sound and smell dominate over sight (traveling
  eyes-closed).
- **Warm layer rendering:** Emphasizes distance/terrain, encounter readiness,
  weather, corruption level. De-emphasizes NPC social context.
- **Background process:** Random encounter checks, travel events, corruption
  monitoring, companion travel chatter.
- **Transition out:** `move_player` to a city location triggers handoff to
  `CityAgent`. `move_player` to a dungeon entrance triggers handoff to
  `DungeonAgent`. The WildernessAgent narrates the departure before handing off.
  `start_combat` (encounter) returns `CombatAgent`.

**Locations:** `greyvale_south_road`, `greyvale_wilderness_north`, `northern_fields`,
and future road/travel locations.

### DungeonAgent

**Purpose:** Dungeon crawling — traps, puzzles, hidden elements, tension, and
careful exploration in enclosed spaces.

- **Model:** Claude Haiku.
- **Tools:** `enter_location`, `query_location`, `move_player`,
  `request_skill_check`, `request_saving_throw`, `discover_hidden_element`,
  `update_quest`, `start_combat`, `roll_dice`, `query_inventory`, `add_to_inventory`,
  `query_lore`, `record_story_moment`, `play_sound`, `set_music_state`.
- **System prompt:** Dungeon exploration rules, trap/puzzle handling, hidden element
  emphasis, Hollow corruption guidance (dungeons are where corruption is highest).
  Companion prompt adjusted — Kael is nervous, alert, speaks in whispers.
- **Narration style:** Terse, tense, sensory-heavy. Short sentences. Echo and
  dripping water. Every sound matters. The Hollow breaks rules here.
- **Warm layer rendering:** Emphasizes corruption level and sensory effects, hidden
  elements and proximity hints, exits and access requirements. De-emphasizes social
  context and commerce.
- **Background process:** Corruption effects, ambient dungeon events, companion
  anxiety escalation, hidden element proximity hints.
- **Transition out:** `move_player` to exterior triggers handoff to
  `WildernessAgent`. The DungeonAgent narrates the departure ("Light. Air. The
  weight of stone lifts from your shoulders.") before handing off. `start_combat`
  returns `CombatAgent`.

**Locations:** `greyvale_ruins_entrance`, `greyvale_ruins_inner`,
`hollow_incursion_site`, and future dungeon/cave locations.

### CombatAgent

**Purpose:** Run a combat encounter from initiative to resolution.

- **Model:** Claude Haiku.
- **Tools:** `request_attack`, `resolve_enemy_turn`, `request_saving_throw`,
  `request_death_save`, `end_combat`, `roll_dice`, `play_sound`, `set_music_state`,
  `query_inventory` (for item use mid-combat).
- **System prompt:** `COMBAT_PROMPT` only. Staccato narration style, initiative
  tracking, HP descriptions. No exploration context, no NPC dialogue rules.
- **Transition:** `end_combat` returns the **previous gameplay-type agent** (tracked
  in `SessionData.pre_combat_agent_type`) with combat results summarized in the
  chat context. A fight in a dungeon returns to `DungeonAgent`. A fight on the road
  returns to `WildernessAgent`.

Combat is the clearest handoff boundary. The agent's personality changes (terse,
urgent), the available actions change completely, and the prompt rules are entirely
different.

### Gameplay-Type Agent Selection

The system needs a mapping from location to agent type. This can live on the
location data itself:

```python
REGION_TYPE = {
    # Accord of Tides — city
    "accord_market_square": "city",
    "accord_guild_hall": "city",
    "accord_temple_row": "city",
    "accord_dockside": "city",
    "accord_hearthstone_tavern": "city",
    "accord_forge": "city",
    "emris_study": "city",
    "torin_quarters": "city",
    # Millhaven — small town, still city-type
    "millhaven": "city",
    "millhaven_inn": "city",
    # Wilderness
    "greyvale_south_road": "wilderness",
    "greyvale_wilderness_north": "wilderness",
    "northern_fields": "wilderness",
    # Dungeons
    "greyvale_ruins_entrance": "dungeon",
    "greyvale_ruins_inner": "dungeon",
    "hollow_incursion_site": "dungeon",
}
```

Or better, add a `region_type` field to each location in `locations.json`. The
`move_player` tool checks whether the destination's region type differs from the
current agent type. If it does, the tool triggers a handoff instead of just
updating `SessionData.location_id`.

### Warm Layer Architecture

The background process maintains raw game state (location, NPCs, quests, companion,
corruption) as a shared data structure — the same as today. Each gameplay-type agent
has its own `render_warm_layer()` method that selects and formats the pieces it cares
about. The background process doesn't need to know which agent is active; it just
keeps the data fresh. The active agent pulls from it and renders on each turn.

### Reconnection

When a player disconnects and reconnects, the database determines which agent to
dispatch. Check in order:

1. Active combat state → `CombatAgent`
2. Onboarding incomplete → `OnboardingAgent`
3. Otherwise → gameplay agent matching the player's current location's `region_type`

The existing 2-minute reconnection grace period stays. If the player reconnects
within the window, the existing session/agent resumes without re-dispatch.

## Context Transfer Strategy

Each handoff needs a deliberate context strategy. `SessionData` on `session.userdata`
persists automatically. The question is what to do with `chat_ctx`.

Handoffs reset prompt caching, but gameplay-type transitions are infrequent (1-3 per
session). The per-turn savings from smaller, focused prompts across dozens of turns
outweigh the cache loss on transitions. Measure after shipping, don't optimize upfront.

| Handoff | Context Strategy |
|---|---|
| Prologue → Creation | Fresh context. No conversation happened. |
| Creation → Onboarding | Summary message: "Player created a [race] [class] devoted to [deity], named [name]. Backstory: [backstory]." Small, focused. |
| Onboarding → CityAgent | Truncated context (last 6-8 messages). Player's first interactions, Kael introduction, quest hook. |
| City → Wilderness | Summary of recent city interactions + active quest state. Companion memory carries over via `SessionData`. The warm layer rebuilds with wilderness context. |
| Wilderness → Dungeon | Truncated context (last 6-8 messages). The player's approach to the dungeon and any recent companion dialogue. |
| Dungeon → Wilderness | Summary: location explored, items found, discoveries made. Fresh wilderness context. |
| Any gameplay → Combat | Pass full recent context. The LLM needs to know what led to combat. Truncate to last 10 messages. |
| Combat → previous agent | Summary: "Combat resolved. [outcome]. [XP awarded]. [notable moments]." Start fresh context with summary on the returning gameplay agent. |

## Structured Play: Scenes and Play Trees

### The Scene Abstraction

A **scene** is a unit of structured gameplay with defined entry conditions, available
tools, narrative beats, and exit conditions. Scenes sit between the rigid beat
sequence of onboarding and the open-world freedom of exploration.

```python
@dataclass
class Scene:
    id: str
    name: str
    region_type: str                   # city | wilderness | dungeon
    instructions: str                  # scene-specific prompt injection
    entry_conditions: dict             # what triggers this scene
    completion_conditions: dict        # what ends this scene
    on_complete: dict                  # effects to apply (XP, items, flags)
    beats: list[SceneBeat] | None      # optional scripted beat sequence
    stage_refs: list[int]              # which quest stages this scene covers
```

Scenes are authored in `quests.json` as a `scenes` array on each quest, wrapping
the existing `stages`. Each scene references one or more stages via `stage_refs`,
adds beats and companion hints, and declares its `region_type`. The existing quest
progression logic (`update_quest`, stage advancement) still works — scenes are a
layer on top, not a replacement.

Scenes are useful for:
- **Quest-critical moments** that need reliable pacing (discovering the ruins,
  first Hollow encounter, confronting an NPC).
- **Scripted narrative events** that shouldn't be left to open-world LLM improvisation
  (the rider scene, god whispers, companion backstory reveals).
- **Tutorials** that teach game mechanics (first skill check, first combat, first
  crafting session).

### Play Trees

A **play tree** is a directed graph of scenes that represents a quest line or
narrative arc. Each node is a scene. Edges represent transitions with conditions.

```
                    ┌─────────────────┐
                    │  Road to        │
                    │  Millhaven      │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │  Millhaven      │
                    │  Investigation  │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │  First Hollow   │
                    │  Encounter      │◄── triggers CombatAgent handoff
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │  Ruins          │
                    │  Exploration    │
                    └───┬─────────┬───┘
                        │         │
              ┌─────────▼──┐  ┌──▼─────────┐
              │ Keep        │  │ Show        │
              │ Artifact    │  │ Companion   │
              └─────────┬───┘  └───┬─────────┘
                        │          │
                    ┌───▼──────────▼───┐
                    │  Return to       │
                    │  Accord          │
                    └──────────────────┘
```

Play trees don't remove player agency — they structure the *available* narrative
beats so the DM agent doesn't have to improvise quest pacing from scratch. The player
can still wander off, explore side content, or ignore the quest. But when they engage
with the quest line, the tree ensures reliable progression.

### Integration with Agent Handoffs

Play trees and gameplay-type agents work together naturally. Each scene in a play
tree has an expected `region_type` that determines which agent handles it:

- "Road to Millhaven" → `WildernessAgent` with scene instructions injected.
- "Millhaven Investigation" → `CityAgent` with scene instructions injected.
- "First Hollow Encounter" → `CombatAgent` (handoff from `WildernessAgent`).
- "Ruins Exploration" → `DungeonAgent` with scene instructions injected.

The scene provides narrative context (objectives, beats, NPC focus, companion hints).
The gameplay-type agent provides the mode of play (tools, pacing, narration style).
This is why quest-specific agents aren't needed — the scene system and the agent
type system are orthogonal layers that compose cleanly.

When the player progresses through a play tree, the scene transitions may or may not
align with agent transitions. Moving from "Millhaven Investigation" to "First Hollow
Encounter" is both a scene change AND an agent handoff (city → wilderness → combat).
But moving from "Arrive at Millhaven" to "Millhaven Investigation" is just a scene
change within the same `CityAgent`.

The active gameplay agent checks the current scene's completion conditions on each
turn. When conditions are met, it advances the play tree and loads the next scene's
instructions. If the next scene requires a different agent type, the current agent
triggers a handoff.

### Companion as Guide

The companion (Kael) is the designed mechanism for hinting at play tree progression.
Each scene in a play tree can define companion hints:

```python
@dataclass
class SceneBeat:
    id: str
    description: str
    completion_condition: str
    companion_hints: list[str]     # what Kael says if the player seems stuck
    hint_delay_seconds: int        # how long to wait before hinting
```

The background process monitors scene progress and delivers companion hints after
a configurable delay. This replaces the current `global_hints` / `stuck_stage_N`
system in `quests.json` with something that's structurally integrated into the
agent's behavior rather than being informational context the LLM may or may not act
on.

## LiveKit Rooms as Shared Spaces

> This section captures architectural thinking for multiplayer. It is not part of
> the handoff refactor.

### What Rooms Add Beyond Agent Handoffs

Gameplay-type agents (CityAgent, WildernessAgent, DungeonAgent) already solve the
single-player problems that rooms were originally envisioned for: per-region tools,
narration style, prompt focus, and audio boundaries. Agent handoffs within a single
room give us all of that without room transfer latency or infrastructure complexity.

What rooms provide that agent handoffs cannot is **shared space**. A room is a
multiplayer concept — it's the thing that lets two players hear the same DM narrate
the same event in the same location.

### Multiplayer Room Model

```
Room: "accord_market_square"
  ├── Player A (participant)
  ├── Player B (participant)
  └── CityAgent instance (agent participant)
      ├── voices all NPCs at this location
      ├── narrates shared events to all participants
      ├── handles individual player actions via data channels
      └── runs with city-type tools, prompt, and narration style
```

Player movement between locations = LiveKit room transfer. The destination room
already has (or spins up) the correct gameplay-type agent. The agent type is
determined by the room's region type, not by the player's session state.

**What rooms give multiplayer:**
- Players in the same location hear shared narration for shared events (a market
  commotion, a Hollow incursion, an NPC announcement).
- Individual actions are handled via per-player data channels. Player A asks an
  NPC a question; the response goes to Player A. A Hollow attack on the market
  is narrated to everyone.
- PvP interactions happen naturally — both players are in the same room, the
  agent mediates.
- Player count per location is visible. The DM agent can narrate "the market is
  crowded today" or "you're alone on the road" based on actual participant count.

**What rooms change architecturally:**
- Agent instances are per-room, not per-player. One CityAgent serves everyone in
  the market square. This is a fundamental shift from the current one-agent-per-
  session model.
- `SessionData` becomes per-player state that the room's agent looks up, not
  agent-owned state on `userdata`. Multiple players = multiple SessionData records
  consulted by one agent.
- Combat in a shared room gets interesting. If Player A starts a fight, does
  Player B see it? Probably yes (shared narration), but Player B's combat actions
  are separate. The CombatAgent may need to be per-player even in a shared room,
  or the room's agent manages a multi-party combat encounter.
- The warm layer becomes room-scoped (location, NPCs present, time of day) plus
  per-player overlays (individual quest state, companion, inventory).

### Tradeoffs

- **Room transfer latency.** The player reconnects to a new room and a new agent
  instance. Acceptable for location changes (narratively significant moments) but
  not for rapid movement. Gameplay-type agent handoffs within a room are instant
  by comparison.
- **Infrastructure complexity.** Each active location needs a running agent instance.
  Idle rooms can be spun down, but scale requires orchestration. The current model
  (one agent per player) scales linearly with players. The room model scales with
  *occupied locations*, which is better at high player counts but worse at low ones.
- **State externalization.** Agent state must live in the database/Redis since room
  agents serve multiple players and can be recycled. This is already the case —
  `SessionData` persists to the DB today.

### Migration Path

1. **Now:** Single room per player session. Gameplay-type agents handle region
   differentiation via handoffs within that room.
2. **Multiplayer (rooms as shared spaces):** Rooms represent locations or regions.
   Players transfer between rooms on movement. Each room runs the appropriate
   gameplay-type agent, now serving multiple players. The agent types, tools,
   and prompts designed in the handoff refactor carry forward directly — a
   `CityAgent` is a `CityAgent` whether it's serving one player or five.

The handoff refactor is designed to be room-topology-agnostic. Whether
`CityAgent` runs inside a per-player room or a shared location room, its tools,
prompt, and narration style are the same. The multiplayer transition adds shared
narration and per-player data channel routing, but doesn't change the agent
definitions themselves.

## Development Milestones

### Milestone H.1 — Base Agent Pattern and CombatAgent Extraction

**Goal:** Establish the multi-agent foundation and prove LiveKit handoffs work by
extracting CombatAgent — the clearest boundary in the system.

**Inputs:** Current monolithic `DungeonMasterAgent` in `apps/agent/agent.py`.

**Deliverables:**
- `BaseGameAgent` class with shared patterns: `SessionData` on `userdata`,
  `on_enter` / `on_exit` lifecycle hooks, common `render_warm_layer()` interface,
  background process attachment point.
- `CombatAgent` class with combat-only tools (`request_attack`, `resolve_enemy_turn`,
  `request_saving_throw`, `request_death_save`, `end_combat`, `roll_dice`,
  `play_sound`, `set_music_state`, `query_inventory`), `COMBAT_PROMPT` as system
  instructions, staccato narration style.
- `start_combat` tool on the monolith agent returns `CombatAgent` via tool-return
  handoff. `end_combat` on `CombatAgent` returns the monolith agent.
- `SessionData.pre_combat_agent_type` field tracks which agent to return to.
- Combat tools removed from the monolith agent's tool list.
- `COMBAT_PROMPT` removed from monolith's system prompt.

**Acceptance criteria:**
- [x] `start_combat` triggers a LiveKit agent handoff — new agent receives combat
      tools, old agent's tools are no longer available.
- [ ] STT stream survives the handoff — player can speak during transition without
      audio loss. *(requires manual playtest)*
- [x] `end_combat` hands back to the monolith agent with a summary in chat context.
- [x] Combat tools are not available outside of `CombatAgent`.
- [x] Existing combat tests pass against the extracted `CombatAgent`.
- [x] `SessionData` persists across the handoff — player state, location, companion
      are intact on return.

**Key references:**
- *This document — CombatAgent, Context Transfer Strategy*
- *LiveKit docs — Agent handoffs, tool-return pattern*

---

### Milestone H.2 — CityAgent Extraction

**Goal:** Extract all settlement gameplay from the monolith into `CityAgent`. After
this milestone, the monolith is gone — `CityAgent` is the primary gameplay agent.

**Inputs:** Milestone H.1 (base agent pattern exists, handoff mechanism proven).

**Deliverables:**
- `CityAgent` class with city-appropriate tools (all current exploration, query,
  quest, inventory, progression, and audio tools minus combat).
- City-specific system prompt: social/exploration rules, NPC dialogue guidance,
  companion prompt. No combat rules.
- City-specific `render_warm_layer()`: emphasizes NPCs, dispositions, social
  context. De-emphasizes corruption and hazards.
- `start_combat` on `CityAgent` returns `CombatAgent`. `end_combat` returns
  `CityAgent` (via `pre_combat_agent_type`).
- Session entry point (`dm_session`) dispatches `CityAgent` instead of the
  monolith for returning players.
- Monolithic `DungeonMasterAgent` removed (creation mode handled separately in
  next milestones).

**Acceptance criteria:**
- [x] A returning player session starts with `CityAgent` and has access to all
      non-combat gameplay tools.
- [x] Combat round-trip works: CityAgent → CombatAgent → CityAgent.
- [x] Warm layer renders city-appropriate context (NPCs, social, quests).
- [x] Background process attaches to `CityAgent` and delivers companion speech,
      world events, warm layer rebuilds.
- [x] System prompt is measurably smaller than the monolith's (no combat rules,
      no creation instructions).
- [x] All existing non-combat gameplay tests pass.

**Key references:**
- *This document — CityAgent, Warm Layer Architecture*

---

### Milestone H.3 — PrologueAgent and CreationAgent Handoff Chain

**Goal:** Extract prologue and character creation into dedicated agents. Wire the
full early-game handoff chain: Prologue → Creation → CityAgent. Eliminate the
session boundary between creation and gameplay.

**Inputs:** Milestone H.2 (CityAgent exists as the gameplay entry point).

**Deliverables:**
- `PrologueAgent` class: no LLM, audio playback only. Listens for voice activity
  as skip signal. Programmatic handoff to `CreationAgent` on completion or skip.
  Stops audio playback before handoff on skip.
- `CreationAgent` class: Sonnet model, creation-only tools
  (`push_creation_cards`, `set_creation_choice`, `finalize_character`,
  `play_sound`, `set_music_state`), `CREATION_SYSTEM_PROMPT` only.
- `finalize_character` returns `CityAgent` via tool-return handoff with a
  summarized chat context (race, class, deity, name, backstory).
- Session entry point dispatches `PrologueAgent` for new players, `CityAgent`
  for returning players. No more separate creation vs. gameplay sessions.
- Creation and first gameplay are one continuous session — player does not need
  to disconnect and reconnect.

**Acceptance criteria:**
- [x] New player flow: PrologueAgent plays audio → CreationAgent guides creation →
      CityAgent starts gameplay. One continuous session, no reconnection required.
- [x] Prologue skip works: player speaks during prologue, audio stops, CreationAgent
      starts immediately. Player's utterance is not lost.
- [x] `finalize_character` transitions smoothly to CityAgent with the player's
      character summary in context.
- [x] CityAgent's first narration references the player's character (race, class,
      deity) — context transfer is working.
- [x] Returning players skip straight to CityAgent with recap instruction.
- [x] Creation tools are not available on CityAgent. Gameplay tools are not
      available on CreationAgent.

**Key references:**
- *This document — PrologueAgent, CreationAgent, Context Transfer Strategy*

---

### Milestone H.4 — OnboardingAgent and Companion Meeting Fix

**Goal:** Build the OnboardingAgent with a scripted beat sequence that guarantees
the player meets Kael, gets oriented, and receives the Greyvale quest hook — all
in their first session.

**Inputs:** Milestone H.3 (creation → gameplay handoff exists).

**Deliverables:**
- `OnboardingAgent` class: Haiku model, city-appropriate tools, scripted beat
  sequence in system prompt.
- Beat tracking in `SessionData.onboarding_beat` (persisted to DB for
  reconnection).
- Five beats implemented: Arrival, The Market, Companion Meeting, Kael's
  Suggestion, First Destination (see Onboarding Beat Sequence in this document).
- Companion Meeting beat: Kael joins reliably regardless of player approach.
  `CompanionState` initialized, `companion_met` flag set.
- `finalize_character` now returns `OnboardingAgent` instead of `CityAgent` for
  new players.
- After Beat 5 completes, programmatic handoff to `CityAgent`.
- Reconnection mid-onboarding: dispatches `OnboardingAgent` at the correct beat.
- Old companion meeting trigger in `background_process.py` removed.

**Acceptance criteria:**
- [x] New player completes creation and enters onboarding — no manual navigation
      required to meet Kael.
- [x] Kael is reliably present after Beat 3, every time.
- [x] Player has the Greyvale quest hook after Beat 5.
- [x] Player can interact naturally within each beat (ask questions, look around)
      without breaking the sequence.
- [x] Disconnect mid-onboarding and reconnect: resumes at the correct beat.
- [x] After onboarding completes, player is on CityAgent with full open-world
      gameplay.
- [x] The old `MEETING_SCENE_INSTRUCTIONS` / `_meeting_triggered` logic is removed.

**Key references:**
- *This document — OnboardingAgent, Onboarding Beat Sequence*

---

### Milestone H.5 — WildernessAgent, DungeonAgent, and Region Handoffs

**Goal:** Build the remaining gameplay-type agents and wire `move_player` to trigger
handoffs on region boundary crossings.

**Inputs:** Milestone H.2 (CityAgent exists with combat handoff working).

**Deliverables:**
- `region_type` field added to each location in `locations.json`
  (`city` | `wilderness` | `dungeon`).
- `WildernessAgent` class: travel pacing, encounter tools, survival narration,
  companion travel chatter. Wilderness-specific `render_warm_layer()`.
- `DungeonAgent` class: trap/puzzle tools, hidden element emphasis, Hollow
  corruption guidance, terse narration. Dungeon-specific `render_warm_layer()`.
- `move_player` refactored: checks destination's `region_type` against current
  agent type. If different, the current agent narrates a departure, then triggers
  programmatic handoff to the destination's agent type.
- `start_combat` on both WildernessAgent and DungeonAgent returns `CombatAgent`.
  `end_combat` returns the correct agent via `pre_combat_agent_type`.
- Reconnection dispatch updated: looks up current location's `region_type` to
  select the correct gameplay agent.

**Acceptance criteria:**
- [x] Moving from `accord_market_square` to `greyvale_south_road` triggers a
      CityAgent → WildernessAgent handoff.
- [x] Moving from `greyvale_wilderness_north` to `greyvale_ruins_entrance` triggers
      WildernessAgent → DungeonAgent handoff.
- [x] Moving from `greyvale_ruins_entrance` back to exterior triggers
      DungeonAgent → WildernessAgent handoff.
- [x] Departure narration is delivered by the outgoing agent before handoff.
- [x] Arrival narration is delivered by the incoming agent after handoff.
- [x] Movement within the same region type (e.g., city to city) does NOT trigger
      a handoff.
- [x] Combat round-trip works from all three gameplay agents.
- [x] Reconnection dispatches the correct agent based on saved location.
- [x] Each agent's warm layer renders region-appropriate context.
- [x] WildernessAgent's system prompt has no NPC commerce rules. DungeonAgent's
      prompt has no social context rules. CityAgent's prompt has no survival rules.

**Key references:**
- *This document — WildernessAgent, DungeonAgent, Gameplay-Type Agent Selection*

---

### Milestone H.6 — Scene and Play Tree Data Model

**Goal:** Build the scene/play-tree layer on top of the existing quest system.
Author the Greyvale quest line as the first structured play tree.

**Inputs:** Milestone H.5 (all gameplay-type agents exist with region handoffs).

**Deliverables:**
- `scenes` array added to quest format in `quests.json`. Each scene has: `id`,
  `name`, `region_type`, `instructions` (prompt injection), `entry_conditions`,
  `completion_conditions`, `on_complete`, `beats` (optional), `stage_refs`.
- `SceneBeat` structure: `id`, `description`, `completion_condition`,
  `companion_hints`, `hint_delay_seconds`.
- Scene-loading logic: gameplay agents check the active quest's current scene
  on each turn and inject its `instructions` into the prompt.
- Scene advancement: when completion conditions are met, advance to the next
  scene. If the next scene's `region_type` differs from the current agent,
  trigger a handoff.
- Greyvale quest line authored as a play tree with 5 scenes:
  1. Road to Millhaven (`wilderness`)
  2. Millhaven Investigation (`city`)
  3. First Hollow Encounter (`wilderness`, triggers combat)
  4. Ruins Exploration (`dungeon`)
  5. Return to Accord (`wilderness` → `city`)
- Each scene has 2-3 beats with companion hints.

**Acceptance criteria:**
- [x] Quest scenes load from `quests.json` and inject instructions into the
      active gameplay agent's prompt.
- [x] Scene transitions advance automatically when completion conditions are met.
- [x] Scene transitions that cross region types trigger agent handoffs.
- [x] Existing `update_quest` tool still works — stage advancement is unchanged.
- [x] Greyvale play tree is authored with all 5 scenes and their beats.
- [ ] A playthrough of the Greyvale arc hits all 5 scenes in order with
      appropriate agent types.

**Key references:**
- *This document — Scenes and Play Trees, Integration with Agent Handoffs*

---

### Milestone H.7 — Companion Hints in Scenes

**Goal:** Wire companion hint delivery into the scene/beat system, replacing the
current `global_hints` mechanism.

**Inputs:** Milestone H.6 (scene/play-tree data model exists with authored
Greyvale scenes).

**Deliverables:**
- Background process monitors active scene's beat progression. When the player
  appears stuck (configurable delay per beat via `hint_delay_seconds`), delivers
  the beat's `companion_hints` via Kael's voice.
- Hint delivery uses existing companion speech pipeline (`SpeechPriority`-based
  queuing).
- `global_hints` / `stuck_stage_N` fields in `quests.json` removed. All hint
  content lives in scene beats.
- Hint suppression: if the player is actively speaking or the agent is mid-
  narration, delay the hint. Don't interrupt.

**Acceptance criteria:**
- [ ] Player sits idle during a scene beat for the configured delay — Kael
      delivers a contextual hint.
- [ ] Hints are specific to the current beat, not generic quest-level hints.
- [ ] Hints don't interrupt active speech (player or agent).
- [ ] Multiple hints per beat are delivered sequentially with escalating
      specificity if the player remains stuck.
- [ ] `global_hints` fields are removed from `quests.json`.
- [ ] A full Greyvale playthrough with deliberate pauses triggers appropriate
      companion hints at each beat.

**Key references:**
- *This document — Companion as Guide*

---

### Milestone H.8 — End-to-End Playtest and Polish

**Goal:** Play through the complete flow — prologue through Greyvale arc — and
fix issues that surface. Validate the full handoff chain works as a cohesive
experience.

**Inputs:** All previous milestones (H.1-H.7).

**Deliverables:**
- Full playthrough notes documenting every handoff, narration transition, and
  scene beat.
- Bug fixes for issues found during playthrough (narration gaps, context loss,
  tool availability errors, companion timing issues).
- Narration transition polish: departure/arrival text tuned for each agent-type
  boundary crossing.
- Cost measurement: compare per-turn token usage before and after the refactor.
  Document findings.
- Updated `dev_milestones.md` with handoff milestone checkboxes.

**Acceptance criteria:**
- [ ] Complete new-player flow works: Prologue → Creation → Onboarding → CityAgent
      → WildernessAgent → CombatAgent → WildernessAgent → DungeonAgent → CityAgent.
- [ ] Returning player flow works: dispatches correct agent based on saved state.
- [ ] Reconnection works from every agent type.
- [ ] No narration gaps or dead air during handoffs.
- [ ] Companion is reliably present after onboarding and provides hints during
      the Greyvale arc.
- [ ] Per-turn token usage is equal to or lower than pre-refactor baseline.

