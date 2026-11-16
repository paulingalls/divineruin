# First Share — A Playable Story for Friends

Goal: a friend installs the TestFlight build and plays a complete first episode,
then two more sessions, without the DM having to improvise the plot.

This file tracks the story path only. Mechanics phases stay in their own files.
Design change from `mvp_spec.md` Session 1 (human 2026-11-15): the disruption
happens to the player. The rider carries a Veil fragment out of the Greyvale;
where it rests, sound thins and one shadeling condenses. The first fight, the
mystery object and the call to action are one beat, in session 1.

## Session 1 — The Fragment (Accord of Tides)

- [x] Creation offers only the first-share subset: 3 races, 4 archetypes, 4 patrons
- [x] A player who gives only a calling and a name gets a complete character
- [x] Onboarding hands off to play once the companion has been met
- [x] The rider arrives once for every new player, after onboarding
- [x] The fragment fight runs from `fragment_shadeling` in a contained Accord location
- [x] When the fight ends, the player holds `greyvale_veil_fragment` and `greyvale_anomaly` has started through the quest path
- [x] Session 1 pays less than 75 XP, so the player reaches Millhaven at level 1
- [x] A patron whisper is waiting in catch-up after session 1
- [x] One acceptance walk drives creation to whisper queued with no paid provider

## Session 2 — Millhaven and the Breach

Shipped in v0.37.0 (divineruin2 clone, sprint `greyvale-millhaven`). The fight's bar is 16 wins of 20 seeds per archetype, where a win includes being downed and saved by the companion.

- [x] Arriving in Millhaven completes stage 1 without the DM choosing to
- [x] The DM's prompt names what finishes the current stage
- [x] The Millhaven fight is winnable at level 1 and victory advances the quest
- [x] Every location is reachable from the market square, and every exit has a return
- [x] The player can rest at the inn

## Session 3 — The Ruins and the Reveal

Owner: divineruin2 clone.

- [ ] Finding the journal fragment puts the item in the inventory
- [ ] The ruins have a fight attached and tuned for a level-2 player
- [ ] The inner chamber holds the discovery
- [ ] The artifact choice is applied and persists
- [ ] Emris can be reached, and the reveal closes the arc on a cliffhanger
- [ ] Veythar's and Syrath's gifts recharge on rest

## Session Edges

- [x] The Leave button shows the session summary
- [x] Re-entering never speaks a stale recap
- [x] The prologue plays with default configuration
- [x] A failed DM dispatch does not leave the player in an empty room

`apps/agent/tests/acceptance/test_fresh_recap.py` exercises room-service takeover,
failed and timed-out closes, guest recaps and saved-location re-entry with real
PostgreSQL, Valkey and LiveKit; model and voice providers are deterministic.

## Protecting the Bill

- [x] Only allowlisted emails can sign in
- [x] A session has a length cap and an idle timeout
- [x] One player cannot run concurrent sessions or dispatch a second DM — 2 h ownership TTL; sessions enforce the approved 60-minute cap
- [x] Rate limits hold behind the load balancer — `apps/server/src/rate-limit.integration.test.ts`, `apps/server/src/rate-limit-failure.test.ts` (real HTTP, shared Valkey, proxy/JWT identity, fail-closed)

## Deployment and TestFlight

Owner: divineruin2 clone. Hosting choice and spend go to the human.

- [x] Server, agent and worker build as containers
- [x] Migrate and seed run as a deploy step
- [x] Narration audio and portraits survive a container restart and are served across processes
- [ ] Production config is complete and email is really sent
- [x] The server has a health endpoint and errors are reported somewhere
- [ ] A TestFlight build installs and connects to the deployed stack

## Playtest

- [ ] The human plays session 1 end to end on the deployed build
- [ ] Three friends are invited and the tracker in `playtest/` records their sessions

Evidence for every item: [`audit/first-share.md`](audit/first-share.md).
