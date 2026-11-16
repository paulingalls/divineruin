# First-Share Audit — Distance to a Friends Playtest

Surveyed 2026-11-15 at main `143b1878` (v0.36.1). Three read-only code surveys
(deployment, player flow, story content) plus spot checks. **Read, not run**:
nobody has played the flow end to end, and `playtest/tracker.md` shows zero
sessions. Lines marked ✔ were re-checked by executing code or a content dump;
everything else is a reading of the source and should be re-verified by the
story that acts on it (constraint 11).

The steps this audit produced are the checklist in
[`../13_first_share.md`](../13_first_share.md). This file is the evidence
behind them.

## 1. What is built

- **Flow:** email-code sign-in → prologue → voice creation → onboarding →
  exploration, combat, dispatch (crafting, training, errands), blacksmith →
  spoken recap on return. Entry point `apps/agent/agent.py` (`dm_session`).
- **Client:** auth, home (character gate, catch-up feed, activity launcher),
  session, session summary, join, settings. About 28 HUD event types handled
  (`apps/mobile/src/audio/game-event-handler.ts`). 59 bundled sound files.
- **Async:** `apps/agent/async_worker.py` resolves crafting, errands, training,
  world news and god whispers, and pushes notifications through the server.
- **Multiplayer:** invite codes, deep links, per-participant STT, host handoff
  and guest departure exist and have acceptance tests.
- **Content:** 23 locations, 17 NPCs, 4 quests, 9 scenes, 11 encounter
  templates, 4 companions. Every NPC `voice_id` resolves to a `VOICES` key.

## 2. Story path

The main quest `greyvale_anomaly` has five stages (XP on completion
50/75/150/200/200 ✔; level 2 needs 200 XP). The arc is authored through the
ruins and the Emris reveal; spec sessions 4–5 are barely authored.

**Session 1 (Accord)**
- ✔ `scene_rider_arrival` is gated on no companion and no quest
  (`bg_event_handlers.py:104`); onboarding always assigns a companion, so no new
  player hears it. The handler also only reacts to a location change, and
  onboarding hands off without one.
- ✔ Nothing in `apps/agent` starts `greyvale_anomaly`; the DM must choose to
  call `update_quest`. Nothing reads quest `completion_conditions`.
- ✔ Creation offers 6 races, 18 archetypes and 11 deity options; the entry hook
  in `creation_agent.py` pushes race cards and asks for race.
- ✔ `shadeling_cluster` (two `hollow_shadeling`, 8 HP, level 1, difficulty easy)
  exists and is used nowhere in the arc.
- ✔ Scene-beat `companion_hints` are delivered on silence
  (`background_process.py:195`), but the selector returns nothing when no quest
  is active.
- `content/events.json` (8 events) is seeded and never read.
- The god-whisper worker triggers only at favor 25
  (`god_whisper_data.FAVOR_WHISPER_THRESHOLD`) ✔, which a new player lacks.

**Session 2 (Millhaven)**
- ✔ `hollow_patrol_greyvale` is difficulty hard, recommended level 3 (one
  mawling, two shadeling minions); the player arrives at level 1.
- No stage targets `hollow_incursion_site`.
- Stage `hints` and `branches` are never consumed; location conditions keyed on
  quest stage or corruption are never evaluated; morale effects log "no morale
  system yet".
- The market square has no exit to `greyvale_south_road`.

**Session 3 (ruins and reveal)**
- Finding `ruins_journal_fragment` sets a flag and grants no item.
- ✔ `ruins_mawling_pair` (moderate, level 5) and `ruins_guardian` (hard,
  level 7) are attached to nothing. The inner chamber has no hidden elements,
  NPC or encounter.
- `emris_study`, `torin_quarters`, `yanna_farmhouse` and `grimjaw_quarters`
  have no inbound exits; the final stage targets `emris_study`.
- The keep-or-show artifact choice is never applied.

**Mechanics holes on the path**
- Rest has no production caller (`resurrection.py:65`). ✔ Gift status in
  `content/gods.json`: Kaelen, Aelora, Thyra active; Veythar, Syrath, Valdris,
  Zhael wait on rest; Orenthel waits on healing; Mortaen, Nythera narrated.
- Debt `6d3b1d6a`: player spell and ability damage is never applied to HP. Not
  re-checked in this audit.
- Defeat routes through Mortaen's domain (`combat_end_lives.py`); not run.

