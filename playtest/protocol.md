# Playtest Protocol — Milestone 9.1: Internal Playtest

## Overview

3 complete playthroughs of Sessions 1-4 by different testers. Each playthrough evaluates the full Greyvale arc solo experience against quality rubrics.

## Before You Start

### Environment Setup
- [ ] Agent running: `cd apps/agent && uv run python -m agent`
- [ ] Server running: `cd apps/server && bun run src/index.ts`
- [ ] Mobile app built and running on device (not simulator — need real mic/speaker)
- [ ] LiveKit server accessible
- [ ] Database seeded with Greyvale content: `cd apps/server && bun run seed`
- [ ] Redis running
- [ ] Tester has headphones (required — spatial audio, Hollow effects)

### Per-Tester Setup
- Fresh account / character for each tester
- No pre-briefing on story — tester discovers everything through the DM
- Brief the tester: "Play naturally. Talk to the DM like a real person. Don't try to break it (yet)."

### Recording
- Enable session recording in LiveKit (audio + data channel events)
- Note the LiveKit room name and session ID for each session
- Tester fills out the rubric scorecard after each session (not during)

## Session Flow

### Session 1 — Arrival (target: 30-45 min)
**Expected beats:** Character creation, arrival at Accord of Tides, meet Kael Thornridge, explore initial area, establish routine.

**Watch for:**
- Character creation: smooth voice-driven flow or confused?
- First DM narration: does it hook within 60 seconds?
- Kael introduction: does the companion feel like a character?
- Navigation: can the player move by intent ("I want to go to the market")?
- Latency: time from end-of-speech to first DM audio

### Session 2 — Investigation (target: 30-45 min)
**Expected beats:** Strange happenings, NPC conversations, clues pointing to Greyvale.

**Watch for:**
- NPC variety: do different NPCs sound/feel distinct?
- Clue delivery: organic or forced exposition dumps?
- Player agency: does the DM adapt to player's investigation approach?
- Guidance: if player gets stuck, does help arrive naturally?

### Session 3 — Journey (target: 30-45 min)
**Expected beats:** Travel to Greyvale, wilderness encounters, companion bonding.

**Watch for:**
- Travel pacing: compressed or dragging?
- Combat encounter: exciting in audio only? Dice rolls land dramatically?
- Companion: does Kael feel like a travel partner with opinions?
- Environmental audio: does the soundscape shift as they leave town?

### Session 4 — The Ruins (target: 30-45 min)
**Expected beats:** Explore Greyvale ruins, combat, discover Attenuation Sphere.

**Watch for:**
- Hollow audio: corruption escalation audible (stages 1-3)?
- Combat: more intense than session 3? Stakes feel higher?
- Artifact discovery: meaningful narrative moment?
- Companion reaction: Kael reacts to the discovery with weight?
- Arc conclusion: does the player want to know what happens next?

## After Each Session

1. Tester fills out `rubric-scorecard.md` (copy per session)
2. Observer fills out `observer-notes.md`
3. Log any bugs in `bugs.md` with reproduction steps
4. Note the session duration, LiveKit room ID, and session ID

## After All Sessions (Per Tester)

1. Conduct the post-playtest interview (see `interview-guide.md`)
2. Record the "overall verdict" question
3. Compile scores into `tracker.md`

## Success Thresholds

From the MVP spec — these are the targets:

| Metric | Target |
|---|---|
| Voice navigation | Not stuck >30 seconds |
| Combat engagement | 80%+ rate "exciting" or "fun" |
| DM immersion | Described as a character, not a system |
| Guidance effectiveness | No "lost/stuck" reports |
| Emotional engagement | Attachment to companion / concern about threat |
| Return rate | 80%+ want session 2 after session 1 |
| Mystery traction | Unprompted questions about the artifact |
| Session pacing | 30-45 min, no rushing or dragging |
| Audio immersion | 80%+ say headphones made a difference |
| Overall verdict | 70%+ would pay for this |
