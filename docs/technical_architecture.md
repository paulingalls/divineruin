# Divine Ruin: The Sundered Veil — Technical Architecture

## About This Document

This document defines the technical architecture for building the MVP of Divine Ruin: The Sundered Veil. It covers the client application, voice pipeline, DM agent architecture, orchestration, infrastructure, AI systems, autonomous agents, multiplayer architecture, and development priorities. It is informed by the *MVP Specification* and *Game Design* documents.

**Last research update:** February 25, 2026

---

## Architecture Overview

The system has seven major layers:

1. **Client Layer** — Expo React Native app: voice connection, HUD, audio mixing, session management
2. **Transport Layer** — LiveKit for real-time voice; LiveKit data channels for server-pushed UI events
3. **Voice Pipeline** — Deepgram STT → Claude LLM → Inworld TTS, managed by the DM agent
4. **Game Engine** — Rules engine, world state (PostgreSQL + Redis), session management
5. **Agent Layer** — DM agent, background process, god-agents, world simulation
6. **Multiplayer Layer** — Multi-player rooms, input arbitration, shared DM
7. **Data Layer** — Content DB (JSON entity schemas), state DB, Redis hot cache

---

## Client Architecture — Expo React Native

### Design Philosophy

The client is thin by design. All game intelligence — narration, rules, world simulation, NPC behavior — lives server-side. The client's job is to be a reliable voice connection with a glanceable HUD bolted on. This keeps the app lightweight, fast to load, and cheap to maintain. The interaction model is closer to a podcast app with an overlay than a traditional game client.

The player's primary interface is their voice and their ears. The screen is secondary — a smartwatch-pattern glance surface for moments when visual context enriches the audio experience.

### Platform and Framework

**Expo (React Native)** — Single codebase targeting iOS and Android. Expo's managed workflow handles builds, OTA updates, and native module linking. Key dependencies:

- **@livekit/react-native** — LiveKit's React Native SDK for WebRTC voice transport. Handles room connection, audio track management, data channel messaging, and RPC.
- **expo-av** or **react-native-audio-api** — Audio playback for ambient soundscapes, sound effects, and UI audio. Needs multi-track simultaneous playback with independent volume control. `expo-av` supports this but has limitations on simultaneous streams; `react-native-audio-api` (Web Audio API polyfill) may be needed for proper mixing. Evaluate both during prototyping.
- **react-native-reanimated** — Smooth 60fps animations for dice rolls, combat UI transitions, item card popups, HP bar changes. Runs animations on the native UI thread.
- **react-native-mmkv** — Fast local key-value storage for cached game state, character data, map progress. Synchronous reads, faster than AsyncStorage.
- **zustand** — Lightweight state management. The state shape is simple and mostly server-driven. Zustand stores for: session state, player state, combat state, UI overlay state, audio state.
- **expo-router** — File-based navigation.
- **expo-haptics** — Tactile feedback for dice rolls, critical hits, level-ups.

### Screen Map

The app has a small screen count. Most gameplay happens on the Active Session screen with contextual overlays.

**Pre-Session Screens:**

- **Auth** — Sign in / sign up. Minimal — get the player into the game fast.
- **Home** — Session resume button (prominent), async activity cards, character summary bar, session history. If no character exists, flows into character creation.
- **Character Creation** — A voice conversation with visual assists. The DM speaks through the LiveKit connection; the client shows contextual cards (race options, class options, patron options) when the server pushes them. The player speaks their choices. Not a form — a conversation with illustrations.

**Active Session (the core experience):**

