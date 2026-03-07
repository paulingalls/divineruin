# Pre-Flight Checklist

Run through this before each playtest session. Catches issues before they waste tester time.

## Infrastructure (5 min)

- [ ] PostgreSQL running and seeded with Greyvale content
- [ ] Redis running
- [ ] LiveKit server accessible (`LIVEKIT_URL` resolves)
- [ ] All env vars set (check `.env` against `.env.example`)

## Services (5 min)

- [ ] Server starts without errors: `cd apps/server && bun run src/index.ts`
- [ ] Agent starts without errors: `cd apps/agent && uv run python -m agent`
- [ ] Agent connects to LiveKit room successfully (check agent logs)
- [ ] Mobile app launches and connects to server

## Voice Pipeline Smoke Test (5 min)

- [ ] Say "Hello" — DM responds with audio within ~2 seconds
- [ ] DM's voice is clear and audible
- [ ] STT correctly transcribes a simple sentence
- [ ] No echo or feedback loop

## Game Systems Smoke Test (10 min)

- [ ] Character creation flow works (say "I want to create a character")
- [ ] DM calls for a skill check at some point — dice roll resolves
- [ ] Navigation works: "I want to look around" triggers scene description
- [ ] HUD displays on mobile (HP, location, any active status)
- [ ] Ambient audio plays (even if just silence/low drone)

## Combat Smoke Test (5 min)

- [ ] Trigger a combat encounter (move toward a hostile area or provoke an NPC)
- [ ] Combat phases announced by DM
- [ ] Player can declare an action by voice
- [ ] Dice roll resolves and DM narrates result
- [ ] Combat ends with XP/loot narration

## Companion Smoke Test (3 min)

- [ ] Kael speaks with a distinct voice/personality
- [ ] Kael makes at least one unprompted comment
- [ ] Kael participates in combat (if tested above)

## Session Lifecycle (3 min)

- [ ] Session save works (end session, data persists)
- [ ] Session resume works (rejoin, state restored, DM catches you up)

## Async Smoke Test (2 min)

- [ ] At least one async activity is available
- [ ] Starting an activity shows in the async hub
- [ ] God whisper fires if conditions are met

## Recording

- [ ] LiveKit session recording enabled
- [ ] Room name noted: _______________
- [ ] Observer has stopwatch for latency samples

---

**If any smoke test fails:** Fix it before starting the playtest. Don't waste tester sessions on known broken systems.

**All clear? Start the session timer and let the tester play.**