## 3. Session edges

- **Leave button:** the client tears down the room; the agent waits 120 s
  (`participant_lifecycle.py:37`), then writes the summary into an empty room.
  The summary screen appears only after a spoken goodbye.
- **Re-entry:** always a new room and a new dispatch. The previous agent can
  outlive it for two minutes, so the spoken recap can be one session stale.
- **No summary** is written for a session that never reaches exploration.
- **Home** shows no last-session summary or history.
- **Guests:** party join is wired only on the returning-player path
  (`agent.py:383`), so a guest is not heard during the host's first session; a
  guest with no character is admitted and silently ignored.
- **HUD:** `currency_gained`, `item_durability_hit` and `skill_tier_advanced`
  are emitted and never shown.
- **Dispatch failure** still returns a token, leaving a room with no DM.
- **Prologue:** the default audio path is an empty directory; the tracked file
  is `assets/audio/prologue.mp3`. With defaults the prologue is skipped.

## 4. Deployment

Target: `docs/ops/production-deployment-architecture.md` (DigitalOcean managed
Postgres and Valkey, LiveKit Cloud, Spaces, containers). None of it exists.

- **Containers:** no Dockerfiles, deploy workflow or IaC. Three processes need
  images: server, agent (needs ffmpeg and repo-root `content/`), async worker.
  The server `start` script hardcodes `--env-file=../../.env`.
- **Migrate and seed:** `scripts/migrate.ts` and `scripts/seed_content.py` are
  non-interactive and idempotent; nothing runs them on deploy. The seed inserts
  the `player_1` fixture.
- **Asset storage:** no object-storage code. The agent and worker write
  narration audio to local disk (`llm_config.py:41`) for the server to serve
  (`activities.ts:203`); separate containers break this, and the two default
  paths do not match even locally. Generated portraits go to ephemeral disk.
- **Config traps:** agent `SERVER_URL` defaults to localhost; email falls back
  to a silent mock without `RESEND_API_KEY`; `AGENT_ENV=production` is needed to
  stop the `player_1` fallback. Missing from `.env.example`: `SERVER_URL`,
  `AGENT_ENV`, `NODE_ENV`, `EMAIL_TRANSPORT`, `EXPO_PUBLIC_API_URL`.
- **Client:** `app.json` has bundle id `com.divineruin.app` and an EAS project
  id; there is no `eas.json`, build number or TestFlight setup. The Expo web
  export runs the game for e2e and is an untested fallback for sharing.
- **Ops:** stdout logs only; no health endpoint, error reporting or metrics.
- **Connections:** each agent job opens an asyncpg pool (2–5); several sessions
  plus the worker and server may approach a small managed-Postgres limit.

## 5. Cost and abuse

- No account allowlist: any email can sign up and start paid voice sessions.
- No session, spend, duration or concurrency caps; `token_tracker.py` only logs.
- A connected idle client keeps the agent alive, and companion idle speech
  keeps spending.
- Every `/api/livekit/token` call dispatches another DM; room ownership is not
  checked, and any signed-in user can create an invite for any room name.
- The rate limiter is an in-memory per-IP map using the socket peer; behind a
  load balancer all clients may share one bucket.

## 6. Test coverage of the flow

- Playwright drives the Expo web build against the real API with injected HUD
  events; it never touches LiveKit, the agent or voice.
- Python acceptance covers multiplayer, reconnection and persistence against a
  testcontainer LiveKit; none drives `dm_session`, prologue or creation.
- Paid real-LLM and live-voice tiers run only with per-run human approval.

## 7. Not on the path to a first share

Economy (Phase 9, 75 open criteria), World Loop (Phase 11), the Phase 12
campaign director, patron abilities and synergies (M8.2, M8.3) and the
remaining Hollow creature effects (M7.3).

## 8. Decisions taken (human, 2026-11-15)

- TestFlight is the first share.
- Creation is simplified: a calling and a name; race and patron default.
- The story is the focus. Session 1 is redesigned so the disruption happens to
  the player: the rider carries a Veil fragment, and the first fight condenses
  around it (lore: `aethos_lore.md` 292, 501, 1040, 1143).
- The first-share arc is three sessions; spec sessions 4–5 wait.
- Two checkouts split the work: this one takes Session 1; the divineruin2
  clone takes Sessions 2–3 and deployment.
