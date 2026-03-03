# Technical Feasibility Assessment: Divine Ruin

## What you're building

An audio-first MMO RPG where players speak to an AI Dungeon Master. No text, no maps — voice is the entire interface. Full RPG mechanics (combat, companions, factions, gods), persistent shared world, thousands of concurrent players eventually. Think "World of Warcraft meets D&D meets a podcast."

There is no shipped precedent for this category of product.

---

## Current state: ~25-30% of MVP implemented

The Python DM agent is the most mature piece (~1,576 lines, 7 test files). The voice pipeline works end-to-end: Deepgram STT → Claude → Inworld TTS with ventriloquism (one agent voicing multiple NPCs via dialogue tags). The rules engine is pure-function, deterministic, and well-tested. 10 tools are implemented across world queries and mechanics. Database layer with caching is functional. Content for one city district and one wilderness zone is seeded.

The Bun server is a stub (85 lines — token generation only). The mobile app has navigation scaffolding and two screens (home + session). Everything else described in the docs is designed but unbuilt.

---

## Verdict: Ambitious but technically feasible

**The MVP is realistic.** Here's why:

**1. The hardest problem is already solved.** The real-time voice loop (player speaks → STT → LLM reasons + calls tools → TTS responds in character) is working. This is the technical risk that would kill the project if it didn't work. It works.

**2. The tech stack is mature and well-chosen.** LiveKit, Deepgram, Claude, Inworld TTS — these are all production services with streaming APIs. No research-grade dependencies. The only novel integration is wiring them together under a 1500ms latency budget, which the architecture is explicitly designed around.

**3. The rules engine architecture is correct.** LLM decides *when* to act; pure functions decide *what happens*. This is the right separation. It prevents the LLM from hallucinating mechanical outcomes while preserving narrative flexibility. The engine is already tested.

**4. The cost model works.** At $0.40/session (solo, 30 min) against a $17.50/month sub, even heavy players (12 sessions/month) yield 52% gross margin. Inworld's TTS pricing ($10/1M chars) is the key enabler — previous TTS providers made margins unsustainable.

**5. The data architecture scales.** PostgreSQL JSONB + Redis caching + LiveKit data channels is a proven pattern. Entity schemas are flexible. World state is in the DB, not the prompt — this is critical for consistency at scale.

---

## Real risks (ranked by severity)

### 1. Multiplayer audio intelligibility — HIGH RISK

When 4 human voices + DM narration + NPC dialogue + ambient audio all play simultaneously, can players actually understand what's happening? This is a perceptual problem, not a technical one. Phase-based combat (everyone declares, then DM narrates) helps, but real-time group conversation may hit human auditory limits. No amount of engineering fixes this if it doesn't work. You'll know at first party playtest.

### 2. Latency budget — MEDIUM-HIGH RISK

1500ms end-of-speech to first audio byte is tight. Each component (VAD → STT → LLM → tool calls → TTS) adds latency. Streaming helps, but tool calls that hit the DB can add 50-200ms per tool. If the LLM decides to chain 3 tools before responding, you're over budget. The architecture accounts for this (Haiku is fast, caching is aggressive), but it will require constant measurement and tuning.

### 3. Inworld TTS dependency — MEDIUM RISK

TTS is 53% of session cost. Inworld's pricing is excellent today, but you have a single-vendor dependency for the most expensive component. The mitigation (self-hosted Chatterbox-Turbo at scale) is noted in the cost model but not implemented. If Inworld changes pricing or quality, you need that fallback ready.

### 4. God-agent coherence at scale — MEDIUM RISK (post-MVP)

10 autonomous god-agents making world-shaping decisions every 15-30 minutes, affecting thousands of players, must produce coherent narrative. This is the kind of emergent system that can produce brilliance or chaos. It's deferred past MVP, which is correct — but it's the biggest design risk for the full vision.

### 5. Content velocity — MEDIUM RISK

MVP needs ~110 entities. The full game needs 500+. Tier 2 (generated) content must be good enough that the DM can improvise from tags alone. If AI-generated content reads generic, the world feels thin. The content style guide helps, but this is a quality-at-scale problem.

### 6. Companion AI coherence — MEDIUM RISK

A companion that maintains personality, remembers past interactions, and develops an emotional arc across 10+ sessions is hard. Context windows are finite. Summarization loses nuance. The design doc describes rich relationship arcs, but implementing multi-session memory that *feels* continuous is an unsolved problem in the industry.

---

## What's NOT risky

- **Single-player voice RPG sessions** — proven working today in this codebase
- **Deterministic mechanics** — pure functions, exhaustively tested, no LLM involvement
- **Database architecture** — standard PostgreSQL + Redis, nothing exotic
- **Mobile app** — Expo + LiveKit React Native SDK is straightforward
- **REST API** — Bun is minimal, endpoints are CRUD + token generation
- **Ventriloquism** — dialogue tag parsing + voice routing is already implemented and tested

---

## Timeline assessment

**MVP (solo playable, one story arc, 8-10 person playtest):**
- 4-6 person team: 4-6 months remaining (given current progress)
- 2-3 person team: 8-12 months remaining
- Solo developer: 12-18 months

**Multiplayer (party play, shared world, 100+ concurrent):**
- Add 6-12 months after MVP

**MMO scale (1000+ concurrent, god-agents, faction wars):**
- Add 12-24 months after multiplayer baseline
- Requires dedicated infrastructure and content teams

---

## Bottom line

The core technical bet — that streaming voice AI is fast enough, cheap enough, and good enough to be the *entire* game interface — is already validated in the codebase. The rules engine is sound. The architecture is designed for scale without requiring rewrites. The cost model has healthy margins.

The risks are real but bounded: audio intelligibility in groups, latency tuning, vendor dependency on Inworld, and content quality at scale. None of these are "this can't work" risks. They're "this needs careful execution" risks.

The full MMO vision (thousands of players, autonomous god-agents, emergent faction politics) is genuinely unprecedented and will take years. But the MVP — a single-player voice RPG with a compelling 3-5 session story arc — is eminently buildable with the foundation that already exists. Ship that, validate that players want it, then scale.
