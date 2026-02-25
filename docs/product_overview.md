# Divine Ruin: The Sundered Veil — Product Overview

## The Short Version

We're building a voice-driven MMORPG for mobile. Players wear headphones, talk to an AI Dungeon Master, and experience a living fantasy world through audio. Think D&D meets Audible meets a persistent online world — no screens required beyond a glanceable HUD.

The game is called **Divine Ruin: The Sundered Veil**, set in the world of **Aethos**.

---

## What It Feels Like to Play

You put on headphones. You hear a world — wind, market sounds, distant bells. The DM's voice sets the scene. You speak naturally: *"I want to find the blacksmith."* The DM narrates your walk through the market, describes the forge, voices the blacksmith who remembers you from last session. You negotiate a price, pick up the sword you commissioned three days ago (it was crafting while you were offline), and head to the guild hall to meet your party.

Two friends join the room. The DM addresses all of you, recaps last session, and sets the hook: something is wrong in the Greyvale. You ride out. The forest sounds shift. Combat erupts — the DM's voice goes sharp and urgent. Everyone shouts their intent at once. Dice roll. The DM narrates a cinematic sequence of the entire round. Your companion NPC shouts a warning from your left. You hear something behind you that doesn't sound like anything that should exist.

After the session, your patron deity whispers a cryptic message. You set your character to train overnight. Tomorrow, you'll check in for 5 minutes, hear the results, and make your next decision.

That's the experience. Now here's how we build it.

---

## The Market

The **LitRPG / progression fantasy** community is massive, audio-native (enormous Audible crossover), and primed for exactly this product. They already consume fantasy through audio and imagine themselves in these worlds. No one has built the interactive version yet.

---

## Core Architecture

### The AI Dungeon Master

The DM is not a single model — it's a layered system:

| Layer | Role | Implementation |
|---|---|---|
| **Narrative Engine** | Storytelling, dialogue, descriptions, pacing | LLM-driven (Claude) |
| **Rules Engine** | Combat resolution, skill checks, dice rolls | Deterministic game logic |
| **World State Manager** | Persistent world tracking across sessions | Database + logic layer |
| **Orchestrator** | Routes player input, assembles responses | Middleware / agent router |

Player says "I swing my axe at the goblin" → Orchestrator routes to Rules Engine → attack roll resolves → result passed to Narrative Engine → player hears a vivid description and sees the dice roll on the HUD.

### The Voice Pipeline

The critical path. Everything flows through it.

```
Player speaks → client-side VAD detects speech →
audio streams to server → Deepgram STT (streaming) →
orchestrator classifies intent → routes to engines →
LLM generates response (streaming) → 
Inworld TTS (streaming, sub-250ms latency) → 
player hears the DM respond
```

**Target: first audio response in ~1.2–2.0 seconds.** The DM starts speaking before the full response is generated — streaming LLM output into streaming TTS, sentence by sentence.

Key technology choices:
- **Transport:** LiveKit (open-source WebRTC platform). Agents join rooms as participants alongside human players. The SFU architecture means every player's audio is a separate, identified track — no speaker diarization needed.
- **STT:** Deepgram Nova-3 — streaming with interim results so the orchestrator starts processing before the player finishes speaking.
- **TTS:** Inworld TTS-1.5 Max — ranked #1 on Artificial Analysis, <250ms latency, voice cloning, expressiveness controls. 3× cheaper than Cartesia at higher quality. The DM voices all characters by switching voice profiles per dialogue segment.
- **LLM:** Claude for narrative quality. Streaming responses. Dynamic system prompts assembled per interaction from world state, character data, and session context.

### The DM Ventriloquism Pattern

The DM agent voices all characters — narrator, companion NPC, merchants, quest-givers, gods — by switching TTS voice profiles per output segment. The LLM generates tagged dialogue (`[MERCHANT]: "What'll it be?"`), the orchestrator parses it, and each segment routes to Inworld TTS with the appropriate voice. One agent, many voices, seamless audio.

As the game matures, key NPCs can be promoted to independent agents with their own LLM sessions and voice tracks — the architecture supports this without client changes.

---

## The World

**Aethos** is a fantasy world under existential threat. Thirty years ago, something tore through the Veil — the barrier between reality and what lies beyond. Creatures pour through that are not monsters in any familiar sense. They are alien, incomprehensible, and cannot be reasoned with. The world's ten gods disagree on what the creatures are and how to stop them. Players collectively unravel the mystery across seasons of play.

The enemy's incomprehensibility is a deliberate design decision: it prevents "dark side" faction play, keeps the community fundamentally cooperative, and maximizes horror in audio — something you can't understand is scarier than something you can.

### The Pantheon as Game Systems

Each god governs specific game mechanics, giving the world's rules narrative grounding:

| God | Domain | Governs |
|---|---|---|
| **Veythar, the Lorekeeper** | Knowledge | Magic systems, lore discovery |
| **Kaelen, the Ironhand** | War | Combat systems, martial classes |
| **Aelora, the Hearthkeeper** | Civilization | Crafting, trade, guilds, property |
| **Syrath, the Veilwatcher** | Shadows | Stealth, espionage, hidden quests |
| **Orenthel, the Dawnbringer** | Healing | Healing systems, sanctuary |
| + 5 more | | |

Players choose a patron deity. Divine patronage flavors their class abilities, shapes their quest lines, and creates natural faction dynamics. The gods are autonomous AI agents running on heartbeat loops — making strategic decisions, generating quests, and interacting with each other in the background.

### The Long Game

There is an overarching mystery that unfolds across seasons. Clues discovered by thousands of players feed into the world state. God-agents synthesize discoveries and adjust the narrative. No single player sees the whole picture — the community collectively drives the story forward. The payoff, when it comes, is deeply personal.

