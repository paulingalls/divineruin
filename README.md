# Divine Ruin: The Sundered Veil

A voice-driven MMORPG for mobile. Players wear headphones, talk to an AI Dungeon Master, and experience a living fantasy world through audio. Think D&D meets Audible meets a persistent online world — no screens required beyond a glanceable HUD.

## What Playing Feels Like

You put on headphones. You hear a world — wind, market sounds, distant bells. The DM's voice sets the scene. You speak naturally: *"I want to find the blacksmith."* The DM narrates your walk through the market, describes the forge, voices the smith who remembers you from last session. You negotiate a price, pick up the sword you commissioned three days ago (it was crafting while you were offline), and head to the guild hall to meet your party.

Two friends join the room. The DM recaps last session and sets the hook: something is wrong in the Greyvale. You ride out. The forest sounds shift. Combat erupts — the DM's voice goes sharp and urgent. Everyone shouts their intent at once. Dice roll. The DM narrates a cinematic sequence of the entire round. Your companion shouts a warning from your left. You hear something behind you that doesn't sound like anything that should exist.

After the session, your patron deity whispers a cryptic message. You set your character to train overnight. Tomorrow, you'll check in for five minutes, hear the results, and make your next decision.

## What It Is

Set in the world of **Aethos**, a fantasy realm under existential threat from creatures pouring through a tear in the Veil (the barrier between reality and what lies beyond). Players collectively unravel the mystery across seasons of play, guided by an AI Dungeon Master that narrates, improvises, manages rules, and voices every character in real time.

The entire experience is voice-first: you speak naturally to navigate, fight, negotiate, and explore. The DM responds within ~1–2 seconds. No push-to-talk. No menus. Just you and the story.

## Core Architecture

**The AI Dungeon Master** is a layered system:

| Layer | Role |
|---|---|
| Narrative Engine | Storytelling, dialogue, descriptions, pacing (Claude LLM) |
| Rules Engine | Combat resolution, skill checks, dice rolls (deterministic) |
| World State Manager | Persistent world tracking across sessions |
| Orchestrator | Routes player input, assembles responses |

**The Voice Pipeline:**
```
Player speaks → VAD detects speech → Deepgram STT (streaming) →
Orchestrator classifies intent → Routes to engines →
Claude generates response (streaming) →
Inworld TTS (streaming, <250ms latency) →
Player hears the DM respond
```

**Target end-to-end latency: 1.2–2.0 seconds.**

**Key technologies:**
- **LiveKit** — WebRTC transport; agents join rooms as participants alongside players
- **Deepgram Nova-3** — streaming STT with interim results
- **Inworld TTS-1.5 Max** — <250ms latency, voice cloning, expressiveness controls
- **Claude** — narrative LLM for DM responses

## Game Systems

- **16 class archetypes × 10 divine patrons** — 160 possible character combinations
- **Phase-based voice combat** — all players declare intent simultaneously; DM narrates the entire round as a cinematic sequence
- **DM Ventriloquism** — one DM agent voices all NPCs by switching voice profiles per dialogue segment
- **Sync + Async play** — 30–90 min real-time sessions with AI-narrated async activities (crafting, training, god whispers) between sessions
- **Autonomous world agents** — ten god-agents running on heartbeat loops, making strategic decisions and generating quests in the background
- **Multiplayer rooms** — 1–4 human players via LiveKit; client-side VAD means players just talk

## The World

**Aethos** has ten gods, each governing specific game mechanics. Players choose a patron deity that flavors their class abilities and quest lines. The gods are AI agents making strategic decisions, interacting with each other, and shaping the narrative — even when no players are online.

The enemy (the Hollow) is deliberately incomprehensible: alien creatures that cannot be reasoned with. This keeps the community fundamentally cooperative and makes them maximally unsettling in audio.

## MVP Scope

The MVP validates one question: **does a voice-first RPG session feel magical?**

- One starting culture (Sunward Accord)
- One city district (Accord of Tides)
- One wilderness zone (The Greyvale)
- One 3–5 session story arc ("The Greyvale Anomaly")
- 2–3 races, 4–5 archetypes, 3–4 divine patrons
- Solo (1 player + AI companion) scaling to 2–4 players

## Monetization

- **$15–20/month subscription** with 7-day free trial
- No pay-to-win — all purchases are cosmetic, narrative, or experiential
- Voice cosmetics (character voices, weapon sounds, spell effects)
- Seasonal battle pass tied to story arcs
- Property system (audio-defined spaces earned or purchased)

## Documentation

| Document | Contents |
|---|---|
| `docs/product_overview.md` | Executive summary, architecture overview, what we're building and why |
| `docs/game_design_doc.md` | Character creation, classes, progression, combat, navigation, monetization |
| `docs/aethos_lore.md` | World history, cosmology, the pantheon, peoples, the core mystery |
| `docs/mvp_spec.md` | Scoped first build, success criteria, development priorities |
| `docs/technical_architecture.md` | DM agent architecture, orchestration, voice pipeline, multiplayer, infrastructure |
| `docs/world_data_simulation.md` | Content authoring format (JSON schemas), world simulation rules, data model |
| `docs/cost_model.md` | Per-session unit economics, subscriber margin analysis |

## Development

```bash
bun install
bun run index.ts
```

Built with [Bun](https://bun.com).
