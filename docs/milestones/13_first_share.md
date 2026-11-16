# First Share — A Playable Story for Friends

Goal: a friend installs the TestFlight build and plays a complete first episode,
then two more sessions, without the DM having to improvise the plot.

This file tracks the story path only. Mechanics phases stay in their own files.
Design change from `mvp_spec.md` Session 1 (human 2026-11-15): the disruption
happens to the player. The rider carries a Veil fragment out of the Greyvale;
where it rests, sound thins and two shadelings condense. The first fight, the
mystery object and the call to action are one beat, in session 1.

## Session 1 — The Fragment (Accord of Tides)

- [x] Creation offers only the first-share subset: 3 races, 4 archetypes, 4 patrons
- [x] A player who gives only a calling and a name gets a complete character
- [x] Onboarding hands off to play once the companion has been met
- [ ] The rider arrives once for every new player, after onboarding
- [ ] The fragment fight runs from `shadeling_cluster` in a contained Accord location
- [ ] When the fight ends, the player holds `greyvale_veil_fragment` and `greyvale_anomaly` has started through the quest path
- [ ] Session 1 pays less than 75 XP, so the player reaches Millhaven at level 1
- [ ] A patron whisper is waiting in catch-up after session 1
- [ ] One acceptance walk drives creation to quest-started with no paid provider

## Session 2 — Millhaven and the Breach

Owner: divineruin2 clone (sprint `greyvale-millhaven`). It may reword these.

- [ ] Arriving in Millhaven completes stage 1 without the DM choosing to
- [ ] The DM's prompt names what finishes the current stage
- [ ] The Millhaven fight is winnable at level 1 and victory advances the quest
- [ ] Every location is reachable from the market square, and every exit has a return
- [ ] The player can rest at the inn

## Session 3 — The Ruins and the Reveal

Owner: divineruin2 clone.

- [ ] Finding the journal fragment puts the item in the inventory
- [ ] The ruins have a fight attached and tuned for a level-2 player
- [ ] The inner chamber holds the discovery
- [ ] The artifact choice is applied and persists
- [ ] Emris can be reached, and the reveal closes the arc on a cliffhanger
- [ ] Veythar's and Syrath's gifts recharge on rest

## Session Edges

- [ ] The Leave button shows the session summary
- [ ] Re-entering never speaks a stale recap
- [ ] The prologue plays with default configuration
- [ ] A failed DM dispatch does not leave the player in an empty room

## Protecting the Bill

- [ ] Only allowlisted emails can sign in
- [ ] A session has a length cap and an idle timeout
- [ ] One player cannot run concurrent sessions or dispatch a second DM
- [ ] Rate limits hold behind the load balancer

## Deployment and TestFlight

Owner: divineruin2 clone. Hosting choice and spend go to the human.

- [ ] Server, agent and worker build as containers
- [ ] Migrate and seed run as a deploy step
- [ ] Narration audio and portraits survive a container restart and are served across processes
- [ ] Production config is complete and email is really sent
- [ ] The server has a health endpoint and errors are reported somewhere
- [ ] A TestFlight build installs and connects to the deployed stack

## Playtest

- [ ] The human plays session 1 end to end on the deployed build
- [ ] Three friends are invited and the tracker in `playtest/` records their sessions

Evidence for every item: [`audit/first-share.md`](audit/first-share.md).