- **Session Screen** — Full-screen with layered HUD overlays. This is where the player spends 95% of their time. The background is atmospheric (dark, ambient-lit, matching the current environment's mood — not a literal scene render). The foreground is the HUD system described below.
- **Map (pull-up)** — Player-initiated. 2D top-down map that fills in as you explore. Current location marker, breadcrumb trail, points of interest, quest objective indicators. Canvas-rendered or SVG. Swipe down to dismiss, back to session.
- **Character Sheet (pull-up)** — Stats, abilities, equipment, divine favor. Read from local cache, updated by server pushes.
- **Inventory (pull-up)** — Items with rarity indicators. Tap for detail card. Managed locally, synced by server.
- **Quest Log (pull-up)** — Active quests, stages, hints. Updated by `update_quest` server pushes.

**Utility Screens:**

- **Settings** — Audio levels (voice, ambience, effects, music), mic mode (VAD vs. tap-to-speak), notification preferences, account.
- **Async Hub** — Between-session activities: crafting timers, training progress, god whisper inbox, party messages. Lighter UI — text + short audio clips, not a full LiveKit session.

### HUD System — Layered Overlays

The HUD is not a traditional game UI. It's a system of overlays that appear contextually and auto-dismiss, designed for glance-and-return interaction. Three layers, from always-visible to player-initiated:

**Layer 1 — Persistent Bar (always visible during session)**

A thin strip at the top or bottom of the session screen. Contains:
- HP bar (compact, color-coded: green → yellow → red)
- Active status effect icons (poisoned, blessed, etc.)
- Mic state indicator (listening / processing / idle)
- Subtle DM-is-speaking indicator (a soft glow or waveform)

Footprint: <10% of screen height. The player should be able to ignore it entirely during normal play and glance at it when they hear a health-low audio cue.

**Layer 2 — Contextual Overlays (server-pushed, auto-dismiss)**

These appear when the server pushes relevant events and disappear after a timeout or player dismissal. They're the "glance down, absorb, go back to listening" moments.

- **Dice roll animation** — Appears when mechanics tools resolve. Shows the die, the roll, the modifier, and the result (hit/miss, success/fail). Distinct audio cue accompanies it. Auto-dismisses after 3-4 seconds. Driven by the `narrative_hint` field from tool results.
- **Combat tracker** — Appears when combat starts (pushed by combat state tools). Shows turn order, enemy HP bars, active status effects. Stays visible during combat, auto-dismisses on combat end. Updated in real-time by `update_combat_ui` pushes.
- **Item card** — Pops when the player receives an item (pushed by `add_to_inventory`). Shows item name, rarity border, brief description, key stats. Auto-dismisses after 5 seconds or on tap.
- **Quest update toast** — Brief notification when a quest advances (pushed by `update_quest`). "Quest Updated: The Greyvale Anomaly — Stage 3." Auto-dismisses after 3 seconds.
- **XP / Level-up notification** — Pushed by `award_xp`. XP gains are subtle toasts. Level-ups get a larger, more celebratory overlay with haptic feedback.
- **Character creation cards** — During character creation, the server pushes visual option cards (race illustrations, class descriptions, patron sigils) that appear as a horizontally scrollable row. The player speaks their choice; the selected card highlights and the rest dismiss.

**Layer 3 — Pull-Up Screens (player-initiated)**

The Map, Character Sheet, Inventory, and Quest Log. Accessed by a gesture (swipe up from bottom, or tap a persistent bar icon). These slide over the session screen as a modal. The voice connection stays active — the player can keep talking to the DM while browsing their inventory. Swiping down or tapping a close button returns to the session screen.

### Data Flow

The client is **reactive, not requesting.** It doesn't poll for game state. All updates flow from server to client via LiveKit data channels.

```
Server → Client (push):
  LiveKit audio track     → DM voice playback
  LiveKit data channel    → Game state events (JSON payloads)
    ├── combat_ui_update  → Combat tracker overlay
    ├── item_acquired     → Item card popup
    ├── dice_result       → Dice animation overlay
    ├── quest_update      → Quest toast + quest log cache
    ├── xp_awarded        → XP toast (+ level-up overlay)
    ├── location_changed  → Map update + ambience crossfade
    ├── status_effect     → Persistent bar icon update
    ├── sound_effect      → Sound effect playback
    ├── creation_cards    → Character creation option cards
    └── session_event     → Session start/end/reconnect UI

Client → Server (voice + explicit actions):
  LiveKit audio track     → Player voice (VAD-gated)
  LiveKit RPC             → start_turn (tap-to-speak mode)
  LiveKit RPC             → session_start / session_end
  HTTPS (REST)            → Auth, async activity actions, settings
```

**Local state cache:** The client maintains a local copy of character data, inventory, quest log, and map progress in MMKV. This cache is populated on session start (server pushes full state) and kept current by incremental server pushes during the session. Pull-up screens read from cache, so they open instantly — no loading spinners.

**Async activities** don't use LiveKit. They're standard HTTPS requests to a REST API. The async hub screen fetches current activity states, displays timers and results, and lets the player make decisions. If an async activity includes a short voiced scene (e.g., a god whisper), the server returns a pre-rendered audio URL that the client plays back — not a real-time voice session.

### Audio Mixing Architecture

The client manages four independent audio channels, mixed locally:

| Channel | Source | Volume Control | Notes |
|---|---|---|---|
| **Voice** | LiveKit audio track | Master + voice slider | DM narration, NPC dialogue, all character voices. Always highest priority. |
| **Ambience** | Local audio files | Master + ambience slider | Environmental soundscapes: tavern bustle, forest wind, rain, combat tension layer. Triggered by `location_changed` and `sound_effect` events. Crossfades on transitions (1-2 second linear fade). |
| **Effects** | Local audio files | Master + effects slider | One-shot sounds: sword clash, spell cast, door creak, divine presence. Triggered by `play_sound` server events. Fire-and-forget, can overlap. |
| **UI Audio** | Local audio files | Master + UI slider | Dice roll sounds, notification chimes, level-up fanfare, menu interactions. Triggered by client-side events (overlay appearance, user actions). |

**Ducking:** When the Voice channel is active (DM is speaking), Ambience ducks to ~40% volume automatically. Effects play at full volume over both (they're brief and add to the scene). UI Audio plays at full volume (it's informational).

**The critical constraint:** Voice is a WebRTC audio track from LiveKit. Ambience, Effects, and UI Audio are local playback. These are separate audio systems on the device. The audio session category on iOS must be configured for `.playAndRecord` with `.mixWithOthers` and `.duckOthers` options. On Android, the AudioManager focus strategy must allow concurrent streams. This is well-trodden territory for podcast and music apps, but it needs to be configured correctly from the start or it creates hard-to-debug audio issues.

**Ambient sound library:** A set of loopable audio files bundled with the app (or downloaded on first launch). Organized by environment tag matching the location schema's `ambient_sounds` field. Examples: `tavern_busy.mp3`, `forest_calm.mp3`, `rain_heavy.mp3`, `combat_tension.mp3`, `hollow_wrongness.mp3`. The server's `location_changed` event includes the ambient sound tag; the client crossfades to the matching file.

**Sound effect library:** One-shot audio files, also bundled or downloaded. Named to match the `play_sound` tool's `effect_name` parameter: `sword_clash.mp3`, `critical_hit_sting.mp3`, `spell_cast_fire.mp3`, `divine_presence.mp3`, `door_creak.mp3`, etc. The server sends the effect name and intensity; the client looks up the file and plays it at the scaled volume.

### Session Flow on the Client

**Session Start:**
1. Player taps "Continue Adventure" or "New Session" on the Home screen
2. Client sends `session_start` RPC to the backend
3. Backend creates a LiveKit room, dispatches the DM agent, returns the room token
4. Client connects to the LiveKit room with the token
5. Audio tracks connect — the player can now speak and hear
6. Client receives the initial state push: character data, current location, quest states, map progress → populates local cache
7. Ambience starts playing (matching current location)
8. The DM agent's opening narration arrives on the voice track
9. Client transitions from the Home screen to the Active Session screen

**Mid-Session:**
- Voice flows continuously on the LiveKit audio track
- Server pushes game events on the data channel → client renders overlays, updates cache
- Player can open pull-up screens at any time without interrupting voice
- State is persisted server-side by the background process; the client doesn't write game state

**Session End:**
1. Player says "let's stop here" or taps the end-session button, or the DM initiates wrap-up
2. The DM narrates a brief closing (2-3 sentences to a natural stopping point)
3. Server sends `session_end` event with session summary
4. Client transitions to a Session Summary screen: recap, XP earned, items found, quest progress
5. "Return Home" button → Home screen, where async activities are now available
6. LiveKit room disconnects

**Reconnection (within 5-minute grace period):**
1. Client detects connection drop → shows "Reconnecting..." overlay with ambient audio continuing
2. Client attempts reconnection to the same LiveKit room (room and agent are still alive)
3. On reconnect: server pushes current state snapshot → client resyncs cache
4. DM acknowledges the interruption naturally ("Where were we...") and continues
5. If grace period expires before reconnection: server runs end-of-session flow without the player. Next time the player opens the app, the Home screen shows the session summary.

### Client-Side Performance Targets

| Metric | Target | Rationale |
|---|---|---|
| App launch to Home screen | <2 seconds | Fast entry, no splash screen lectures |
| Home to Active Session (voice connected) | <4 seconds | Room creation + WebRTC negotiation + first audio |
| Overlay render (dice roll, item card) | <100ms from event receipt | Overlays must feel instant and synchronous with narration |
| Audio crossfade (ambience change) | 1-2 seconds | Smooth, not jarring |
| Pull-up screen open | <200ms | Reads from local cache, no network |
| Memory footprint | <150MB active session | Reasonable for a non-game-engine app |
| Battery impact | <10% per 30-min session | Comparable to a voice call + music playback |

### Prototyping Priorities

Two things to validate early because they carry the most client-side risk:

1. **LiveKit React Native + simultaneous audio playback.** Connect to a LiveKit room, receive audio, and simultaneously play local ambient audio files — with correct iOS audio session configuration and Android AudioManager setup. If this doesn't work cleanly out of the box, it needs to be solved before anything else on the client.

2. **Server-pushed overlay rendering.** Receive JSON events on the LiveKit data channel and render animated overlays (dice roll, item card) within 100ms. Validate that Reanimated can drive the animations smoothly while WebRTC audio is streaming. If there are frame drops or audio glitches during overlay animations, the timing or rendering approach needs adjustment.

Everything else on the client (screens, navigation, caching, async hub) is standard React Native work with low risk.

---

## The Voice Pipeline — End to End

### The Core Loop

```
Player speaks → audio captured → transport to server → STT → 
orchestrator classifies intent → routes to appropriate engine → 
response generated → TTS → audio streamed back → player hears DM
```

**Target: first audio response in ~1.2–2.0 seconds.**

### Speech-to-Text (STT)

**Recommendation: Deepgram Nova-3**

Deepgram remains the strongest choice for real-time streaming STT in 2026. Nova-3 offers streaming WebSocket support with interim results, meaning the orchestrator can begin processing intent before the player finishes speaking. Accuracy is strong across accents and casual speech, and latency is consistently low.

**Alternative: Whisper (via Together AI or self-hosted)**
Together AI now offers serverless Streaming Whisper with millisecond-accurate transcription. Could serve as a fallback or for async processing where accuracy matters more than speed.

**Key capability: interim/partial results.** The STT must stream partial transcriptions so the orchestrator can begin routing before the full utterance is complete. This shaves 200-400ms off perceived latency.

### Voice Input — Client-Side VAD with Semantic Turn Detection

**The player just talks.** No buttons, no holding the phone, no gestures. The mobile client handles speech detection locally and manages the audio pipeline automatically.

**Primary mode: VAD-first (hands-free)**

The client runs **Silero VAD** locally — a lightweight voice activity detection model (~2MB, negligible CPU, runs on any modern phone). When the VAD detects speech onset, the client starts publishing audio on the player's LiveKit track. When it detects sustained silence, it signals the end of input. LiveKit's agents framework includes Silero VAD as a built-in plugin.

On the agent side, LiveKit's **semantic turn detector** — a small transformer model — analyzes the incoming transcription to determine whether the player has completed a thought, not just whether they've stopped making sound. "I want to attack the—" reads as incomplete and the system waits. "I search the room for traps." reads as complete and processing begins immediately. This prevents the system from cutting players off mid-sentence while also minimizing the dead time after they finish speaking.

The combination of client-side VAD for speech boundaries and server-side semantic turn detection for intent completeness gives us natural conversational flow without any manual input.

**Echo cancellation:** The DM is speaking through the player's headphones. The mic must not pick up the DM's audio and re-trigger the VAD. With headphones (our primary design target), hardware acoustic echo cancellation (AEC) in the phone's audio stack handles this, and LiveKit's client SDKs include AEC by default. Without headphones, echo becomes a real problem — we should strongly recommend headphones and may enforce it for the best experience.

**Endpointing tuning:** The silence threshold before the system decides the player is done speaking is critical. Too short (200ms) and pauses mid-sentence get cut off. Too long (1.5s) and the game feels sluggish. A starting point of 500-700ms of silence, overridden by the semantic turn detector when it detects an incomplete thought, should feel natural. This will need playtesting and tuning.

**Interruption support:** If the player starts speaking while the DM is still talking, the VAD triggers and the agent can interrupt the current TTS output to process the new input. This is built into LiveKit's agents framework as a first-class feature. It feels natural — just like interrupting a real DM: "Wait, before I go in there, do I see any traps?"

**Multiplayer with VAD:** Two players might start talking simultaneously. This is fine technically — the SFU delivers both tracks separately, tagged with each player's identity, and the DM receives two parallel transcriptions. The DM handles it through the LLM — processing both intents, responding to each, or managing turn-taking conversationally ("One at a time — Kira, you were saying?"). This is a prompt design problem, not an infrastructure problem.

**Fallback mode: tap-to-speak.** For noisy environments or multiplayer sessions where explicit turn-taking is desired, the player can switch to tap-to-speak in settings. Tap once to start, tap again to stop (or tap-and-hold). This is identical to the push-to-talk pattern from LiveKit's example code — the client triggers a `start_turn` RPC and the agent enables audio input for that player's track.

**Noise environment adaptation:** If the VAD is triggering on background noise (coffee shop, transit), the client can automatically raise the VAD sensitivity threshold or suggest the player switch to tap-to-speak. A "noisy environment" toggle in settings handles this explicitly.

### Text-to-Speech (TTS)

**The TTS landscape has evolved rapidly.** After evaluating the full field, Inworld TTS-1.5 has emerged as the primary choice — offering the best combination of quality, cost, and fit for game audio.

**Primary recommendation: Inworld TTS-1.5 Max**

Inworld TTS-1.5 Max is ranked #1 on Artificial Analysis blind tests (ELO 1,160) and was originally built for game character voices. Key advantages:
- **#1 quality ranking** on independent benchmarks — 52 ELO points ahead of ElevenLabs, 107 points ahead of Cartesia
- **$10 per million characters** — 3× cheaper than Cartesia, 20× cheaper than ElevenLabs
- **<250ms P90 latency** (Max), <130ms (Mini) — both support real-time WebSocket streaming
- **30% more expressiveness** and 40% lower word error rate vs. previous generation
- Instant voice cloning from 5-15 seconds of audio
- Temperature-based expressiveness control and talking speed adjustment (0.5×–1.5×)
- 15 languages supported
- On-premise deployment available for data sovereignty
- Game/interactive content heritage — designed for exactly our use case

The latency difference vs. Cartesia (~200ms vs. 40-90ms) is not a concern in practice: the LLM generates text at 500-800ms to first token, which is always the bottleneck. By the time the first sentence is ready for TTS, both providers deliver audio in well under conversational thresholds.

**For routine interactions: Inworld TTS-1.5 Mini ($5/1M chars)**

The Mini model at half the cost with even lower latency (<130ms) is ideal for high-volume, lower-stakes audio: navigation confirmations, merchant exchanges, simple NPC greetings, ambient narration. The orchestrator routes to Mini or Max based on interaction importance.

**Evaluated alternative: Cartesia Sonic-3**

Cartesia remains worth evaluating for specific needs:
- **40-90ms TTFA** — fastest TTS available, valuable if latency proves critical in playtesting
- **Granular emotion controls** — specific emotion tags (excitement, sadness, laughter, breathing) vs. Inworld's temperature dial
- 42 languages (vs. Inworld's 15)
- Built on State Space Models (SSMs) — different architecture, potentially complementary

Trade-off: ~3× more expensive ($30/1M chars at Scale plan) with lower quality ranking. If playtesting reveals that Cartesia's lower latency or more granular emotion controls produce a materially better DM experience, the cost premium may be justified for specific use cases.

**Self-hosted option: Chatterbox-Turbo**

For cost elimination at scale:
- **MIT license** — completely free to self-host
- 350M parameter model, 1-step distilled decoder — fast inference
- **Emotion exaggeration control** — unique parameter to dial expressiveness from monotone to dramatic
- **Paralinguistic tags** — [laugh], [cough], [chuckle] natively in the model
- Zero-shot voice cloning from seconds of audio
- 23 languages (multilingual variant)
- Sub-200ms latency hosted, ~470ms first chunk self-hosted (with community streaming fork)
- Benchmarked favorably against ElevenLabs (63% preference in blind tests)

Self-hosting Chatterbox on GPU eliminates per-character costs entirely. A single A10G (~$0.75/hr) can handle multiple concurrent sessions. This becomes the primary cost-elimination path at 100K+ subscribers.

**Future watch: Dia2 (Nari Labs)**

Dia2 is architecturally the most interesting option for our ventriloquism pattern:
- **Native multi-speaker dialogue** with [S1]/[S2] tags — literally our DM-as-multiple-characters use case
- Streaming from first tokens, real-time on single GPU
- Nonverbal elements (laughter, sighing, coughing) built in
- Audio conditioning for tone and emotion control
- Apache 2.0 license

Currently English-only and research-stage (no managed API, quality not benchmarked against commercial options). Worth tracking — if it matures, it could handle multi-character narration more naturally than switching between single-speaker voice IDs.

**Multiple voices strategy:**
- DM narrator: Stable, authoritative Inworld Max voice with expressiveness
- Companion NPC: Distinct cloned voice with personality-appropriate characteristics
- God whispers: Unique voice per deity via voice cloning + client-side audio effects
- Town NPCs: Pool of 6-8 distinct voices from Inworld's voice library, assigned by character type
- Hollow creatures: Processed/distorted audio, potentially generated differently or post-processed client-side
- Routine interactions: Inworld Mini for cost optimization on lower-stakes audio

### The LLM / Narrative Engine

**Recommendation: Claude (Anthropic) for narrative quality**

For the DM's narration, NPC dialogue, and improvisation, model quality is paramount. Claude's strengths in creative writing, character consistency, and following complex system prompts make it the strongest choice for the narrative engine.

- **Streaming responses** are essential — begin TTS on the first sentence before the full response generates
- **System prompt** assembled dynamically — see DM Agent Architecture below for the layered prompt system
- **Context window management:** Sliding window with compressed session summary + structured world state from database

**For the MVP:** Use Claude API directly. Cost is manageable at playtest scale.
**For production:** Evaluate fine-tuned smaller models for common interactions, reserving Claude-class models for complex narrative moments.

---

## DM Agent Architecture

The DM agent is the core of the game experience. It's not just a voice chatbot — it's a game master that maintains world state, enforces rules, voices characters, and responds to a world that changes independently of the conversation. The architecture has three layers: the voice agent (real-time conversation), the background process (world-aware prompt management), and the toolset (game mechanics and world mutation).

### Layer 1: The Voice Agent

The DM is a LiveKit `Agent` subclass running inside an `AgentSession`. It uses the standard STT→LLM→TTS pipeline: Deepgram Nova-3 for speech recognition, Claude for reasoning and narration, Inworld TTS-1.5 for voice synthesis.

```python
class DungeonMasterAgent(Agent):
    def __init__(self, session_data: SessionData):
        super().__init__(
            instructions=build_system_prompt(session_data),  # static + warm layers
            tools=[
                # World query tools
                query_npc, query_location, query_lore, 
                query_inventory, query_quest_log, query_character_sheet,
                # Dice & mechanics tools
                request_skill_check, request_attack, request_saving_throw, roll_dice,
                # Game state mutation tools
                move_player, add_to_inventory, remove_from_inventory,
                update_quest, update_npc_disposition, apply_status_effect,
                remove_status_effect, award_xp, rest,
                # Client effect tools
                play_sound, show_item_card,
            ],
        )
```

The agent manages a `userdata` dataclass on the session containing the mutable game state handle — player identity, current location ID, active scene state, combat state if any. This is accessible from every tool via `RunContext`.

**Pipeline node customization:** The agent overrides two key pipeline nodes:

`on_user_turn_completed` — fires after the player finishes speaking, before the LLM generates a response. This is the "hot layer" injection point. It queries the database for turn-specific context (current combat state, pending events, immediate sensory details) and injects them as ephemeral messages in the chat context. These messages don't persist beyond the current turn, keeping the conversation history clean.

`tts_node` — parses the LLM's output to extract character dialogue tags (`[MERCHANT]: "What'll it be?"`) and routes each segment to Inworld TTS with the appropriate voiceId. This is the ventriloquism mechanism. The DM narrator voice handles narration, and tagged dialogue switches to character-specific voices.

### Layer 2: The Background Process

The background process is an async coroutine that runs alongside the voice agent in the same Python process. Its job is to keep the DM's system prompt current as the world changes independently of the conversation.

**Why it exists:** A 45-minute session spans real in-game time. Other players act in shared spaces, god-agents shift influence, time of day progresses, environmental conditions change. Without the background process, the DM is frozen in the state the session started — it wouldn't know that another player just cleared the bandits from the road, or that night has fallen and the city gates are now closed.

**Trigger model (hybrid event-driven + timer):**

The background process listens on an event bus and runs a fallback timer. Events trigger immediate prompt rebuilds; the timer catches slow-drift changes.

*Event-driven triggers (rebuild immediately):*
- Player moves to a new location (scene description, NPCs, exits all change)
- Combat starts or ends (prompt needs combat context added or removed)
- A god-agent action affects the player's area
- Another party member does something significant in a shared space
- A quest state changes (objective completed, new objective revealed)
- An NPC the player is interacting with receives updates from another source

*Timer-based fallback (rebuild every 60 seconds if no events fired):*
- Time-of-day progression (affects descriptions, NPC availability, danger levels)
- Weather and environmental drift
- Slow-burn god-influence accumulation
- Session duration pacing cues

**Rebuild process:**

1. Event arrives on the bus (or timer fires)
2. Query the database for current world state relevant to this player's context
3. Assemble a new "warm layer" prompt section
4. Compare against the current prompt — if materially different, call `agent.update_instructions(new_prompt)` with the combined static + warm layers
5. If the event warrants proactive speech, classify its priority and act accordingly

**Proactive speech — the DM speaks unprompted:**

A real DM doesn't wait for the player to ask what's happening. When the ground shakes, the DM says so. The background process can trigger `session.generate_reply(instructions="...")` to make the DM initiate.

Events that justify proactive speech:
- God-agent events (divine intervention, Hollow corruption spreading)
- Environmental danger (building collapsing, storm arriving, ambush)
- Another party member's actions that directly affect this player
- Time-sensitive quest updates (deadline approaching)

Events that do NOT trigger proactive speech (prompt update only):
- Ambient flavor (time of day, weather drift, crowd levels)
- Slow environmental changes
- Background god-influence shifts with no immediate consequence

**Priority system for proactive speech:**

*Critical (can interrupt the player):* Immediate physical danger, god-agent direct intervention, combat-relevant changes (reinforcements arrive, environment shifts mid-fight). Fires `session.generate_reply()` immediately.

*Important (wait for next pause):* Another party member's significant action, quest deadline warning, major environmental shift. Queued and delivered during the next natural silence (when agent state is "listening").

*Routine (prompt update only):* Time-of-day drift, weather, ambient god-influence. Folded into the system prompt; the DM weaves changes into its next natural response.

### Layer 3: The Toolset

Tools are `@function_tool` decorated Python functions that the LLM calls to interact with the game world. They fall into four categories.

#### World Query Tools (read-only)

The DM calls these when the player asks about something not already in the system prompt. These cover the "long tail" of game knowledge — the prompt contains the current scene, but not every NPC's backstory or every item's properties.

**`query_npc(npc_id)`** — Returns personality, backstory, disposition toward this player, current location, shop inventory if merchant. Used when a player engages an NPC not in the active scene section of the prompt.

**`query_location(location_id)`** — Description, exits, hidden elements, hazards, current occupants. For when the player asks about places beyond the current scene.

**`query_lore(topic)`** — Semantic search against the Aethos lore database. Player asks about the Hollow, a forgotten god, a historical event. Returns relevant passages for the DM to weave into narration.

**`query_inventory(player_id)`** — Full inventory list with item properties. The prompt has a summary; this gets details when the player asks "what potions do I have?" or "tell me about this sword."

**`query_quest_log(player_id)`** — Active quests, objectives, progress, history. Summary lives in the prompt; details on demand.

**`query_character_sheet(player_id)`** — Full stats, abilities, status effects, skill modifiers. For when the DM needs exact numbers to make a ruling.

#### Dice & Mechanics Tools (hybrid: LLM requests, rules engine validates and applies)

The DM has narrative judgment about *when* a check is needed. The rules engine determines *how it resolves*. These tools are atomic — they roll, validate, apply consequences, and return results in a single call. The DM cannot ignore or override outcomes.

**`request_skill_check(player_id, skill, context)`** — The DM determines a check is warranted. The rules engine looks up the player's skill modifier, sets DC based on context and difficulty guidelines, rolls, applies modifiers, and returns the canonical result. The mutation (success/failure consequences) is applied immediately.

Returns: `{outcome: "success", roll: 14, modifier: 3, total: 17, dc: 15, margin: 2, narrative_hint: "succeeded comfortably"}`

The DM narrates the outcome but cannot change it. "You run your fingers along the stone wall and feel a faint draft — there's a hidden passage here" (for a successful perception check) is the DM's creative latitude. The *finding* is settled by the dice.

**`request_attack(attacker_id, target_id, weapon_or_spell)`** — Resolves the full attack: to-hit roll against target AC, damage roll if hit, damage application to target HP. Returns the breakdown for narration. If the attack kills the target, that's resolved immediately too — the DM narrates a death, not a choice about whether something dies.

Returns: `{hit: true, damage: 12, damage_type: "slashing", critical: false, target_hp_remaining: 23, target_killed: false, narrative_hint: "solid hit, target wounded but standing"}`

**`request_saving_throw(player_id, save_type, dc, effect_on_fail)`** — Rolls the save, applies the consequence. Poison damage is dealt, status effects are applied, spell effects resolve. The DM narrates what it feels like, not whether it happened.

Returns: `{outcome: "failure", roll: 8, modifier: 2, total: 10, dc: 14, effect_applied: "poisoned for 3 rounds", narrative_hint: "failed decisively, full effect"}`

**`roll_dice(notation)`** — Raw dice roll for narrative moments with no mechanical consequence. "Roll a d100 for the loot table," "flip a coin for which path the NPC takes." Returns the result; the DM interprets it freely.

**The `narrative_hint` field:** Every mechanics tool returns a brief hint about the drama level of the result — "barely succeeded," "critical failure," "overwhelming success." This gives the LLM a nudge about how dramatic to make the narration without dictating specific words.

#### Game State Mutation Tools (smart — enforce game rules)

These tools change the world. They validate inputs, enforce constraints, apply changes, and automatically push relevant UI updates to the client. The DM doesn't need to think about UI — when damage is applied, the combat UI updates automatically.

**`move_player(player_id, destination_id)`** — Validates the path exists and is accessible (locked doors require keys, impassable terrain requires the right ability). Updates player location in the database. Triggers any enter-location events. Returns the new location description for narration. Auto-pushes: location change to client.

**`add_to_inventory(player_id, item_id, source)`** — Checks weight/capacity limits, handles consumable stacking. Rejects with a reason if inventory is full ("your pack is too heavy to carry more"). Auto-pushes: item card popup to client.

**`remove_from_inventory(player_id, item_id)`** — Validates item exists, handles equipped items (must unequip first). Auto-pushes: inventory update to client.

**`update_quest(quest_id, player_id, action)`** — Advances, completes, or fails a quest. Validates prerequisites (can't complete step 3 before step 2). Triggers quest-completion rewards automatically (XP, items, reputation). Returns what changed for narration. Auto-pushes: quest log update to client.

**`update_npc_disposition(npc_id, player_id, delta, reason)`** — Shifts NPC relationship within bounds. A merchant won't jump from hostile to friendly in one interaction — the tool clamps changes to reasonable ranges. Returns the new relationship level and any threshold crossings ("the merchant now trusts you enough to show you the back room inventory").

**`apply_status_effect(target_id, effect, duration, source)`** — Validates the effect is legal, checks for immunities and resistances ("you can't poison an undead"), applies it. Auto-pushes: status effect indicator to combat UI.

**`remove_status_effect(target_id, effect)`** — Validates removal is possible (some effects require specific spells or items to remove, others expire naturally). Auto-pushes: combat UI update.

**`award_xp(player_id, amount, reason)`** — Applies XP, handles level-up if threshold crossed. Returns level-up details so the DM can make it a narrative moment ("you feel a surge of power as your understanding deepens"). Auto-pushes: XP notification to client.

**`rest(player_id, rest_type)`** — Short or long rest. Applies healing, resets abilities, advances in-game time. Validates safety — can't long rest in combat or hostile territory without consequences (the tool returns a warning and the DM narrates the risk, but the rest still happens with potential interruption events).

#### Client Effect Tools

These push visual and audio feedback to the player's device via LiveKit RPC. Mutation tools auto-push where relevant, but the DM can also trigger effects explicitly for narrative moments.

**`play_sound(effect_name, intensity)`** — Triggers sound effects and ambient audio shifts on the client. Named effect library: "sword_clash", "thunder", "tavern_ambience", "hollow_whisper", "critical_hit_sting", "door_creak", "spell_cast", "divine_presence", etc. Intensity controls volume and layering.

**`show_item_card(item_id)`** — Pushes a visual card to the player's UI when they find, receive, or inspect an item. Displays the item's image, stats, description, and rarity. The DM narrates the discovery; the card gives the mechanical details.

**`update_combat_ui(combat_state)`** — Pushes current HP bars, turn order, and active status effects to the client. This is auto-called by combat mutation tools, but the DM can also call it explicitly to refresh the display or highlight a specific element ("look at the turn order — you're up next").

#### Tool Design Principles

**Auto-push UI updates from mutations.** When `request_attack` deals damage, the combat UI updates, the hit sound plays, and the HP bar animates — all without the DM making separate tool calls. The DM focuses on narration; the system handles feedback.

**Smart validation over thin pipes.** Tools enforce game rules: inventory capacity, movement path validity, status effect immunities, quest prerequisites. When a tool rejects an action, it returns a reason the DM can narrate naturally ("your pack is already full" becomes "you try to stuff the potion into your bag, but there's no room").

**Narrative hints, not narrative dictation.** Mechanics tools return a `narrative_hint` suggesting the drama level, but never dictate specific words. The DM decides *how* to describe "critical hit" — the tool just says it happened.

**Atomic operations.** Dice rolls and their consequences are applied in a single tool call. There's no "roll then decide whether to apply" gap that would let the LLM cheat. The DM narrates outcomes, not decisions about outcomes.

**Tools the LLM can't access don't exist.** If the DM shouldn't be able to do something (directly edit a player's character sheet, override a dice roll, bypass a locked door), there's no tool for it. The absence of a tool is the enforcement mechanism.

### Prompt Architecture

The DM's context is delivered in two channels: the system prompt (managed by the background process) and per-turn chat context injection (managed by the `on_user_turn_completed` hook).

#### System Prompt: Static + Warm Layers

The system prompt is set via `agent.update_instructions()` and contains everything the DM needs for general awareness. It has two conceptual layers that are assembled into a single prompt string.

**Static layer (~2,000 tokens) — set at session start, rarely changes:**

```
[DM PERSONA]
You are the Dungeon Master for Divine Ruin. You narrate in second person,
present tense. You voice all NPCs using [CHARACTER_NAME]: "dialogue" tags.
You are atmospheric, responsive to player choices, and never break character.
[tone, style, and content boundary rules]

[GAME MECHANICS REFERENCE]
When a player attempts something risky or uncertain, call request_skill_check.
When combat actions occur, call request_attack or request_saving_throw.
You do not decide the outcomes of checks — the dice do. Narrate the results.
[tool usage guidelines, combat flow summary, rest rules]

[PLAYER CHARACTER]
Name: Kira Ashvane | Class: Warden (Level 4) | Key abilities: [summary]
Personality: [player-authored backstory notes]
Companion: Sable (shadow-fox, bonded familiar)
[condensed character sheet — enough for narration, not full stats]

[SESSION PARAMETERS]
Difficulty: Standard | Tone: Dark fantasy with moments of levity
Content boundaries: [player-configured limits]
Session started: [timestamp] | Current duration: [minutes]
```

**Warm layer (~1,500-2,500 tokens) — rebuilt by background process on events/timer:**

```
[CURRENT SCENE]
Location: The Wailing Market, Ashfall District, Veldross
Time: Late afternoon, overcast, light rain
Description: [2-3 sentences of atmospheric scene-setting]
Exits: North (Temple Quarter), South (Harbor Gate), East (Merchant Row)
Environmental conditions: Hollow corruption level 2/10 — faint wrongness
in peripheral vision, occasional whispered words from nowhere

[ACTIVE NPCs]
- Maren Thell (merchant, female, middle-aged): Disposition FRIENDLY.
  Sells alchemical supplies. Knows rumors about the missing Thornwatch patrol.
  Currently behind her market stall, looks nervous.
- City Watch Patrol (2 guards): Disposition NEUTRAL.
  Passing through on routine rounds. Will intervene if violence breaks out.

[ACTIVE QUESTS]
- "The Silent Patrol" (primary): Investigate the disappearance of Thornwatch
  patrol unit near the Hollowmere border. Current objective: gather information
  in Veldross before heading to the border. Progress: 1/4 objectives complete.
- "Sable's Hunger" (companion): Sable needs to feed on shadow-essence soon.
  Urgency: moderate (2 in-game days remaining).

[WORLD STATE]
- Aethon's influence: RISING in this district (recent divine activity)
- Hollow pressure: STABLE but watchful
- Recent event: A merchant caravan arrived this morning with news of
  border skirmishes. The mood in the market is tense.
- Other party: [if multiplayer] Theron is currently in the Harbor District
  investigating the smuggling ring. No immediate overlap.

[GOD-AGENT CONTEXT]
Aethon (god of order): Currently focused on Veldross. Has been strengthening
wards around the Temple Quarter. May respond to prayers in this area.
The Hollow: Probing the Ashfall District through minor corruption. Not yet
a direct threat but escalating.
```

This entire system prompt benefits from Claude's prompt caching. The static layer is cached after the first LLM call (~0.1× input cost on subsequent reads). The warm layer is cached between background process updates — if no events fire for 60 seconds, it's read from cache for every player turn in that window.

**Estimated total system prompt: ~4,000-5,000 tokens.** At Haiku pricing with caching, this costs roughly $0.0004-0.0005 per turn for the cached portion.

#### Per-Turn Hot Layer (Chat Context Injection)

The `on_user_turn_completed` hook injects ephemeral context into the chat before the LLM generates a response. This content is specific to the current turn and doesn't persist in conversation history.

```python
async def on_user_turn_completed(self, chat_ctx, new_message, ...):
    # Inject combat state if active
    if self.session.userdata.in_combat:
        combat_state = await db.get_combat_state(self.session.userdata.combat_id)
        chat_ctx.add_message(role="system", content=format_combat_context(combat_state))
    
    # Inject pending triggered events
    pending = await db.get_pending_events(self.session.userdata.player_id)
    if pending:
        chat_ctx.add_message(role="system", content=format_pending_events(pending))
    
    # Inject immediate sensory details relevant to player's statement
    # (semantic match against what they just said)
    relevant_details = await get_contextual_details(
        new_message.content, self.session.userdata.location_id
    )
    if relevant_details:
        chat_ctx.add_message(role="system", content=relevant_details)
```

Hot layer content (~300-500 tokens per turn):
- Combat state: turn order, HP values, status effects, tactical positions
- Pending events: "the merchant is waiting for your answer," "you hear footsteps approaching"
- Contextual details: if the player says "I look at the sky," inject current weather/celestial details; if they say "I check the door," inject the door's properties

This is fresh every turn (not cached), but it's small — the cost is negligible compared to the system prompt.

### Putting It Together: Request Flow

Here's what happens when a player says "I want to search the merchant's stall for hidden compartments":

1. **STT:** Deepgram transcribes the speech to text
2. **on_user_turn_completed fires:** Hot layer injection queries the database — injects Maren Thell's stall details, any hidden elements flagged for this location, the player's perception modifier
3. **LLM processes:** Claude reads the full context (static prompt + warm prompt + hot injection + conversation history + player's statement) and decides:
   - This requires a perception check → calls `request_skill_check("kira", "perception", "searching merchant stall for hidden compartments")`
4. **Tool executes:** Rules engine looks up Kira's perception (+3), sets DC 14 (moderate — the compartment exists but is well-hidden), rolls d20 → 11 + 3 = 14, exactly meets DC → success. Applies the discovery to game state. Returns `{outcome: "success", roll: 11, modifier: 3, total: 14, dc: 14, margin: 0, narrative_hint: "barely succeeded — found it at the last moment"}`
5. **LLM narrates:** "You run your hands along the underside of the counter, finding nothing at first. Just as you're about to give up, your fingers catch on a seam in the wood. A hidden drawer, cleverly disguised. [MAREN]: 'Wait — don't touch that!'"
6. **TTS processes:** The orchestrator parses the output. Narration goes to the DM narrator voice. Maren's line goes to her assigned voice (nervous, higher pitch). Both audio segments stream to the player.
7. **Client updates:** If the hidden compartment contains items, `show_item_card` fires automatically. Sound effect "drawer_open" plays.
8. **Background process:** If this discovery is significant (quest-relevant, changes the scene), an event fires on the bus. The background process may update the warm layer to reflect the new state ("Maren is now agitated and defensive about the hidden compartment").

### Combat Flow

Combat deserves special attention because it's the most tool-intensive interaction pattern.

**Entering combat:** The DM (or a triggered event) calls `request_skill_check` for initiative. The rules engine rolls initiative for all participants, establishes turn order, and enters combat state. The combat UI auto-pushes to the client: HP bars, turn order display, status effects.

**During a player's turn:** The DM announces whose turn it is (from the hot layer's combat state). The player states their action verbally. The DM interprets the intent and calls the appropriate mechanics tool:
- "I swing my sword at the creature" → `request_attack(kira, creature_1, longsword)`
- "I try to dodge behind the pillar" → `request_skill_check(kira, acrobatics, "taking cover behind pillar")`
- "I cast Flame Ward on Theron" → `request_attack(kira, theron, flame_ward)` (or a custom spell tool)

Each tool call resolves atomically: roll, validate, apply, return, auto-push UI. The DM narrates the result using the narrative hint and the mechanical outcome.

**NPC/monster turns:** The DM controls enemies. It calls the same mechanics tools for their actions — `request_attack(creature_1, kira, claw_attack)`. The rules engine resolves identically whether the attacker is a player or NPC. The DM narrates the monster's actions and the results.

**End of combat:** When the last enemy is defeated (or the encounter resolves otherwise), combat state is cleared, the combat UI is dismissed, and the background process updates the warm layer to reflect the post-combat scene.

---

## Orchestration Design

The orchestration layer handles everything between "player speaks" and "player hears the response" — output parsing, multi-player input arbitration, error recovery, and session lifecycle. It's the connective tissue between the voice pipeline, the toolset, and the client.

### Output Parsing: The tts_node Voice Router

The DM agent's LLM output mixes narration with character dialogue. The `tts_node` override parses this stream in real-time (as tokens arrive, not after the full response) and routes each segment to the appropriate TTS voice.

**Tag format:**

```
[CHARACTER_NAME, emotion_hint]: "dialogue"
```

Untagged text is narration and goes to the DM narrator voice at default expressiveness. Tagged text goes to the character's assigned voiceId with the emotion hint mapped to TTS settings.

**Example LLM output:**

```
The merchant eyes you suspiciously, then leans forward.
[MAREN, nervous]: "That compartment isn't for sale. You'd best forget you saw it."
[GUARD, authoritative]: "Everything alright here, merchant?"
Maren's expression shifts instantly, a forced smile replacing the scowl.
[MAREN, forced_cheerful]: "Fine, officer. Just a misunderstanding."
```

**Parser extracts five segments:**
1. Narration → DM narrator voice, default settings
2. Maren line → Maren voiceId, temperature high (nervous), slightly faster pace
3. Guard line → Guard voiceId, temperature low (authoritative), measured pace
4. Narration → DM narrator voice, default settings
5. Maren line → Maren voiceId, temperature medium (forced composure)

**Emotion-to-TTS mapping:** The emotion hint is a free-text cue from the LLM. The parser maps it to Inworld TTS parameters:

| Emotion hint | TTS temperature | Speed | Notes |
|---|---|---|---|
| nervous, anxious | 0.8-0.9 | 1.1× | Higher expressiveness, slightly rushed |
| angry, threatening | 0.7-0.8 | 0.9× | Intense but measured |
| calm, neutral | 0.4-0.5 | 1.0× | Default conversational |
| whispering, secretive | 0.3-0.4 | 0.8× | Low energy, slow |
| excited, urgent | 0.8-0.9 | 1.2× | High energy, fast |
| sad, grieving | 0.5-0.6 | 0.8× | Subdued, slow |
| authoritative, commanding | 0.3-0.4 | 0.9× | Steady, deliberate |
| forced_cheerful, lying | 0.6-0.7 | 1.0× | Slightly off — uncanny |

Unrecognized emotion hints fall back to the character's default settings. The mapping is a lookup table, easily tuned through playtesting.

**Streaming parse behavior:** The parser operates on the token stream. It buffers until it can determine the segment type:
- If a `[` token arrives, buffer until the `]:` closing and the opening `"` — then we know the character and emotion, and can begin streaming the dialogue content to TTS immediately.
- If normal text tokens arrive without a `[` prefix, they're narration — stream to the narrator voice immediately.
- Quoted text within a tagged block streams directly to that character's TTS as tokens arrive. No need to wait for the closing `"`.

This means TTS synthesis begins within tokens of the LLM generating each segment. The voice switch between segments is the only point where there's a brief gap (the time to start a new TTS generation with a different voiceId).

**Strict parsing rules (enforced by prompt instructions):**
- The LLM is instructed to ALWAYS use `[CHARACTER_NAME, emotion]: "dialogue"` format for NPC speech
- Stage directions and body language are expressed through the emotion tag or as separate narration segments — never as prose embedded within a dialogue block
- If the LLM produces untagged dialogue (e.g., `Maren says "get out"`), the parser treats the entire line as narration. It still works — the narrator reads the line — just without the character voice. This is the graceful fallback, not a failure.

### Multi-Player Input Arbitration

When multiple players are in a session, their speech arrives on separate LiveKit audio tracks, each tagged with player identity. The orchestrator manages how these inputs are collected and presented to the LLM.

**The 500ms collection buffer:**

When a player's turn completes (VAD + semantic turn detector confirm they're done speaking), a 500ms collection window opens. If another player speaks within that window, their input is collected into the same batch. When the window closes, all collected inputs go to the LLM as a single compound turn:

```
[Kira]: "I search the body for clues."
[Theron]: "I'll keep watch while she does that."
```

The LLM responds to both in one coherent response, addressing each player by character name. If only one player speaks, the window adds no perceptible latency — 500ms is within the normal STT + LLM processing time.

**Interruption policy (anyone can interrupt, DM manages conversationally):**

Any player can speak while the DM is talking. LiveKit's interruption handler stops the current TTS output. The new input is transcribed and sent to the LLM. The DM is prompted to handle interruptions naturally:

```
[System prompt instruction]:
If a player interrupts you, acknowledge it gracefully. You might say
"Hold on—" and address their interruption, or you might weave it into
your narration: "—and just as the door creaks open, Theron, you wanted
to say something?" Maintain conversational flow. Never ignore an interruption.
```

The LLM receives the interrupted context (what it was saying when interrupted) and the new player input, and generates a response that bridges both.

**Combat-specific arbitration:**

During the declaration phase of combat, the collection window extends to match the declaration timer (configured in game settings, typically 10-15 seconds). All player declarations within the window are collected and processed as a batch:

```
[Kira]: "I attack the creature on the left with my sword."
[Theron]: "I cast Shield of Light on Kira."
[Lyra]: "I try to flank around behind them."
```

The DM receives all declarations, resolves them through the mechanics tools in initiative order, and narrates the round as a cinematic sequence. This is the phase-based combat model from the Game Design doc, mapped to the voice pipeline.

### Error Recovery

Errors are handled at the layer where they occur, with graceful degradation rather than hard failures. The player should never experience a frozen or broken session.

**Tool call failure (database timeout, rules engine error, malformed LLM parameters):**

The tool raises `ToolError` with a descriptive message. LiveKit's framework returns this to the LLM, which narrates around it: "Something feels uncertain about that attempt... try a different approach." If the same tool fails repeatedly, the background process logs an alert. The session continues — a failed skill check tool just means the DM improvises without mechanics for that moment.

**Unparseable LLM output:**

Everything the parser can't match to a `[CHARACTER, emotion]: "dialogue"` pattern goes to the narrator voice. The player hears slightly off delivery (the narrator reading dialogue instead of the character voice) but the experience doesn't break. The occurrence is logged for prompt tuning.

**TTS failure on a segment:**

If Inworld returns an error on one segment, that segment is skipped. The DM continues with the next segment. A dropped line mid-narration is less disruptive than a long pause or retry. For critical segments (the punchline of a scene, a god's pronouncement), the system retries once with a 200ms timeout before skipping.

**LLM timeout or rate limit:**

If the LLM doesn't begin streaming within 3 seconds, the `BackgroundAudioPlayer` plays a "thinking" ambient sound (soft atmospheric audio matching the current scene). If no response after 8 seconds, a canned acknowledgment plays: "Give me a moment..." The system retries with the same input. After two failures, the DM delivers a minimal response: "Let's pause for a moment and consider your options." The session stays alive.

**Player disconnect:**

LiveKit detects the disconnect. Grace period: 5 minutes. During the grace period: the agent process stays alive, in-memory state is preserved, the background process pauses proactive events for this player. If the player reconnects within the grace period, they rejoin the room seamlessly — the DM acknowledges: "Welcome back. Where were we..." If the grace period expires, the system runs the end-of-session flow (see below) without the player present.

**Background process crash:**

The voice agent continues running with a stale system prompt. The DM still functions — just with outdated world context (NPCs may not reflect recent events, time-of-day might be wrong). The background process is supervised and restarts automatically. On restart, it immediately rebuilds the prompt from current database state, and the DM is back in sync.

### Session Lifecycle

#### Session Start

1. **Player taps "Continue Adventure" (or "New Session")** on the mobile client
2. **Backend creates a LiveKit room** and dispatches the DM agent via `RoomAgentDispatch`
3. **Agent entrypoint fires** — the initialization sequence:
   - Load player data from database: character sheet, last session state, inventory, quest log, companion state, location
   - Load location data, active NPCs, environmental conditions for the player's current position
   - Load the previous session's compressed summary (if continuing)
   - Build the initial system prompt: static layer (DM persona, mechanics reference, character sheet, session parameters) + warm layer (current scene, NPCs, quests, world state)
   - Initialize `userdata` dataclass with session state handle (player ID, location ID, combat state, session start time)
   - Start the background process coroutine (event bus listener + 60-second timer)
4. **Agent joins the room,** `AgentSession.start()` begins the voice pipeline
5. **Player's client joins the room,** audio tracks connect, WebRTC negotiation completes
6. **`on_enter` fires** → DM delivers a context-appropriate opening:
   - First session ever: Full introduction to the world and the player's situation
   - Continuing from last session: "When we last left off..." recap from the compressed summary
   - Returning after a long break: In-world acknowledgment of time passing, brief catch-up

#### Mid-Session State Persistence

Game state mutations (HP changes, inventory updates, quest progression, location moves) are persisted asynchronously. The tool returns its result to the LLM immediately; the database write happens in a background task.

- **Async writes with retry queue:** Each mutation tool fires a database write as an asyncio task. If the write fails, it enters a retry queue with exponential backoff. The player never waits for persistence.
- **Conversation checkpointing:** Every 5 minutes, the current conversation history is checkpointed (not the full chat context, but enough to reconstruct context on a crash recovery). This is a background operation.
- **Worst-case data loss on crash:** The last few seconds of mutations. For a game, this is acceptable — "you picked up the sword but the server didn't save it, so it's still on the ground" is a minor inconvenience, not a catastrophe.

#### Session End

1. **Trigger:** Player says "I need to stop" / taps end-session button / session approaches a configured time limit (soft warning at 40 minutes for a 45-minute target)
2. **DM wraps up narratively:** `session.generate_reply(instructions="The player is ending their session. Find a natural narrative stopping point within 2-3 sentences. End on a moment that creates anticipation for returning — a cliffhanger, an arriving at a place of safety, or an unresolved question.")`
3. **Final state flush:** All pending async writes are flushed. Any in-flight mutations complete.
4. **Session summary generation:** A separate LLM call compresses the session's conversation history into a structured recap (~500 tokens): what happened, what the player learned, decisions they made, where things stand, unresolved threads. This recap becomes part of the next session's static prompt layer.
5. **Session metadata logged:** Duration, tool calls made, XP earned, locations visited, NPCs interacted with, key narrative events. Used for analytics, the "last session recap" at next login, and player-facing session history.
6. **Cleanup:** Background process stops, agent leaves the room, room is deleted.

#### Reconnection

If a player disconnects unexpectedly (network drop, app crash):

1. **LiveKit detects disconnect** — agent remains in the room
2. **Grace period starts** (5 minutes, configurable)
3. **Background process pauses** proactive events for this player (no point narrating to an empty room)
4. **In-memory state preserved** — agent process, conversation history, game state all stay alive
5. **If player reconnects within grace period:** They rejoin the room. Audio tracks reconnect. The DM acknowledges the return naturally and picks up where they left off. No state is lost.
6. **If grace period expires:** Run the end-of-session flow (steps 3-6 above) without the player present. The DM doesn't narrate a closing — it just persists state and shuts down.

#### Cross-Session Continuity

The player's experience across sessions is maintained through:

- **Compressed session summaries** in the static prompt layer — the DM "remembers" what happened
- **Full game state in the database** — character sheet, inventory, quest progress, NPC relationships, location
- **Conversation history** is NOT carried across sessions verbatim. It's compressed into the summary. This keeps prompt size manageable and avoids the context window growing over dozens of sessions.
- **The warm layer rebuilds from database state** at each session start — so the DM's world awareness is always current, even if other players or god-agents changed things between sessions

---

### The Options

**WebSockets**
- Full control over the audio pipeline
- Simpler to implement and debug
- Easier client-side audio mixing (ambient sounds, spatial audio, sound effects)
- No built-in NAT traversal, SRTP, or adaptive bitrate
- Must handle reconnection, buffering, and error recovery manually

**WebRTC**
- Built for real-time media — NAT traversal, DTLS/SRTP encryption, adaptive bitrate
- Handles network degradation gracefully (packet loss, jitter)
- More complex to implement and debug
- Less control over the audio pipeline — mixing is harder
- Overkill for client-to-server audio when there's no peer-to-peer requirement

**LiveKit — The Hybrid Answer**

LiveKit is the strongest option for our architecture. Here's why:

LiveKit is an open-source WebRTC platform that abstracts away WebRTC's complexity while preserving its benefits. Critically for our use case, LiveKit's Agents framework treats AI agents as room participants — exactly our model. The DM, NPC companions, and god-agents can all join a "room" as participants alongside human players.

**Key LiveKit advantages for Divine Ruin:**
- **Agents as participants:** AI agents join rooms natively, receiving audio streams and publishing audio back. This is literally our DM architecture.
- **Built-in STT/TTS/LLM pipeline:** The Agents framework has plugin support for Deepgram, Cartesia, OpenAI, and others. The voice pipeline we need is a first-class use case.
- **Semantic turn detection:** Uses a transformer model to detect when a user is done speaking — critical for natural conversation flow.
- **Multiplayer native:** Multiple participants in a room with individual audio streams. Player-to-player voice, DM-to-all narration, and spatial audio are all supported.
- **WebRTC reliability with WebSocket control:** LiveKit uses WebRTC between frontend and agents, while agents communicate with backend services via HTTP and WebSockets. Best of both worlds.
- **Open source (Apache 2.0):** Can self-host the entire stack. No vendor lock-in.
- **Production-grade:** Load balancing, Kubernetes compatibility, built-in orchestration.
- **Client SDKs for all platforms:** iOS, Android, React Native, Flutter, Web, Unity.

**Recommendation: LiveKit as the transport and agent hosting layer.**

### Why the SFU Architecture Eliminates Speaker Diarization

This is a critical architectural insight: **LiveKit's SFU (Selective Forwarding Unit) architecture means we never need real-time speaker diarization.** In a traditional mixed-audio setup, all voices get blended into a single stream and you need diarization to figure out who said what. LiveKit doesn't work that way.

In LiveKit, every participant — human or AI — publishes their own individual audio track. The SFU forwards each track separately to subscribers without decoding or re-encoding. When Player A speaks, their audio arrives at the DM agent tagged as Player A's track. When Player B speaks, it's Player B's track. The DM inherently knows who is speaking at all times because each participant's audio is a separate, identified stream.

This is why LiveKit is architecturally perfect for our use case. A tabletop game DM needs to know who's talking — "I attack the goblin" means something different from the warrior than from the healer. With LiveKit's SFU, speaker identity comes free.

### Room Capacity and Limits

LiveKit rooms have **no fixed limit on the number of participants.** The practical limit is that a room must fit on a single node — the self-hosted documentation mentions ~3,000 participants per room as a practical ceiling, with audio-only scenarios supporting even more. For our use case of 2-4 human players plus a handful of AI agents (well under 20 total participants), we are nowhere near any constraint.

Each participant can publish audio, video, and data tracks. Each participant can selectively subscribe to other participants' tracks. This per-track control is foundational to our audio architecture.

### Multiple Agents in One Room

LiveKit explicitly supports dispatching multiple agents to the same room. Using explicit dispatch, you include multiple `RoomAgentDispatch` entries in the room configuration, and each named agent is dispatched independently. Each agent runs in its own process for isolation. The dispatch system supports hundreds of thousands of connections per second with sub-150ms dispatch time.

LiveKit already has production examples of this pattern: their push-to-talk example demonstrates one agent responding to multiple users in a room, their multi-agent-python repo shows multiple agents cooperating, and their restaurant ordering example shows agents managing shared state across participants.

### The Linked Participant Model and How We Override It

By default, a LiveKit `AgentSession` creates a `RoomIO` that links the agent to one "linked participant" — typically the first person to join. The agent listens to and responds to that one person. This is the 1:1 pattern used in call center and customer support demos.

**This is a default, not a constraint.** For our DM agent, we create a custom `RoomIO` that subscribes to ALL human player audio tracks. LiveKit provides full control: you can manually set which participants the agent listens to, dynamically switch the linked participant, or subscribe to all tracks simultaneously.

The push-to-talk pattern in LiveKit's examples demonstrates the underlying mechanism: audio input can be dynamically enabled/disabled per player track via RPC. Our VAD-first approach builds on this same infrastructure — instead of the player triggering `start_turn` manually, the client-side VAD triggers it automatically when speech is detected. The DM agent receives each player's audio on their individual track, so the transcription arrives inherently tagged with the speaker's identity — no diarization, no speaker ID model, no ambiguity. In tap-to-speak fallback mode, the flow reverts to the manual `start_turn` RPC pattern.

### Architecture Summary

The architecture becomes:
- Players connect to a LiveKit room via the mobile client
- The AI DM agent joins the room as a participant via LiveKit Agents framework
- NPC companion agents join as additional participants (or are voiced by the DM — see "DM Ventriloquism" section below)
- Player audio → LiveKit (separate tracks per player) → DM agent (STT → orchestrator → LLM → TTS) → LiveKit → all players hear the response
- Player-to-player voice passes through LiveKit natively — players hear each other directly
- Backend game engine communicates with agents via HTTP/WebSocket

This gives us WebRTC's reliability and NAT traversal for the player-facing connection, while our game logic communicates with the agent layer through standard WebSockets where we have full control. Audio mixing for ambient sounds, combat audio, and the Hollow's wrongness happens client-side on top of the LiveKit audio stream.

---

## Game Engine Layer

### Rules Engine
Deterministic game logic — no LLM needed. Fast (millisecond responses).
- Dice rolling with defined probability distributions
- Damage calculation, health tracking, skill check resolution
- Combat state machine (phase tracking, declarations, resolution)
- Inventory management, leveling, XP
- Divine favor tracking and milestone triggers

**Implementation:** Python or Rust service. Called by the orchestrator, results passed to the narrative engine.

### World State Manager
Persistent state for the game world.
- Character data: stats, inventory, quest progress, reputation, relationships
- Session state: location, active NPCs, combat status, current quest stage
- World state: Ashmark boundary, faction standings, world events
- Regional state: NPC positions, resource availability, local conditions

**Implementation:** PostgreSQL for persistent storage. Redis for session cache (fast access to current session state during gameplay).

### The Orchestrator
The central nervous system. Receives transcribed player input, routes to appropriate systems, assembles responses.

1. **Intent classification:** Is the player navigating? Fighting? Talking? Asking for help?
2. **Context assembly:** Builds the prompt context from session state, world state, character data
3. **Routing:** Sends to rules engine, narrative engine, or both as needed
4. **Response assembly:** Combines outputs into a coherent response for TTS
5. **State update:** Updates world state based on outcomes

**Implementation:** Python service running within or alongside the LiveKit agent. Stateful per session.

---

## Agent Layer — Autonomous NPCs and World Simulation

### The Question: How Alive Should NPCs Be?

You raised the right question about whether NPCs should have autonomous life loops. The answer depends on the tier of NPC.

### NPC Tiers

**Tier 1: Ambient NPCs (Simple)**
Town vendors, guards, generic townsfolk. Pre-defined personalities and dialogue patterns. No autonomous behavior — they respond when spoken to using templated responses with light LLM variation. Cheap to run.

**Tier 2: Reactive NPCs (Moderate)**
Quest-givers, faction representatives, recurring characters. Have personality profiles, memory of past interactions with the player, and state that changes based on world events. Not autonomous — they don't act on their own — but they feel alive because they remember and react. Use LLM for dialogue but with strong personality constraints.

**Tier 3: Companion NPCs (Rich)**
The player's companion and key story characters. Deep personality, relationship memory, emotional state, opinions. They react in the moment (combat suggestions, environmental comments) and between sessions (async messages, relationship evolution). Moderate autonomy — they might initiate conversation or react to world events without being prompted. This is where the OpenClaw-style persistent agent loop starts to apply, but scoped to the individual player relationship.

**Tier 4: God-Agents (Autonomous)**
The ten gods of Aethos. These are fully autonomous agents with life loops, running continuously in the background. They:
- Monitor world state across all active sessions
- Make strategic decisions about their domain (Kaelen positions forces, Aelora adjusts trade routes, Syrath investigates)
- React to player discoveries and actions at scale
- Generate quests and interventions for their followers
- Interact with other god-agents (alliance, disagreement, tension)
- Manage the macro narrative (Ashmark expansion, faction conflicts, seasonal story progression)

This is where the OpenClaw heartbeat pattern applies directly. Each god-agent runs on a loop:
1. Wake up on heartbeat (configurable interval — maybe every 15-30 minutes)
2. Review world state changes since last heartbeat
3. Make decisions based on personality, domain, and current priorities
4. Execute actions: generate new quests, adjust world state, trigger events, send whispers to followers
5. Log decisions for narrative consistency
6. Sleep until next heartbeat

God-agents use a smaller, faster LLM for routine decisions and escalate to a more capable model for significant narrative moments.

### Background World Simulation

**The world should feel alive even when players aren't in it.** This means:

- **The Ashmark shifts** on a schedule, influenced by player actions and god-agent decisions
- **Faction standings evolve** based on aggregate player behavior and god-agent strategy
- **NPC routines continue** — the blacksmith isn't frozen when you leave, they were working on your sword
- **Events trigger** based on world state thresholds — when enough clues have been discovered, the next mystery layer unlocks
- **Async timers resolve** — crafting completes, training finishes, scouts return

**Implementation:** A background worker service that runs world simulation ticks on a configurable interval. God-agents are long-lived processes with heartbeat loops. World events are processed through a queue system.

---

## Multiplayer Architecture

### The Core Problem

How do multiple human players share a voice-first game experience? This isn't just a technical problem — it's a design problem about how shared audio spaces work. Our research into LiveKit's architecture resolved several major unknowns.

### Room-Based Architecture (via LiveKit)

Every game session is a **LiveKit room.** Rooms have no fixed participant limit. Each participant (human or AI) publishes individual audio tracks. The SFU routes tracks to subscribers without mixing — every participant hears individual streams from every other participant.

### The DM Ventriloquism Pattern (MVP Architecture)

For the MVP, we use a **single DM agent that voices all characters.** This is the "DM Ventriloquism" pattern.

**How it works:** The DM agent is the only AI agent in the room. When narrating, it uses the DM narrator voice. When the companion NPC speaks, it switches to the companion's voice. When the player talks to a merchant, it switches to the merchant's voice. Inworld TTS-1.5's WebSocket API makes this seamless — you change the `voiceId` parameter per generation, and the same connection handles multiple distinct voices.

**Why this is the right MVP choice:**
- One agent process instead of many — simpler infrastructure, easier debugging
- One LLM session maintains full narrative coherence — the DM knows everything
- No coordination overhead between agents
- Inworld's voice cloning creates distinct, consistent character voices from seconds of reference audio
- The DM already knows what every NPC should say — it's generating the narrative

**What the DM agent manages internally:**
- A voice registry mapping each active character to an Inworld voiceId
- Character personality profiles in the warm layer of the system prompt (see DM Agent Architecture)
- Emotional state per character (affects TTS temperature/expressiveness settings)
- Conversation history per character (the merchant remembers what you asked last time)

**Character voice tagging in LLM output:**
```
When narrating, respond as the DM narrator.
When an NPC speaks, format as: [CHARACTER_NAME]: "dialogue"
The tts_node parser will split output and route each segment 
to Inworld TTS with the appropriate voiceId.
```

The orchestrator parses the LLM output, splits it into narration segments and character dialogue segments, and sends each to Inworld TTS with the appropriate voiceId. The result is a seamless audio stream where the narrator describes the scene and NPCs speak in their own voices — all from a single agent.

### Multi-Player Input Handling

**VAD-first is the default for all players.** Each player's client runs Silero VAD locally. When speech is detected, their audio track goes active and streams to the DM agent. When silence is detected and the semantic turn detector confirms the thought is complete, the track goes quiet and the DM processes the input.

The flow for each player utterance:

1. Player's client-side VAD detects speech onset → client starts publishing audio on their LiveKit track
2. DM agent receives audio on that player's identified track (SFU keeps tracks separate — no diarization needed)
3. Deepgram transcribes the audio stream, tagged with player identity
4. Client-side VAD detects sustained silence → semantic turn detector on the agent confirms the thought is complete
5. Orchestrator receives completed transcription: `{player: "Kira", text: "I search the body for clues"}`
6. DM processes and responds, addressing the player by character name

**During combat declarations:** Multiple players can speak in rapid succession (or even simultaneously — the SFU handles parallel tracks). The orchestrator collects declarations during the declaration phase window, then the DM processes them as a batch for resolution. The phase-based combat system (from the Game Design doc) maps naturally to this pattern — declarations are gathered, then resolved together, then narrated as a cinematic sequence.

**Simultaneous speech:** Because LiveKit delivers each player's audio as a separate track, two players talking at the same time doesn't create a mixed-audio problem. The DM agent receives two separate transcription streams and can process both. The orchestrator queues them and the DM addresses both in its response. The LLM handles turn management conversationally — "Kira wants to search the body while Theron keeps watch. Let's resolve both." For sessions where this becomes disruptive, players can switch to tap-to-speak mode for explicit turn-taking.

**DM-is-speaking awareness:** While the DM is narrating, player VAD is still active. If a player interrupts, the agent's interruption handler stops the current TTS output and processes the new input. If no one speaks, the DM finishes naturally. The client can optionally show a subtle visual indicator when the DM is speaking (a glowing indicator on the HUD) so players know the DM hasn't finished — but this is a courtesy, not a gate. Players can always interrupt.

### Room Structure — Who's In the Room

**Solo session:**

| Participant | Kind | Publishes | Subscribes To |
|---|---|---|---|
| Player | STANDARD | Voice (VAD-activated) | DM audio |
| DM Agent | AGENT | Narration + all NPC voices | Player audio |

**Party session (2-4 players, MVP):**

| Participant | Kind | Publishes | Subscribes To |
|---|---|---|---|
| Player 1 | STANDARD | Voice (VAD-activated) | DM audio, all player audio |
| Player 2 | STANDARD | Voice (VAD-activated) | DM audio, all player audio |
| Player 3 | STANDARD | Voice (VAD-activated) | DM audio, all player audio |
| Player 4 | STANDARD | Voice (VAD-activated) | DM audio, all player audio |
| DM Agent | AGENT | Narration + all NPC voices | All player audio |

**Party session (production, with independent NPC agents):**

| Participant | Kind | Publishes | Subscribes To |
|---|---|---|---|
| Player 1 | STANDARD | Voice (VAD-activated) | DM audio, all player audio, all NPC audio |
| Player 2 | STANDARD | Voice (VAD-activated) | Same |
| Player 3 | STANDARD | Voice (VAD-activated) | Same |
| Player 4 | STANDARD | Voice (VAD-activated) | Same |
| DM Agent | AGENT | Narration, ambient NPCs | All player audio |
| Companion 1 | AGENT | Its voice only | Player 1 audio, DM audio |
| Companion 2 | AGENT | Its voice only | Player 2 audio, DM audio |
| God Whisper | AGENT | Whisper audio | Selective — only target player |

### Migration Path: Ventriloquism → Independent NPC Agents

The DM Ventriloquism pattern is the MVP. But the architecture must support upgrading specific characters to independent agents as the game grows. Here's the migration path:

**Phase 1 (MVP): Full ventriloquism.** DM voices everything. One agent, one process, one LLM session.

**Phase 2: Companion extraction.** The companion NPC is promoted to its own agent participant. It joins the room independently, has its own STT/LLM/TTS pipeline, its own personality and memory, and its own voice track. It subscribes to its linked player's audio and the DM's audio (so it knows what's happening in the scene). It can interject independently — commenting on the environment, offering suggestions, reacting to combat — without waiting for the DM to "speak for" it.

The DM agent is updated to recognize the companion as an independent participant and no longer generates dialogue for it. The DM still narrates the world and voices ambient NPCs. The companion's LLM receives the scene context from the orchestrator so it stays narratively coherent.

This is the critical moment for immersion: the companion becomes a real presence in the room, not a ventriloquist's puppet. It can whisper to just its player using selective track subscription (only that player subscribes to the companion's audio track). It can argue with the DM's narration. It can have its own emotional arc.

**Phase 3: Key NPC extraction.** Major story NPCs (quest-givers, faction leaders, antagonists) get promoted to independent agents for critical scenes. This is expensive in compute, so it's reserved for high-impact moments — the audience with a god, the confrontation with Veythar's secret, the trial before Valdris. For routine NPC interactions, the DM continues to ventriloquize.

**Phase 4: God-agent voice.** When a god speaks directly to a player (divine whisper, vision, dream sequence), a dedicated god-agent can be dispatched to the room temporarily. It joins, delivers its message with its unique voice, and leaves. This creates genuine dramatic impact — a new presence entering the room that all players can feel.

**The ventriloquism-to-extraction pattern is backwards-compatible.** The client doesn't care whether a voice comes from the DM agent or a separate NPC agent — it's all just audio tracks in a LiveKit room. The transition is server-side only, invisible to the player except that NPC interactions get richer.

### Player Discovery and Matchmaking

**Finding each other:**
- **Friends list / party system:** Players can add friends, form persistent parties, and start sessions together. The party leader creates a room and invites members.
- **Matchmaking queue:** Solo players or partial parties can queue for a session. Matchmaking considers: level range, quest compatibility, reputation score, session tone preference, and party role needs (a group of 3 warriors might want a healer).
- **Guild sessions:** Guilds have persistent rooms/channels. Members can drop in for scheduled sessions.
- **Open world encounters:** Players in the same region at the same time might cross paths. The system can offer: "Another party is exploring the Greyvale Ruins. Would you like to encounter them?"

### The DM Problem: Shared or Separate?

**Each session has ONE DM agent.** The DM manages the shared narrative for all players in the room. This is essential — multiple DMs would create contradictory narratives.

When players merge (encounter in the open world, join a party):
- Their individual DM sessions end
- A new shared DM session starts that inherits context from both
- The shared DM knows each player's character, active quests, and recent history

When players split (party members going different directions):
- The shared DM session forks
- Each sub-group gets a continuation DM that inherits the shared context
- When they reconvene, the DMs merge again

**This is the hardest technical challenge in multiplayer.** DM context must be portable, mergeable, and forkable. The solution is to keep DM context structured (not just conversation history) so it can be composed:
- Player character state (from database)
- Active quest state (from database)
- Current location and environment (from world state)
- Recent conversation summary (compressed, not full transcript)
- Session-specific narrative threads (structured events, not prose)

**LiveKit supports the underlying mechanics:** The `MoveParticipant` API can move a player from one room to another. The `ForwardParticipant` API can share a participant's tracks to multiple rooms simultaneously (useful for a god broadcasting to multiple sessions). Room creation is automatic when the first participant joins, and rooms close when the last participant leaves.

### Voice Interaction Between Players

**In-session voice:**
All players in a room hear each other and the DM. Standard LiveKit room audio. Client-side VAD activates each player's audio track when they speak, with tap-to-speak as a fallback for noisy environments or explicit turn-taking. Players can also hear each other in real-time for out-of-character coordination — LiveKit delivers player-to-player audio directly without going through the DM agent.

**Selective audio / private channels:**
LiveKit's per-track subscription control enables private communication channels within a room:
- **Companion whispers:** Only the companion's linked player subscribes to the companion's audio track. Other players don't hear it.
- **God whispers:** A god-agent publishes audio and only the target player subscribes.
- **Player-to-player whisper:** Possible via a data channel sideband or a separate audio track that only selected players subscribe to.
- **DM secrets:** The DM could publish certain narration on a track that only one player subscribes to — "You notice something the others missed..."

**Proximity-based audio (future, post-MVP):**
LiveKit provides per-track volume control (0 to 1.0) that can be adjusted programmatically. In theory, the server could calculate in-game distance between players and adjust their volume of each other's tracks accordingly — farther away means quieter. The DM would always be full volume. The `ActiveSpeakersChanged` event fires when participants start or stop speaking, providing audio level information that could drive UI indicators.

This is technically possible but adds significant complexity in mapping game-world position to audio parameters in real-time. **For MVP: all players in a room hear everyone equally.** Proximity audio is a post-MVP feature that enhances immersion but isn't necessary to prove the experience works.

**Cross-room communication (future):**
God whispers, guild chat, and async voice messages don't require real-time room sharing. These can be implemented as stored audio clips delivered asynchronously. LiveKit's `ForwardParticipant` API could also enable a "broadcast" pattern where a god-agent's audio is forwarded to multiple active rooms simultaneously — every player with that patron deity hears the god speak at the same moment.

### Multiplayer Session Types

| Type | Players | DM | NPC Approach | Room Structure |
|---|---|---|---|---|
| **Solo** | 1 human | 1 DM agent | DM ventriloquism | Simple room, 2 participants |
| **Party** | 2-4 humans | 1 shared DM agent | DM ventriloquism (MVP) or extracted companions (prod) | Single room, all hear all |
| **Raid** | 5+ humans | 1 DM + assistant narrators | DM ventriloquism + extracted key NPCs | Single room, sub-channels for squads |
| **Open encounter** | 2 parties cross paths | DMs merge into shared session | Combined NPC roster | Rooms merge via MoveParticipant |
| **Async** | 1 human, no room | No live DM — async handler | Pre-generated companion messages | No room, API calls only |

---

## Infrastructure

### MVP Infrastructure

```
┌─────────────────────────────────────────────────┐
│              Mobile Clients (1-4 players)         │
│  (iOS/Android - React Native/Flutter)             │
│  Silero VAD → LiveKit SDK → Speaker               │
│  HUD rendering, client-side ambient audio mix     │
│  Tap-to-speak fallback, noise adaptation          │
└──────────────────┬────────────────────────────────┘
                   │ WebRTC (LiveKit) — separate audio
                   │ track per player, no mixing
                   ▼
┌─────────────────────────────────────────────────┐
│            LiveKit Server (Cloud / Self-hosted)   │
│  SFU: routes individual tracks without mixing     │
│  Room management, agent dispatch (<150ms)          │
│  Per-track subscription control                   │
│  ActiveSpeakersChanged events                     │
└──────────────────┬────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────┐
│     DM Agent (LiveKit Agent — one per room)       │
│  Custom RoomIO: subscribes to ALL player tracks   │
│  ┌───────────────────────────────────────────┐   │
│  │  Deepgram STT (streaming, per-player)      │   │
│  │  Each transcription tagged with player ID  │   │
│  │         ↓                                  │   │
│  │  Orchestrator                              │   │
│  │    ├── Intent Classifier                   │   │
│  │    ├── Context Assembler (all players)     │   │
│  │    ├── Speaker Identification (from track) │   │
│  │    └── Response Router                     │   │
│  │         ↓                  ↓               │   │
│  │  Rules Engine        Narrative LLM         │   │
│  │  (deterministic)      (Claude API)         │   │
│  │         ↓                  ↓               │   │
│  │  Response Assembler                        │   │
│  │    ├── Parse narrator vs character segments│   │
│  │    └── Assign voice_id per segment         │   │
│  │         ↓                                  │   │
│  │  Inworld TTS (streaming, multi-voice)       │   │
│  │  Single WebSocket, multiple voice_ids      │   │
│  └───────────────────────────────────────────┘   │
│  Publishes: single audio track (all voices)       │
│  All players subscribe to this track              │
└──────────────────┬────────────────────────────────┘
                   │ HTTP / WebSocket
                   ▼
┌─────────────────────────────────────────────────┐
│            Backend Services                       │
│  ┌──────────┐  ┌──────────────────┐              │
│  │PostgreSQL │  │     Redis        │              │
│  │(persistent│  │ (session cache,  │              │
│  │  state)   │  │  voice registry) │              │
│  └──────────┘  └──────────────────┘              │
│  ┌──────────────────────────────────────────┐    │
│  │  Async Worker                             │    │
│  │  ├── Crafting/training timers             │    │
│  │  ├── World simulation ticks               │    │
│  │  ├── God-agent heartbeat loops            │    │
│  │  └── Companion between-session messages   │    │
│  └──────────────────────────────────────────┘    │
└─────────────────────────────────────────────────┘
```

### Cloud Platform

**Recommendation: AWS or GCP.** LiveKit Cloud is available for managed hosting during MVP, with the option to self-host later. Backend services deploy via containers (Docker/Kubernetes).

### Cost Considerations for MVP

| Service | Cost Driver | MVP Estimate |
|---|---|---|
| **LiveKit Cloud** | Participant-minutes | Low — 10-15 testers, limited sessions |
| **Deepgram STT** | Audio minutes processed | ~$0.0065/min (Nova-3, Growth) |
| **Claude API** | Input/output tokens | Moderate — every interaction is an LLM call, but prompt caching reduces 80%+ of input costs |
| **Inworld TTS** | Characters synthesized | Largest single component (~53% of session cost) — all DM narration |
| **PostgreSQL/Redis** | Standard hosting | Low |
| **Async workers** | Compute hours | Low |

**TTS is the largest cost component, but no single component dominates.** The full cost model (see *Cost Model* document) shows a 30-minute solo session costs ~$0.40 with Haiku + Inworld Max + self-hosted LiveKit. At a $17.50/month subscription, even solo heavy players (12 sessions/month, 45 min each) run at 52% gross margin. Strategies to further optimize:
- Use Inworld Mini ($5/1M chars) for routine interactions, Max ($10/1M) for dramatic moments
- Cache system prompts aggressively (90% savings on repeated context via Claude's prompt caching)
- Use Haiku for routine interactions, Sonnet for complex narrative moments
- Pre-generate common audio (location descriptions, ambient NPC dialogue)
- At scale: evaluate self-hosted Chatterbox-Turbo to eliminate per-character TTS costs entirely

---

## Development Priorities (Ordered by Dependency)

1. **LiveKit integration + basic voice loop.** Client connects to a room, speaks (detected by client-side Silero VAD), receives audio back from a minimal agent. Prove the transport works, VAD feels natural, and measure end-to-end latency.
2. **STT + TTS pipeline.** Deepgram Nova-3 streaming in, Inworld TTS-1.5 Max streaming out. Prove voice quality and latency meet the ~1.2-2.0s target for first audio response.
3. **DM Agent — basic voice loop.** Implement `DungeonMasterAgent(Agent)` with static system prompt, Claude LLM, and basic conversation. Prove the AI DM can hold a freeform conversation in voice with the DM persona.
4. **DM ventriloquism via tts_node.** Implement the `tts_node` parser that splits LLM output into narrator segments and `[CHARACTER_NAME]: "dialogue"` segments, routing each to Inworld TTS with the appropriate voiceId. Prove that multiple characters sound distinct and transitions feel natural.
5. **Tool system — world query tools.** Implement `query_npc`, `query_location`, `query_lore`, `query_inventory` as `@function_tool` functions backed by the database. Prove the DM can look up information mid-conversation and weave it into narration naturally.
6. **Tool system — dice & mechanics.** Implement `request_skill_check`, `request_attack`, `request_saving_throw` with the hybrid model: LLM requests, rules engine validates, rolls, and applies atomically. Prove the DM calls for checks at appropriate moments and narrates outcomes using `narrative_hint`.
7. **Tool system — game state mutation.** Implement `move_player`, `add_to_inventory`, `update_quest`, `award_xp`, etc. with smart validation and auto-push client UI updates via LiveKit RPC. Prove mutations enforce game rules and client UI stays in sync.
8. **Background process — prompt management.** Implement the async coroutine with event bus + timer fallback. Prove `update_instructions()` keeps the DM aware of world changes mid-session. Test proactive speech with priority classification (critical/important/routine).
9. **Hot layer — per-turn context injection.** Implement `on_user_turn_completed` hook with combat state, pending events, and contextual detail injection. Prove ephemeral context improves DM response quality without bloating conversation history.
10. **Multi-player room.** 2 humans + DM agent in a room. VAD-activated input from both players. DM addresses each by character name. Prove the SFU-based multi-player input model works with simultaneous VAD.
11. **Combat system.** Phase-based combat with multiple actors, declaration queuing, and the full mechanics tool chain. Client-side combat UI (HP bars, turn order, status effects). Prove combat is exciting in audio.
12. **Navigation and world.** The Accord of Tides district and Greyvale. `move_player` tool driving location changes with scene transitions. Prove players can move through the world via voice intent.
13. **Companion NPC (via ventriloquism).** The DM agent voices the companion character with its own personality and distinct voice. Companion offers suggestions, reacts to the environment, has opinions. Prove the ventriloquism pattern creates a convincing NPC presence.
14. **Guidance system.** Escalating nudges, companion suggestions (still ventriloquized). Prove players don't get stuck.
15. **Content: the Greyvale arc.** The actual story, NPCs, encounters. The playtest experience.
16. **Async system.** Timer-based activities with narrative wrapper. Prove the between-session loop.
17. **Companion extraction (post-MVP).** Promote the companion NPC to its own agent participant with independent LLM session and voice track.
18. **God whisper system.** Basic divine favor tracking + god voice interaction via temporary agent dispatch.

---

## Testing and Quality Strategy

### The Testing Challenge

A voice RPG can't be tested like a web app. The product's quality is defined by subjective experience — "does the DM feel like a real dungeon master?" isn't a pass/fail assertion. But beneath that subjective question are layers of systems where we can be rigorous. The strategy is: automate everything that can be automated, build structured evaluation for the AI layers, and reserve human judgment for the experience layer.

Five tiers, from fully automatable to fully human.

### Tier 1 — Infrastructure Tests (Automated, CI/CD)

Standard software testing for the deterministic components. These run on every commit and block deployment if they fail.

**Unit tests:**
- LiveKit room creation, agent dispatch, and cleanup
- STT integration: audio input → transcript output (mock audio fixtures)
- TTS integration: text input → audio output (verify format, duration, voice routing)
- Database operations: CRUD for all entity types, JSONB query patterns
- Redis cache: set/get/invalidate, TTL behavior, rebuild-from-PostgreSQL on miss
- Auth flows: token generation, session validation, expiry

**Integration tests:**
- Full voice pipeline: mock audio → STT → LLM (mocked) → TTS → audio output. Verify the chain completes without error.
- LiveKit data channel: send JSON event → verify client-parseable format
- Background process: inject event → verify `update_instructions()` fires → verify prompt content changes
- Session lifecycle: start → persist → end → verify database state
- Reconnection: connect → drop → reconnect within grace period → verify state intact
- Reconnection failure: connect → drop → grace period expires → verify end-of-session flow

**Load tests:**
- Concurrent sessions: ramp to target concurrent user count, measure resource consumption and latency degradation
- Database write throughput: simulate mutation tool calls at peak combat rate (multiple tools per second)
- Redis cache hit rate under load: verify hot-path reads serve from cache, not PostgreSQL
- TTS concurrent requests: verify Inworld handles burst traffic (combat with multiple characters speaking)

**Performance benchmarks (run nightly, alert on regression):**
- End-to-end voice latency: audio in → audio out, measured at the 50th, 90th, and 99th percentile
- Component latency breakdown: STT time, LLM time-to-first-token, TTS time-to-first-byte
- Tool execution time: each mechanics tool from call to return
- Background process rebuild time: event received to `update_instructions()` complete
- Client overlay render time: data channel event received to pixels on screen (measured on device)

### Tier 2 — Rules Engine Correctness (Automated, Exhaustive)

The rules engine is the one system that must be provably correct. If the DM narrates a hit and the rules engine calculated a miss, player trust collapses. These tests are deterministic and should have near-complete coverage.

**Mechanics tool tests (parameterized, hundreds of cases):**
- `request_skill_check`: every skill × modifier range × DC range → verify correct roll, correct modifier application, correct success/failure determination, correct `narrative_hint` assignment
- `request_attack`: weapon types × attacker stats × defender stats → verify to-hit calculation, damage roll, HP application, status effect triggers (critical hit, killing blow)
- `request_saving_throw`: save types × DC range × status effects → verify roll, consequence application, effect interaction (e.g., advantage from a status cancels disadvantage from another)
- `roll_dice`: all notation formats (d20, 2d6, d100, 4d6 drop lowest) → verify distribution properties over large sample sizes

**Game state mutation tests:**
- `move_player`: valid paths succeed, invalid paths (locked, blocked, nonexistent) fail with correct error message
- `add_to_inventory`: weight limits enforced, stacking works, full inventory rejected with reason
- `remove_from_inventory`: can't remove nonexistent items, equipped items require unequip first
- `update_quest`: stage prerequisites enforced, completion triggers rewards, branching paths work
- `award_xp`: level-up thresholds correct, stat increases applied, level-up details returned
- `apply_status_effect`: immunities respected, duration tracking works, stacking rules enforced
- `rest`: HP restoration correct, exhaustion reduction correct, status effect clearing follows rules

**Edge cases and interactions:**
- Status effect combinations: poisoned + blessed → verify both apply correctly to the same roll
- Simultaneous combat events: two characters attack the same target in the same round → verify HP updates are atomic, not race-conditioned
- Death trigger: HP reaches 0 → verify Fallen state applied, death saves initiated, combat state updated
- Cascade prevention: a mutation that triggers an event that triggers another mutation → verify cascade depth limits are enforced

**Regression suite:** Every bug found in playtesting that traces to a rules engine error becomes a permanent test case. The suite grows over time and prevents regressions.

### Tier 3 — DM Agent Behavior Evaluation (Semi-Automated)

The DM agent is an LLM, so its behavior is probabilistic. But many aspects of DM quality are measurable through structured evaluation. This tier uses scripted scenarios with assertions on the output.

**Tool selection accuracy:**

Build a scenario suite — 50-100 scripted situations with known-correct tool calls:
- Player says "I search the room for traps" → should call `request_skill_check(player, "perception", ...)` or `request_skill_check(player, "investigation", ...)`
- Player says "I attack the goblin with my sword" → should call `request_attack(player, goblin, sword)`
- Player says "I want to buy a healing potion" → should call `query_inventory(merchant)` then possibly `remove_from_inventory` + `add_to_inventory`
- Player says "let's head to the tavern" → should call `move_player(player, tavern_id)`
- Player says "what does this symbol mean?" → should call `query_lore(...)` not `request_skill_check`

Run each scenario N times (N=10-20). Measure: correct tool selected (%), correct parameters (%), tool called when it shouldn't have been (false positive rate), tool not called when it should have been (false negative rate). Target: >90% correct tool selection, <5% false positives.

**Output format compliance:**

Run a conversation suite (100+ DM turns) and parse every output for format correctness:
- Ventriloquism tags: every NPC dialogue line uses `[CHARACTER, emotion]: "dialogue"` format
- No raw mechanics in narration: the DM never says "you rolled a 14" or "DC 13"
- Narrative hints used: when a `narrative_hint` is returned, the DM's narration reflects the margin (barely/overwhelming/catastrophic)
- No hallucinated tools: the DM never references tools or game mechanics that don't exist
- Character consistency: the same NPC uses the same speech patterns across a conversation

Measure compliance rate per category. Target: >95% format compliance, >90% character consistency.

**Guidance system evaluation:**

Simulate a stuck player (player goes silent, or gives confused/off-topic responses):
- Does the DM fire level 1 ambient nudge after the silence threshold?
- Does the companion offer a level 2 suggestion on continued silence?
- Does the DM escalate to level 3 explicit guidance?
- Does the guidance use `global_hints` from the active quest?
- Does the guidance feel natural in tone (not "you should go to the guild hall" but a contextual suggestion)?

Run 20+ stuck-player scenarios. Measure: guidance fires at correct time (%), correct escalation order (%), uses quest-appropriate hints (%).

**Context fidelity:**

Test that the three-layer prompt system keeps the DM accurate:
- Location changes: after `move_player`, does the DM describe the new location correctly? Does it stop referencing the old location?
- NPC knowledge: does the DM respect knowledge gating? An NPC with low disposition shouldn't reveal secrets.
- Quest state: does the DM reference the correct quest stage? Does it avoid spoiling future stages?
- Time awareness: does the DM reflect time-of-day changes (NPC schedules, lighting, shop availability)?
- Combat state: during combat, does the DM track HP, turn order, and status effects correctly?

Build assertion suites for each category. Run regularly as the prompt architecture evolves.

**Evaluation automation pipeline:**

The scenario suites should run as a nightly CI job against the current agent code and prompt. Results are logged to a dashboard with trend lines. Regressions (accuracy drops below threshold) trigger alerts. This creates a feedback loop: every prompt change or tool modification is validated against the full behavior suite before it reaches playtesting.

The evaluator itself can be an LLM — a separate Claude instance that reads the DM's output and judges whether the tool call was correct, the format was compliant, and the narration was appropriate. This is cheaper and faster than human review for the structured categories.

### Tier 4 — Experience Quality (Human Evaluation)

The subjective layer. No automation — structured human judgment with rubrics to make it as consistent as possible.

**Internal playtesting (pre-external):**

Before any external playtester touches the game, the team plays through the full Greyvale arc multiple times. Each session is recorded (audio + event log). After each session, the player fills out a structured rubric:

*DM quality rubric (1-5 per category):*
- Narration quality: Does the prose paint a vivid scene? Does it vary in pacing and tone?
- Character voices: Do NPCs feel distinct? Does the companion feel like a real character?
- Pacing: Does the DM read the player's energy? Does it compress boring parts and expand dramatic ones?
- Rules integration: Do skill checks feel natural? Does the DM call for checks at appropriate moments?
- Improvisation: When the player does something unexpected, does the DM respond creatively?
- Emotional range: Does the DM create tension in combat, warmth in social scenes, unease near the Hollow?

*System quality rubric (1-5 per category):*
- Voice latency: Does the response time feel conversational or awkward?
- Audio quality: Do the voices sound natural? Is the ambient audio immersive? Do effects enhance the scene?
- HUD usefulness: Do overlays appear at the right moments? Are they readable at a glance?
- Combat flow: Does phase-based combat create excitement? Do dice rolls land with dramatic impact?
- Navigation: Can you move through the world by intent without confusion?
- Guidance: If you get stuck, does help arrive naturally?

*Session rubric (1-5 per category):*
- Opening hook: Did the session pull you in within the first minute?
- Narrative arc: Did the session feel like a complete episode?
- Closing: Did you want to come back?
- Emotional investment: Did you care about what happened?

Aggregate rubric scores across sessions to identify weak systems. A category that consistently scores below 3 needs engineering attention before external playtesting.

**External playtesting:**

Detailed in the *MVP Spec — Playtest Structure*. Wave 1 (solo, 10-15 testers) and Wave 2 (group, 5-8 groups). The testing strategy here adds structure to how playtest data is collected and analyzed:

- Every external playtest session is recorded (with consent) — audio, event log, and client screen recording
- Post-session survey covers the MVP spec's success criteria quantitatively (combat engagement rating, DM immersion, return intent, etc.)
- Post-session interview (15-20 minutes) captures qualitative feedback — what moments stood out, what broke immersion, what confused them, what they'd change
- Session recordings are reviewed for critical incidents: moments where the DM failed (wrong tool, bad narration, broken character), where the player got stuck, where audio glitched, where the experience broke
- Critical incidents are categorized (DM behavior, rules engine, latency, audio, HUD, content) and prioritized by frequency and severity

**A/B testing for prompt and configuration changes:**

Once the playtest pool is large enough, structured A/B tests on specific variables:
- Prompt wording changes: does a different static prompt produce better DM narration quality?
- Temperature settings: does a higher LLM temperature create more creative narration or more errors?
- Guidance timing: is 15 seconds too soon for the ambient nudge? Is 20 too late?
- Combat pacing: is 10 seconds the right declaration timer, or should it be 15?
- TTS expressiveness: does higher temperature on emotional lines improve or hurt the voice quality?

Each test needs a clear hypothesis, a measurable outcome metric, and enough sessions to reach statistical significance.

### Tier 5 — Content Quality (Review Process)

The authored content — tier 1 entity descriptions, quest narratives, NPC personalities — needs quality review before it enters the game. Bad content undermines even perfect systems.

**Tier 1 entity review checklist:**

*Locations:* Does the description create a vivid mental image from audio alone? Are the key_features discoverable through natural exploration? Do the exits make spatial sense? Are the conditions (time-of-day, weather, corruption) meaningfully different? Do the ambient_sounds match the atmosphere?

*NPCs:* Is the personality distinctive — could you identify this NPC from dialogue alone? Does the speech_style feel natural when read aloud (not just on paper)? Are the mannerisms memorable but not annoying? Does the gated knowledge create interesting conversation progression? Does the schedule make logical sense for this character's role?

*Quests:* Does each stage have a clear objective that can be communicated in voice? Do the completion_conditions fire at the right narrative moment? Do the branches create meaningful choices (not "good path" vs. "slightly different good path")? Do the hints in global_hints escalate naturally? Is the XP/reward proportional to the effort?

*Items:* Does the description work in audio (avoid visual-dependent descriptions)? Do the effects make mechanical sense in the rules engine? Are the value_modifiers creating interesting economic behavior?

**Content playtesting:**

Beyond structural review, content quality is validated through play. A tier 1 NPC might check every box on the review checklist and still feel flat when the DM voices them. Content passes through three gates:

1. **Authored review** — Does it meet the checklist? Is the writing quality high?
2. **DM agent test** — Feed the entity to the DM agent in a test scenario. Does the DM portray it well? Does the personality come through? Do the gated knowledge triggers work?
3. **Playtest feedback** — Do real players find the NPC/location/quest interesting? Do they remember it after the session?

### Latency Budget

The end-to-end target is 1.2-2.0 seconds from player finishing speech to first DM audio. Here's where every millisecond goes:

| Component | Budget | Notes |
|---|---|---|
| VAD silence detection | 300-500ms | Configurable. Too short → cuts off mid-thought. Too long → feels laggy. Start at 500ms, tune via playtesting. |
| Audio transport (client → server) | 50-100ms | WebRTC, depends on network. Minimal on good connections. |
| STT processing | 200-350ms | Deepgram Nova-3 streaming. Partial results available earlier; final transcript at this mark. |
| LLM time-to-first-token | 400-800ms | Claude Haiku. Includes prompt processing. The bottleneck. Cached system prompt (static + warm layers) reduces this by avoiding re-processing ~3.5K tokens. |
| LLM token streaming | Overlapped | TTS begins on first complete sentence, not full response. Streaming overlap hides most generation time. |
| TTS time-to-first-byte | 150-250ms | Inworld TTS-1.5 Max. WebSocket streaming. The second-largest fixed cost after LLM TTFT. |
| Audio transport (server → client) | 50-100ms | WebRTC return path. |
| **Total (first audio)** | **1,150-2,100ms** | Sum of sequential components. Streaming overlap between LLM and TTS means the player hears audio before the LLM finishes generating. |

**Where the margin is:**
- VAD tuning is the biggest lever — every 100ms off the silence threshold is 100ms off perceived latency, but cut it too short and you interrupt mid-thought.
- LLM TTFT is the bottleneck but partially hidden by streaming. Anthropic's prompt caching (~90% savings on cached tokens) keeps this fast by avoiding re-processing the static and warm prompt layers.
- TTS TTFT is fixed per provider. Inworld Max at ~200ms is acceptable. If it becomes the bottleneck, Inworld Mini at <130ms is the fallback for non-critical narration.

**Latency monitoring in production:**
- Every session logs component-level timestamps: VAD end → STT complete → LLM first token → TTS first byte → client audio start
- Dashboard tracks percentile distributions (p50, p90, p99) per component and end-to-end
- Alerting on p90 exceeding 2.5 seconds or p99 exceeding 4 seconds
- Per-session latency percentiles are correlated with playtest satisfaction scores to find the threshold where latency starts hurting experience

### Continuous Quality Loop

Testing isn't a phase — it's a continuous loop that runs throughout development and after launch:

1. **Every code change** triggers tier 1 (infrastructure) and tier 2 (rules engine) tests in CI.
2. **Every prompt or tool change** triggers tier 3 (DM behavior evaluation) in the nightly suite.
3. **Every content addition** passes through the tier 5 review checklist and DM agent test.
4. **Weekly internal playtests** generate tier 4 rubric scores and identify regressions.
5. **Latency dashboards** run continuously, alerting on degradation.
6. **Playtest feedback** (once external testing begins) feeds back into all tiers — bugs become test cases, subjective complaints become evaluation scenarios, latency complaints inform budget re-allocation.

The goal is that by the time external playtesters sit down, the experience has already been validated against hundreds of automated scenarios, the rules engine has been proven correct, the DM's tool selection is >90% accurate, and the team has played through the full arc multiple times. External playtesting should surface experience-level refinements, not infrastructure bugs.

---

## Open Technical Questions

**Resolved by LiveKit research:**
- [x] ~~Speaker diarization for multiplayer~~ — **Not needed.** LiveKit's SFU delivers each player's audio as a separate, identified track. The DM always knows who's speaking.
- [x] ~~Multiple agents in one room~~ — **Fully supported.** LiveKit allows unlimited participants (agents or humans) per room via explicit dispatch.
- [x] ~~Room capacity limits~~ — **Not a concern.** ~3,000 participants per room (single node). Our max is ~10.
- [x] ~~Proximity audio feasibility~~ — **Technically possible** via per-track volume control. Scoped as post-MVP.

**Remaining open questions:**
- [ ] **VAD tuning and endpointing** — Optimal silence threshold (starting point: 500-700ms), semantic turn detector sensitivity, echo cancellation effectiveness with various headphone types, false trigger rate in noisy environments, and the overall feel of hands-free voice input. Needs extensive playtesting.
- [ ] **Interruption UX** — When a player interrupts the DM, how quickly does the TTS stop? Does it feel natural or jarring? Should there be a brief overlap or an immediate cut? How does the DM handle being interrupted mid-narration gracefully in the LLM prompt?
- [ ] **LLM response quality at speed** — Can we get narrative quality AND low latency simultaneously? May need tiered model strategy.
- [x] **Client-side audio mixing** — Resolved in Client Architecture section. Four independent channels (Voice, Ambience, Effects, UI Audio) with ducking behavior. iOS `.playAndRecord` with `.mixWithOthers` and `.duckOthers`. Ambient sounds triggered by `location_changed` events, effects by `play_sound` events. Prototyping priority to validate LiveKit + simultaneous local playback.
- [x] **DM context portability** — Resolved by the three-layer prompt architecture. Static + warm layers in the system prompt (managed by background process), hot layer injected per-turn via `on_user_turn_completed`. Multiplayer context merging handled by the warm layer including party member state.
- [x] **Ventriloquism output parsing** — Fully specified in Orchestration Design. Strict `[CHARACTER, emotion]: "dialogue"` tags parsed by `tts_node` override. Emotion hints mapped to TTS temperature/speed settings. Streaming parse begins synthesis within tokens. Untagged text falls back to narrator voice gracefully.
- [ ] **Companion extraction trigger** — At what point does ventriloquism become insufficient and an NPC needs its own agent? Metrics: response latency when the DM handles too many characters, player perception of companion "realness."
- [x] **Cost modeling** — Detailed per-session cost estimate completed. See *Cost Model* document. Solo 30-min session = ~$0.40 (Haiku + Inworld Max + self-hosted LiveKit). All player profiles are margin-positive at $17.50/month. The ventriloquism pattern is significantly cheaper than multiple agents per room.
- [x] **Offline/poor connectivity** — Partially resolved in Client Architecture. Reconnection uses LiveKit's ICE restart within the 5-minute grace period. Client shows "Reconnecting..." overlay with ambient audio continuing. Remaining question: what audio does the player hear during a brief dropout (silence, ambient loop, or "connection unstable" notification)?
- [ ] **God-agent coordination** — How do 10 autonomous god-agents avoid contradictory world state changes? The background process event bus is the integration point, but the god-agent arbitration logic is unspecified.
- [x] **Content generation pipeline** — Resolved in *World Data & Simulation* document. Two-tier system: tier 1 authored (human-reviewed, ~35-40 entities for MVP), tier 2 AI-generated from templates and tags (~55-75 entities). On-demand generation fills gaps as players explore. JSON schemas for all entity types. Content loaded into PostgreSQL JSONB.
- [x] **Multi-player combat declarations** — Resolved in Orchestration Design. The 500ms collection buffer extends to the full declaration timer (10-15s) during combat. All declarations are collected and processed as a batch in initiative order. The DM narrates the round as a cinematic sequence.
- [ ] **Tool count and LLM reliability** — Current design has ~20 tools. Need to test whether Claude reliably selects the right tool with this many options. May need to use dynamic tool sets via `update_tools()` — e.g., combat tools only available during combat, merchant tools only when talking to a merchant.
- [ ] **Background process event bus implementation** — Redis pub/sub, PostgreSQL NOTIFY/LISTEN, or a dedicated message queue? Needs to be low-latency for critical events but reliable for important ones.
- [ ] **Proactive speech feel** — Does the DM interrupting the player for urgent events feel natural or annoying? Needs playtesting to calibrate the priority thresholds.

---

## Document Relationships

| Document | Purpose | Status |
|---|---|---|
| **Product Overview** | Executive summary, elevator pitch, document map | Living |
| **Game Design** | Full player experience, all game systems | Living |
| **Aethos Lore** | World, gods, peoples, narrative | Living |
| **MVP Specification** | Minimum testable slice | Living |
| **Technical Architecture** *(this document)* | Client app, voice pipeline, DM agent, orchestration, infrastructure, multiplayer | Living |
| **World Data & Simulation** | Content authoring format (JSON schemas), world simulation rules, data model | Living |
| **Cost Model** | Per-session and subscriber unit economics | Living |

---

*This document is living — it will be updated as technology choices are validated and development progresses.*
