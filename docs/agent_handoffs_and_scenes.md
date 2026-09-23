# Agent Handoffs, Scenes, and Structured Play

The shipped agent flow uses LiveKit handoffs for changes in play mode. Location changes
update the Stage held by `ExplorationAgent`; they do not switch region agents.
`BaseGameAgent` supplies shared lifecycle and session behavior.

## Agent flow

```text
PrologueAgent → CreationAgent → OnboardingAgent → ExplorationAgent
                                             ExplorationAgent ↔ CombatAgent
                                             ExplorationAgent ↔ DispatchAgent
                                             ExplorationAgent ↔ BlacksmithAgent
```

`PrologueAgent` plays opening audio and hands off to `CreationAgent` when it ends or
the player skips it. `CreationAgent` handles character choices; `finalize_character`
returns `OnboardingAgent` with a character summary in chat context. Onboarding guides
the first meeting and then hands off to `ExplorationAgent`. Returning players enter
exploration with a recap. `SessionData` remains on the LiveKit session across handoffs.

### ExplorationAgent

One agent handles settlement, travel, and dungeon exploration. The location's Stage
supplies nearby people, affordances, hazards, and quest context; its `region_type`
changes with movement. `move_player` changes location without an agent handoff.
The common verb set includes `enter_location`, `query_info`, `check`, `move_player`,
`travel`, `transact`, `update_quest`, `update_npc_disposition`,
`adjust_faction_reputation`, `record_story_moment`, `end_session`, `activate`,
`select`, and `enter_mode`.

`enter_mode` hands off for combat, dispatch, or blacksmith work. These focused agents
have their own tools and return to exploration on completion. The session background
process persists through mode handoffs.

### CombatAgent

Combat uses its own prompt and this registered tool list:

- **Tools:** `declare_phase`, `resolve_phase`, `consume_legendary_action`, `check`, `request_death_save`, `end_combat`, `query_info`, `activate`, `get_spell_info`.
- **Transition:** `enter_mode` starts combat; `end_combat` returns an `ExplorationAgent` with the encounter outcome.

### DispatchAgent and BlacksmithAgent

These mode agents handle dispatch and forge interactions with focused toolsets.
They return to `ExplorationAgent` when the mode ends. Their tool registrations,
not location type, define the available actions.

## Context transfer and reconnection

Tool-return handoffs pass the chosen chat context while `SessionData` persists on
`session.userdata`. Creation sends a character summary to onboarding. Mode handoffs
carry recent context and the session state needed for a return to exploration.
On reconnection, startup uses saved creation, onboarding, combat, and location state
to choose an agent. Region changes within exploration rebuild location context.

## Scenes and structured play

Quest stages and scene records supply narrative instructions, objectives, and beats
to the active Stage. `scene_tools.py` resolves the active scene from the quest graph;
`background_process.py` checks scene beat hints. Scene changes in city, wilderness,
or dungeon remain with `ExplorationAgent`. Combat scenes use `CombatAgent` through
`enter_mode`. The earlier proposal for a separate region agent per scene was retired.

## LiveKit rooms and multiplayer

Rooms connect participants and the voice agent. The design for a shared location room,
with one agent serving several players, remains a multiplayer proposal. The current
session keeps player state on `SessionData` and uses agent handoffs for play modes.

## Development Milestones

These milestones record the original plan and its shipped outcome. Checkboxes in the
old plan described the implementation at the time; the current classes and flows
below supersede them.

### Milestone H.1 — Base agent and combat extraction

The monolithic `DungeonMasterAgent` became `ExplorationAgent` for gameplay.
`BaseGameAgent` supplies common behavior; `CombatAgent` handles encounters.
Combat's tool-return handoff and session state persisted through the split.

### Milestone H.2 — Settlement gameplay extraction

`CityAgent` first held settlement gameplay. It was folded into `ExplorationAgent`,
which now handles settlements and other regions with one verb set and location Stage.
Combat returns to `ExplorationAgent`.

### Milestone H.3 — Prologue and creation chain

`PrologueAgent` and `CreationAgent` split opening audio and character creation from
the old `DungeonMasterAgent`, whose gameplay role became `ExplorationAgent`.
Character finalization now enters `OnboardingAgent` before exploration.

### Milestone H.4 — Onboarding and companion meeting

`OnboardingAgent` guides the first session and hands off to `ExplorationAgent`.
Onboarding beat state supports continuation after reconnection; companion meeting
belongs to that guided flow.

### Milestone H.5 — Region handoffs

The planned `WildernessAgent`, `DungeonAgent`, and `CityAgent` became `ExplorationAgent`. `region_type` and Stage content supply local
context. `move_player` updates location without switching agent classes.

### Milestone H.6 — Scene and play tree data

Scene records and quest stage mapping shipped through scene lookup and Stage context.
The proposed agent handoffs at scene region boundaries became Stage changes inside
`ExplorationAgent`; combat still hands off to `CombatAgent`.

### Milestone H.7 — Companion hints in scenes

Scene beat hints shipped in the background process. It reads the active beat's
`companion_hints` and `hint_delay_seconds` and delivers hints through the companion
speech path. This is independent of region agent selection.

### Milestone H.8 — Playtest and polish

The shipped flow is `PrologueAgent` → `CreationAgent` → `OnboardingAgent` →
`ExplorationAgent`, with `CombatAgent` for encounters. This milestone's historical
playthrough and latency aspirations are not a claim that every live experience has
been manually validated.