*The full lore is documented separately. It's worth reading — the narrative design is as ambitious as the technical design.*

---

## Game Systems

### 16 Class Archetypes × 10 Gods

Six categories — Martial, Arcane, Primal, Divine, Shadow, Support — with 2-3 archetypes each. Every archetype can follow any god, creating 160 possible combinations with distinct playstyles and narrative identities. A Rogue serving the god of justice is a very different character than a Rogue serving the god of shadows.

### Voice-First Combat

Phase-based, not turn-by-turn. All players declare intent simultaneously, dice resolve, and the DM narrates the entire round as a cinematic sequence. Interrupt mechanics let players shout reactions mid-narration. Timer pressure on declarations rewards decisiveness. Sound design IS the tactical environment — spatial audio positions enemies around you.

### Synchronous + Asynchronous Play

**Sync sessions** (30-90 min) are the main event: real-time voice RPG with your party and the AI DM. **Async activities** are the connective tissue between sessions: crafting timers, training, side quests, god whispers, faction reputation. Every async check-in is AI-narrated — decisions bookend wait periods, and the narration makes each one feel unique.

### Multiplayer

LiveKit rooms with 1-4 human players plus the DM agent. Client-side VAD (Silero) means players just talk — no push-to-talk button. The SFU delivers each player's audio as a separate track, so the DM always knows who's speaking. Players can also hear each other directly for coordination. Parties form through friends lists, matchmaking, guilds, or open-world encounters.

---

## Monetization

### Business Model

Higher per-user costs than a traditional MMO — every interaction involves real-time AI inference, voice synthesis, and speech-to-text. Monetization must cover this sustainably. We've modeled it: **margins are healthy for the target subscription price,** with TTS as the dominant cost (~53% of session cost) and the LLM surprisingly cheap (~15%). The full cost model is documented separately.

- **7-day free trial** of the full experience (treat as marketing spend)
- **Premium subscription (~$15-20/month):** Unlimited sync, full async, premium DM narration
- **Battle pass** tied to seasonal story arcs
- **Voice cosmetics:** In a game with no visual character model, your voice IS your identity. Character voices, weapon sounds, spell effects, critical hit signatures.
- **Narrative cosmetics:** Personalized backstory integration, titles NPCs use for you, personal legends bards sing about in taverns
- **Property system:** Audio-defined spaces (a seaside cottage IS its soundscape). Earn through play or purchase to accelerate.

### Red Lines

No pay-to-win. No stat boosts for money. No pay-to-skip-grind. All purchases are lateral — cosmetic, narrative, experiential, or convenience.

---

## Where We Are

### What Exists

- Deep game design across seven living documents: product overview, lore bible, game design, MVP spec, technical architecture, world data & simulation, cost model
- Technology stack selected and validated through research: LiveKit + Deepgram + Claude + Inworld TTS
- Architecture defined for voice pipeline, multiplayer rooms, NPC agents, and world simulation
- MVP scoped: one starting culture (Sunward Accord), one city district, one wilderness zone, one 3-5 session story arc

### What's Next — The MVP

The MVP proves one thing: **does a voice-first RPG session feel magical?**

A single 30-minute session with 1 player, an AI DM, an AI companion, one combat encounter, and one narrative encounter. If that works, everything else is scaling and systems.

Development priorities:
1. LiveKit integration + basic voice loop
2. STT/TTS pipeline with latency validation
3. Orchestrator + DM conversation
4. DM ventriloquism (multi-character voices)
5. Rules engine (dice, combat, skill checks)
6. Multiplayer room (2+ humans)
7. Content: the Greyvale story arc
8. Async system

---

## The Hard Problems

This is what makes the project interesting to build:

**Voice pipeline latency.** The entire experience depends on sub-2-second voice-to-voice response. Streaming LLM → streaming TTS → streaming audio delivery, all while maintaining narrative quality. Every millisecond matters.

**AI DM quality.** The DM must narrate, improvise, manage rules, voice multiple characters, maintain continuity across sessions, and adapt to player behavior — all in real time. The system prompt engineering and orchestrator design are deep technical challenges.

**Multiplayer voice coordination.** Multiple humans and AI agents in one room, with VAD-based input, simultaneous speech handling, and a shared narrative that stays coherent. No one has built this for a game before.

**Autonomous world agents.** Ten god-agents running on heartbeat loops, making strategic decisions, generating quests, and interacting with each other. The world must feel alive even when players aren't in it.

**Content at scale.** Every interaction is AI-generated, but the world needs structure, consistency, and authored narrative arcs underneath the improvisation. The content pipeline — locations, NPCs, quests, encounters — needs to be efficient without being generic.

**Cost management.** Every session is real-time LLM + TTS + STT inference for every player. We've validated that the unit economics work at a $17.50/month subscription — margins range from 9% (solo heavy users) to 91% (light party players). TTS is 77% of session cost, making voice synthesis optimization the primary economic lever. Party play is dramatically cheaper per player than solo.

---

## The Deeper Documents

| Document | What It Covers |
|---|---|
| **Aethos Lore Bible** | World history, cosmology, the pantheon, geography, peoples, cultures, the core mystery |
| **Game Design Document** | Character creation, class system, progression, combat, navigation, player guidance, the opening experience, monetization |
| **MVP Specification** | Scoped first build: what we're building, what we're proving, success criteria |
| **Technical Architecture** | Voice pipeline, DM agent architecture, orchestration, LiveKit rooms, multiplayer, infrastructure |
| **World Data & Simulation** | Content authoring format (JSON schemas), world simulation rules, data model, god-agent integration |
| **Cost Model** | Per-session unit economics, subscriber margin analysis, optimization paths |

---

*If this sounds like something you want to build, let's talk.*
