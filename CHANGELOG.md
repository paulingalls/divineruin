# Changelog

## 0.50.0

Zhael's followers can bend fate. Fate's Thread lets a follower force a reroll after any check, attack, saving throw or death save they or an ally makes, then choose which result stands; the outcome waits until they decide. Lucky turns a follower's own natural 1 into a 20, or a 20 into a 1. Initiative, shoves and grapples, reaction contests, crafting experiments, Echo rolls and free-form dice are outside fate's reach.

Mortaen's followers sense the dying: Death's Awareness names the creatures and party members nearby at a quarter health or less. Nythera's followers keep their bearings: Horizon Sense reports the hours traveled since their last long rest and the nearest place they have never visited, counted in travel legs.

Veythar's followers roll saves against the Hollowed condition with advantage (Scholar's Ward), and Kaelen's followers have 5 more maximum HP (Warrior's Endurance).

Release steps: none.

## 0.49.3

Housekeeping: the shared patron validator test fixture now carries Veythar's current Natural cantrip synergy text, matching the game content. No gameplay change.

Release steps: none.

## 0.49.2

Thyra's Natural synergy for Druids, Beastcallers and Wardens now works away from the wild. Outside natural terrain, Nature's Pulse gives them +2 on Perception and Survival checks. In natural terrain it still gives advantage, and the two never stack.

Release steps: none.

## 0.49.1

Fixed: an Unbound player whose patron was stored as empty, rather than "none", made the twenty-minute deed judgment fail, which stopped that session's background loop. Such players are now judged as Unbound and earn autonomy normally. A patron id that names no god still fails loudly.

Release steps: none.

## 0.49.0

The Unbound Path now has its own progression. An Unbound player builds autonomy by acting alone:
- winning a fight with no ally present (+4);
- succeeding on a check alone (+1);
- choosing to push their own Resonance with Raw Channeling (+2).

Every twenty minutes of play the DM judges these deeds, each counted once, and tells the player when they reach a new tier. Tiers are milestones and are never lost.

- **Self-Reliant** (from the start): choose one saving throw to become proficient in. It applies at once, even mid-fight.
- **Self-Forged** (40 autonomy): Divine Immunity. Once per long rest, the player can shrug off a divine ability, narrated by the DM.
- **Sovereign** (75 autonomy): Veil Mastery. Once per session, a Hollow Echo becomes "Nothing stirs".

Rule change: Veil Mastery used to be every Unbound player's starting gift. Now it is the Sovereign reward, as the design intends.

Asking the DM about your patron as an Unbound player now reports your autonomy, your tier and which rewards are ready.

Release steps: none.

## 0.48.2

The agent test tooling moves to pytest 9.2.0 and pytest-bdd 9.0.1. One pytest run that mixes acceptance and regular test files no longer loses the acceptance fixtures. Nothing players see changes.

Release steps: none. After pulling, run `uv sync --project apps/agent --frozen` in each local checkout.

## 0.48.1

Move the patron query into a dedicated module to make future patron updates easier to maintain.

Release steps: none.

## 0.48.0

Every archetype now has a synergy with every patron: 180 pairings, each Natural, Divine or Unexpected. Natural pairings fit the god's domain and give the largest mechanical bonus. Divine pairings give a moderate one. Unexpected pairings give a small, unusual edge, often something only that character notices. A player can ask the DM about their synergy, and the DM can look it up.

Twelve synergy effects now work in play:
- Kaelen's Iron Resolve triggers below 40% health, instead of 25%, for Warriors, Guardians and Skirmishers.
- Aelora's Artificers get +2 Bond with two allies near.
- Syrath's followers cast hidden for one less Resonance.
- Nythera's Seekers and Spies get +3 to Investigation and Perception at a place they haven't stayed before, including when searching for the Choir's sound.
- Nythera's Druids and Beastcallers get +1 to Animal Handling.

Synergies that change combat rolls, or that depend on what a check is for, are described by the DM but don't change the numbers yet.

Unbound players get +1 on every skill check when no companion or other player is with them.

Some design-doc synergy numbers were rebalanced so Natural is always the largest bonus. Valdris's Paladin bonus rises to +2. Several Unexpected and Divine bonuses drop to +1, and Thyra's Unexpected critical bonus drops to +1d4.

Release steps: none.

## 0.47.2

Native backend acceptance on iOS owns its API server, Metro and temporary sign-in enrollment, cleaning up after each run.

Release steps: none.

## 0.47.1

A test now covers the HUD inventory showing tainted and clean stacks of the same material as separate rows, each with its own quantity, in the phone-sized web build. Nothing players see changes.

Release steps: none.

## 0.47.0

Patron tier abilities are in play. A follower at Acknowledged, Devoted or Exalted favor can now ask the DM to use the seven abilities the DM resolves by narration: Veythar's Lorekeeper's Library, Syrath's Whisper Network and Veilwatcher's Eye, Mortaen's Speak with Dead, Nythera's Charted Course, Valdris's Discern Lies and Zhael's Prophecy Fragment. Valdris's Layer 1 gift, Weight of Truth, works the same way. Each use is spent and comes back on its authored rest or, for once-per-session abilities, at the next session. Abilities lock when favor drops below their tier and come back, with the same spent state, when it climbs again. The other 23 tier abilities are listed as not yet in play.

Rule change: a long rest now also restores abilities and gifts that recharge on a short rest. This includes Veythar's Lorekeeper's Insight and Syrath's Shadow Veil, which before came back only on a short rest.

The character sheet lists the follower's patron abilities as ready, spent or locked, and the favor bar stays current. A player who joins someone else's session now gets their own sheet and favor bar right away, and a reconnect refreshes them. Session start data is sent only to its own player.

Under the hood, spell_casting.py is split into smaller modules with no behavior change.

Release steps:
- Apply migration 065_patron_revision.sql (adds players.patron_revision and its update trigger) with the normal migrate step before deploying the agent and server. Free; it writes the production schema.

## 0.46.0

In multiplayer, every player now hears their own god. When a guest's favor crosses a tier, the guest's patron whispers to them by name, and a guest whose favor drops hears that god's displeasure once a session, as the host always has. When two players cross at once, both whispers play in turn. A player who leaves before their whisper plays hears nothing, and their whisper is not counted as delivered.

Release steps: none.

## 0.45.2

The test runner is pinned to proof v0.34.1. Before the fix, staged runs (every free patch's acceptance and every commit hook) read every input file through git for every task, so setup on a staged sprint run took 25 minutes or more. Setup now takes about 24 seconds. There is no player-facing change.

Release steps: none.

## 0.45.1

Split spell casting into smaller modules while preserving casting behavior.

Release steps: none.

## 0.45.0

Crafting now counts toward your patron's favor. When a craft finishes, even with a flaw, the crafter records a crafted-item deed. Aelora, the Hearthkeeper, values that deed, so her followers gain favor at their next twenty-minute judgment in play. A failed craft records nothing.

Release steps: none.

## 0.44.0

Your patron now notices what you do in play. Winning a fight with every enemy down, fleeing, talking a fight down, slipping past on a stealth check and uncovering lore on a knowledge check are recorded as deeds. Every twenty minutes of play, your patron judges them. A deed your god values raises favor, a deed against its values lowers it, and another god's deed is ignored. Each kind of deed counts once per twenty minutes, so repeating it earns nothing more, and a deed the DM has already rewarded is not paid again. Deeds left unjudged when a session ends are judged early in the next one. When favor moves, the DM hears about it and your favor bar updates.

Release steps: none.

## 0.43.0 — 2026-11-17

- The Greyvale arc plays to its end. Finding the journal fragment puts it in the inventory, even when the item was found before its stage came up.
- The ruins have a fight tuned for a level-2 player: a pair of young mawlings, a new tier-1 Hollow creature. Winning it opens the way on.
- The Veil fragment from session 1 opens the sealed inner door. Any party member holding it lets the party through, so a warrior is no longer locked out by an Arcana check.
- Walking into the inner chamber reveals the sealed artifact, with no roll to miss.
- Keeping the artifact secret or showing the companion is a decision the DM records once. Its effects apply in the same transaction and are remembered. Millhaven's defence choice uses the same path, and an option effect that does not parse is refused.
- Bringing the find to Emris closes the arc. The closing beat is spoken, and the player's own patron whispers; an Unbound player hears none. Effects that nothing consumed were removed.
- Veythar followers can reroll a failed knowledge check once, and Syrath followers can vanish for a round in combat. Each gift returns after a short rest.

## 0.42.1 — 2026-11-17

- Proof generation no longer fails in a checkout that holds a Git-ignored virtualenv (such as `scripts/audio/.venv-sa3`). In a Git checkout the import graph lists only tracked and unignored files; Proof's sandbox keeps scanning its tracked tree.

## 0.42.0 — 2026-11-16

- An edit anywhere reruns at most a handful of expensive tests. Across every tracked file outside the lockfiles, manifests, toolchain versions and acceptance-stack scripts, the files whose edit reruns more than 20 acceptance or e2e tasks fell from 829 to 11, and the mean per file fell from 19.5 to 4.7. `python3 scripts/proof_key_breadth.py` reads it in about 20 seconds without running a test, and `--limit <glob> <n>` fails naming any file over a limit. It replaces `scripts/proof_selection_probe.py`.
- Test harness modules, conftests and provider helpers key one representative test per family. A feature file, fixture or WAV keys the tests that name it.
- An agent module keys its direct importers when there are at most 10, otherwise one representative per reaching family; below the threshold every reaching test is keyed, its own family included.
- Content keys the tests whose behavior loads it, including a test's own SQL reads of a seeded table, or representatives. Migrations and the seed script stay within 20.
- Acceptance tests that launch subprocesses key what they actually launch (Proof-resolved TypeScript closures and named scripts) instead of whole directories, and media keys the tests that read it. An unclassified subprocess launch or a named reader that reaches no test fails generation.

## 0.41.0 — 2026-11-16

- Sign-in is invite-only. An email must be on the allowlist (`bun run allow <email>`, `--remove` to revoke) to receive or use a code; anyone else is told the playtest is invite-only, and no account is created. The script prints which database it wrote to.
- One DM per player. Starting a session while another is live closes the old room first, so its DM saves the summary; nobody can join or invite into a room they don't own. A DM that fails to join returns an error with a retry instead of an empty room.
- Re-entering never speaks a stale recap. A new session waits up to 15 s for the previous one's summary; if it failed or never arrived, the DM greets the player without a recap. A dispatch superseded while waiting steps aside quietly.
- Leave shows the session summary. A solo player's Leave ends the session and the summary screen appears; in a party, the leaver departs with their own summary and a guest becomes host if needed. Leave during creation or onboarding returns home at once. If no summary arrives within 15 s, the app goes home anyway.
- A session is capped at 60 minutes, with a steer toward a resting point at 55. After 5 minutes of player silence, companion chatter and hints stop and the DM checks in once; at 10 minutes the session ends with its summary saved.
- Rate limits live in Valkey and hold across server instances. Signed-in requests count per player; others count per client IP, read from `X-Forwarded-For` behind the HTTPS proxy when `TRUSTED_PROXY_HOPS` is set. A broken limit store fails the request rather than letting it through.
- The native iOS check picks a general iOS runtime and a phone with a Home gesture, not Xcode 27.2's foldable-only runtime.

## 0.40.0 — 2026-11-16

- PR CI runs only the two lint jobs. Tests are proven locally by Proof: a free patch's land runs `scripts/free-acceptance.sh`, which runs Proof's `land` set and then its `sprint` set on the trial-merged tree with the sprint hook's environment.
- A fresh, cache-free `super` run of every declared task runs on this Mac at 02:00 on Tuesday, Thursday and Saturday (`scripts/super-test.sh`, installed by `scripts/super-test-install.sh`). It tests `origin/main` in its own worktree and raises a macOS notification on any red.
- Edits select fewer tests. Docs key no task. A widely imported agent module keys about two representative acceptance tests per family instead of every importer, and a content file keys the tests that declare they read it (`scripts/proof-families.json`). The seed script and migrations also key the tests that name them. Across five probe edits the changed task keys fell from 468 to 117 (`scripts/proof_selection_probe.py`).
- The unused CI service-database mode is gone from the DB lifecycle helpers.

## 0.39.0 — 2026-11-16

- The game runs as containers. `deploy/compose.yml` runs the server, the DM agent and the async worker, plus a one-shot migrate-and-seed job, from three images (`deploy/*.Dockerfile`). The images run as a non-root user and carry no `.env`, tests or mobile sources. `scripts/deploy-up.sh` is the operator's entry point, and `scripts/deploy-smoke.sh` checks the built images locally before a deploy. Nothing in this release creates a cloud resource.
- `GET /api/health` returns 200 when Postgres and Valkey both answer, and 503 naming whichever did not, within a bounded deadline.
- Every deploy migrates and seeds before any serving container is replaced. A failed migration or malformed content stops the deploy with the old containers untouched. Production seeding skips the `player_1` fixture, refuses if fixture rows already exist, validates rows with both the Python and TypeScript catalog parsers before committing, and clears the content caches so the new content is served without restarting the server.
- Narration audio and portraits live under one generated-media directory, set by one variable that all three processes read and backed by one named volume. They survive a container restart and are served by the server whichever container wrote them. The bundled prologue and tracked images still load on a fresh volume.
- A production server, agent or worker refuses to start half-configured and names every missing variable. The mock email transport is refused in production, so `RESEND_API_KEY` is required. `deploy/env.production.example` lists what each service needs, and `.env.example` is complete.
- An unhandled error in the server, agent or worker leaves one JSON line on stderr with the service, time, message and stack, and no tokens, emails or player speech. Compose keeps bounded, rotated logs per service.
- The iOS app can be built for TestFlight against a named server with an EAS profile.

## 0.38.1 — 2026-11-16

- The fast Python lane seeds its dev database after migrating it, so a change to `content/*.json` is tested against matching data at story land instead of the previous seed. The fixture players in `content/players.json` are reset on each run.
- `scripts/teardown-worktree.sh --sweep` works on a machine that also runs unrelated Docker Compose projects. It skips a project with no divineruin ownership labels and still refuses on partial, mixed or malformed ownership.

## 0.38.0 — 2026-11-16

- Session one is a complete episode. A new player answers two questions, meets a companion, fights once, is handed a mystery and a reason to go north, and finds a message from their god waiting afterward.
- Character creation asks for a calling and a name. The first-share roster is four archetypes (warrior, mage, rogue, cleric), three races (human, elari, vaelti) and four patrons (Kaelen, Veythar, Syrath, Aelora). Race defaults to human and the patron follows the archetype; a player who names a race or patron from the roster gets it. The full catalogs are untouched, so the roster widens by editing one list.
- Onboarding is three beats in the market square and ends when the companion has been met. The DM can no longer move the player during onboarding, so play always begins in the square. The companions' `onboarding_suggestion` field is removed from the content and from the Python and TypeScript loaders.
- The wounded rider now arrives for every new player, once, when play begins. He is carrying a wrapped stone shard out of the Greyvale; in the new guild infirmary the sound thins around it and one shadeling condenses. The scene could not fire before: it required a player with no companion, and it listened for a location change that the onboarding handoff never makes.
- When that fight ends, by victory, defeat, flight or de-escalation, the engine gives the player the Veil Fragment and starts "The Greyvale Anomaly". The DM no longer has to decide to start the quest. It happens once, inside the combat-end transaction, and two sessions ending the same fight cannot grant it twice.
- The first fight is one shadeling. Across 20 fixed seeds a level-1 warrior, mage, rogue and cleric with their companion win 20, 19, 19 and 20 fights. Session one pays 25 XP, so the player reaches Millhaven at level 1.
- A patron whisper is generated for the catch-up feed after the first episode, even at zero favor, and only once. This spends one background narration and one voice render per new player. The favor-25 whisper trigger is unchanged.
- Companion hints during the rider scene reach a silent player before any quest is active.
- Fixed: a reconnect could fail its cleanup because a speech handle was scheduled as a task (#625), and proactive speech during a combat handoff could stop all later background hints (#626).
- Three unread entries are removed from `content/events.json` (`market_disruption`, `normalcy_market_task`, `companion_introduction`).
- `docs/milestones/13_first_share.md` lists every step to a friends playtest and `docs/milestones/audit/first-share.md` records the evidence behind them.

## 0.37.0 — 2026-11-15

- The Millhaven leg of the Greyvale arc no longer depends on the DM deciding to advance the quest. Arriving in Millhaven, by walking or by travel, completes "The Road North"; winning the Hollow patrol fight completes "First Blood", whether combat ends through the DM's tool or automatically. Rewards are paid once and roll back with the combat end if anything fails.
- The DM's prompt states what finishes each active quest stage: the encounter to start for a fight, the facts and sources for an investigation, and the exact `update_quest` call for stages the engine does not advance. The unread stage `hints` arrays are removed from `content/quests.json` and the shared TypeScript quest entity; scene-beat companion hints are unchanged.
- The Millhaven patrol is retuned for a level-1 character with a companion: one shadeling and one minion shadeling, no mawling. Across 20 fixed seeds a warrior, mage, rogue and cleric win 20, 17, 17 and 20 fights using only basic attacks. The mawling waits for the ruins.
- Every authored location can be walked to from the Accord market square and every exit has a way back. Five exits were missing, including the ones into Emris's study and Yanna's farmhouse and the road north out of the square. A content check fails if either property breaks.
- Players can rest. The DM's new `rest` tool restores Stamina fully and Focus to half on a short rest, and HP, Stamina and Focus on a long rest, which also records the settlement as the player's anchor. Either rest resets Resonance. It refuses in combat and where the location is not safe, and restores each co-located party member from their own pools.
- A lost fight no longer crashes resurrection with a missing player id.
- New characters are created with their archetype's Focus and Stamina pools. Creation had written neither, so every spell or ability with a cost was refused; migration 063 backfills existing characters without touching pools already spent.
- A long rest restores HP only up to the ceiling left by permanent death penalties.
- The per-player character snapshot sent after a rest goes only to that player, not to everyone in the room.

## 0.36.1 — 2026-11-06

- CI's Python lanes install ffmpeg from a pinned, sha256-checked static build (BtbN month-end 2026-10-31, LGPL 8.1) that is cached between runs, instead of through apt. The Azure apt mirror had stalled that step to the 20-minute job timeout twice in one day. The step is capped at 5 minutes.

## 0.36.0 — 2026-11-06

- Every patron now has its Layer 2 Resonance modifier and its three favor tiers (Acknowledged, Devoted, Exalted) in `content/gods.json`. The Python loader and a new shared TypeScript god entity validate them against one fixture corpus and fail loudly on a bad profile.
- A caster's patron changes their magic. Kaelen's combat spells generate 1 less Resonance. Thyra's generate less on natural ground. Syrath's generate 2 less while hidden. Orenthel's healing generates none. Valdris's are halved against a creature that wronged the party. Mortaen's generate none on a target at 0 HP. Nythera's generate 1 less in a place the caster has never been. No reduction goes below 0. Veythar's arcane casters roll 2 Flickering bonus dice instead of 1. Aelora's spells ignore Veil Ward penalties. At Resonance 9+, a Zhael follower hears two Hollow Echo results and picks one aloud.
- Hiding and grievances are real state. A successful Stealth check hides the player until they cast, attack or fail a Stealth check the DM calls when a watcher might notice. Combat records who struck first, and the DM can mark a broken promise or an injustice with `update_npc_disposition`.
- Thyra's Nature's Pulse is live: advantage on Perception and Survival in natural terrain for every check, discovery, gathering, travel and Choir-search roll. The DM is also cued to narrate ecosystem health without a check.
- A favor loss now whispers only when it drops the player's tier; smaller losses stay silent. Neglect decay is still narrated at session start and on join.
- The Unbound Path works. The DM can tell an Unbound player their exact Resonance. Once per encounter they can push it up by 3 through `activate`, and once per session Veil Mastery turns a Hollow Echo into "Nothing stirs".
- Phase 8 M8.1: 3 open acceptance criteria (was 9). The alignment heartbeat is deferred to its own sprint.

## 0.35.0 — 2026-11-06

- Harvesting follows the bestiary's skill table. Every gated drop names one material kind, and each kind needs exactly one skill and tier (pelts and meat Survival: Trained; glands, venom and rare gems Survival: Expert; construct parts Crafting: Trained; Hollow residue Crafting: Expert; magical components Arcana: Trained; Named fragments and Veil shards Arcana: Expert). A catalog test fails on any drop whose gate disagrees with its kind. cave_gemstone moves to Survival: Expert, named_fragment to Arcana: Expert, and woven_void_fragment to tier 2. Migration 062 turns salvageable_weapon into equipment.
- Every loot drop either appears in a recipe or is marked `crafting_use: "trade"` for later sell values; no drop is both.
- Dispel Corruption purifies a whole tainted stack. The caster names the owner and the item, Focus is spent as for any cast, and the units move to the clean stack in one transaction. Corruption-saturated stone refuses before Focus is spent.
- Artificers can purify tainted units as a timed activity: `begin_activity(kind="purification")` takes the units into escrow at once, and after three skill-practice cycles the worker returns them clean, exactly once even if resolution replays.
- Every creature names its habitat in a required `terrains` list, in Python and TypeScript. Hollow creatures list every terrain for now.
- `build_encounter` composes encounters from the creature catalog by tier, region and terrain. The budget scales with party size and each companion's own HP factor (Sable 0.50, the others 0.75). A mixed-level party uses its mean level. Expected damage per round follows each player's level, so fights fit their difficulty's round window: standard 3–5, tough 4–6, boss 5–7. A request that cannot fit raises a named error. Known gap: player spell and ability damage is not yet applied by the combat engine (debt 6d3b1d6a), so generated fights run longer than certified until it is.
- The DM can start a generated encounter with `enter_mode(mode="combat")` and a difficulty instead of an encounter id, and can look creatures up with `query_info(kind="creature")`. GPT-6 Luna accepted all five changed tool sets in strict mode.
- Phase 7 M7.4 is complete: 0 open acceptance criteria (was 8).

## 0.34.0 — 2026-11-04

- Every location now appears on the HUD map. Seven locations had no map node (Training Hall, Grimjaw's Forge, Grimjaw's Quarters, the Old-Growth Grove, Keldaran Southern Pass, the Tidal Shore and the Reed Marsh), so the map panel silently left them and their routes off. A test now fails when a location has no node, and the location-authoring guide lists it.
- Combat loot honours skill gates. `generate_loot` replaces `derive_role_loot`. A drop whose `requires` the party cannot meet never appears; it is not a failed roll. The gate uses the best tier per skill among the players who fought, so one player's Crafting and another's Arcana can unlock a drop together. A drop authored at chance 1 always drops, even from a Minion, and dice quantities still roll.
- Hollow loot is tainted. Migration 061 keys `player_inventory` by `(player_id, item_id, tainted)`, so tainted and clean units of an item are separate stacks. Drops from a `hollow_residue` loot table land tainted, and other drops land clean. A craft whose recipe does not allow tainted materials never spends tainted units; one that does spends them first. The Python and HTTP inventory snapshots and the mobile inventory panel keep the two stacks apart. Native HUD verification is deferred: Xcode 26.3 cannot build Expo 57 on the Intel Mac.
- The `agent-db` proof provider applies pending migrations to the checkout's dev database, so a story that adds a migration no longer fails land.
- Phase 7 M7.4: 8 open acceptance criteria (was 11).

## 0.33.0 — 2026-11-03

- Playwright runs as proof tasks in the sprint set: `e2e:chromium`, `e2e:web`, `e2e:web-lighthouse` and `e2e:home-character`, which is the representative for `packages/shared` edits. A web-only edit skips the mobile app tests and a mobile-only edit skips the web tests; editing a spec runs only its task. The e2e tasks share one lane because they bind fixed ports. Each keeps Playwright's 4 workers and runs beside acceptance at every core.
- The sprint hook calls only `proof run --set sprint`. A fresh run of all 100 tasks (636 acceptance cases, 88 Playwright tests) took 354 s, about the time acceptance alone took before, against 347 s plus a separate 133 s Playwright run. A red e2e task keeps its log, screenshot, video and trace.
- The four acceptance tests proof could not trace (dynamic imports) no longer run on every change: they key on the agent sources, including the `*_agent.py` modules the verb registry discovers.
- Proof v0.33.2. The milestone "Run only the tests an edit could break" reaches distance 0.

## 0.32.0 — 2026-11-03

- The hooks run proof's selection, not whole lanes. Commit runs staged lint, `proof lint`, then only the commit-set tasks the staged files can break; a repeat commit finds them PROVEN, and a Markdown-only commit runs none. Story land runs the commit and land sets on the merged tree, reusing what the branch proved: a repeat land took 3 s instead of 171 s. Sprint close runs the selected acceptance tasks next to Playwright. `bun run test:all`, `test:python` and `test:acceptance` stay as manual full lanes, and PR CI still runs everything.
- Proof v0.33.0 runs every core; no hook passes `--jobs`. The DB-backed Bun tasks clone a seeded template from one provider Postgres and Valkey.
- The two slowest acceptance files run as several tasks (choir capstone in 3, terrain commands in 3), so a fresh full acceptance run took 347 s, down from 456 s. The generator refuses splits that would leave a test in no part.
- The milestone Measure also counts the hooks that call proof.

## 0.31.2 — 2026-11-03

- `proof` (v0.32.0) also declares the Python tests: `agent-pytest` (the unit lane, in `land`) and one `agent-acceptance:<file>` task per deterministic acceptance file (in `sprint`), generated by `scripts/generate-proof-declarations.py`. An edit reruns the tests that import the changed file directly. A shared module reruns at most three representative tests that import it, and lint and the unit lane cover the rest. An edit to migrations, the seed or the provider reruns everything.
- Proof runs tasks on every core by default; nothing passes `--jobs`. The full acceptance set (92 tasks, 636 cases) took about 6.5 min at 16 jobs on a loaded host, against 618 s for the old serial lane and 1315 s for one-at-a-time proof tasks. The slowest file, `test_choir_capstone` at about 4 min, sets the floor.
- One proof run starts one Postgres (seeded template, cloned per task) and one Valkey (a database per task), and reuses the checkout's LiveKit. Plain `pytest` keeps its own containers.
- The provider refuses to start when the seed imports a module missing from `proof.yaml`'s `seeded-data`, so the shared template cannot change without rerunning every task.

## 0.31.1 — 2026-11-02

- `proof` (v0.27.0) declares the ten Bun test targets: the six packages plus the four DB and Redis server tests as their own tasks. `bunx proof run --set commit` runs only the tasks whose test imports or declared reads changed, and `proof plan` shows the rest PROVEN. Hooks keep their current tiers for now.
- The shared portrait checks test that the files exist instead of asking Git, so they pass in a sandbox without a repository.

## 0.31.0 — 2026-10-13

- Each check runs once, in the cheapest tier that catches it, with measured costs in `.xp/system.md`. Push now only scans outgoing commits for secrets (about 0.1 s, no services). Story land keeps the fast lane, and sprint close runs acceptance and Playwright. PR CI owns full lint and all suites, so free patches lose no coverage; Python and acceptance run as parallel jobs, and acceptance refuses to skip when Docker is missing.
- Acceptance cases that need a fresh database share one Postgres server, each with its own unseeded database: Postgres now starts 3 times per full run instead of 11.
- The nightly test tier is gone; constraints 2 and 13 name commit, story land, push, sprint close and PR CI.
- Meta-tests left the regular runs (tests of hooks, gates, dev tools and the doc indexer). Test code is now 1.87x source, under the 2x bar. Floors that prove a product guard inspected something stay.
- `REMAINING.md` matches the phase docs (331/538) and the content and code it describes.

## 0.30.0 — 2026-10-11

- Elite and Boss Mawlings attack Claw, Dissolution Maw, Claw. The per-role sequence is authored on the catalog row, and both validators reject unknown role keys and unresolvable attack references. Standard Mawlings keep Claw then Dissolution Maw.
- A melee hit from within 5 ft on a Fallen character adds two death-save failures. Ranged hits, save damage and the Dissolution Field tick still add one. A queued strike continues onto a target who fell earlier in the same phase; only damage reaches a Fallen ally, so a hostile mark aimed at one is wasted.
- Story land runs the fast lane (`bun run test:all`) on the merged tree before the merge commits, and keeps the full output in `flake-artifacts/last-pre-merge-commit.log`. Acceptance stays at sprint close.
- `probe_strict_limits.py --provider openai-luna --agent <name>` sends one strict-compile request for one agent with retries off. The combat agent's 9 tools were accepted strict.
- Split `combat_turn.py` into the tool shells and `combat_resolve_phase.py`, and move the down-target rules into `combat_down.py`, which breaks an import cycle through `combat_ability`.
- Source walks in the strict-budget and line-cap tests read tracked files only, ending an intermittent fast-lane failure under parallel runs. Meta-tests of test helpers were deleted; constraint 3 now keeps tests of tests, hooks and tools out of regular runs, and new constraint 13 makes wall clock a quality budget.

## 0.29.0 — 2026-10-11

- Every location carries a physical terrain from one closed ten-value list (Decisions 129–132), mirrored in Python and TypeScript. Seeding and server startup refuse a missing or unknown terrain, or one that does not fit the location's region type. The travel-difficulty field formerly named `terrain` is now `navigation`.
- Primal magic draws on the land: a cast generates its catalog Resonance scaled by the terrain's base (healthy wilds are the baseline), so ancient forest is gentler than a city. Per-spell terrain overrides and the stale "normal" default are gone.
- Korath's earth-anchored −1 primal Resonance applies only on earth or stone, not coast or wetland. The Druid's Veil Ward is refused off natural terrain and costs 3 Focus instead of 5 in ancient forest.
- Combat resolves its terrain once at the start and keeps it with the fight; casts and wards mid-combat never look the location up again. A combat at a location without terrain refuses to start.
- Four new wilderness locations give every terrain a real place: the Old-Growth Grove (Thornveld), Keldaran Southern Pass, the Tidal Shore and the Reed Marsh (Sunward Coast). `world_data_simulation.md` gains an "Authoring a Location" guide.
- Free test lanes can no longer bill a paid provider: an unapproved request to Anthropic, OpenAI, Deepgram or Inworld is refused and fails the test, even when the calling code swallows the error.
- The agent dev-command boot check allows a loaded four-core machine time to start.

## 0.28.0 — 2026-10-08

- Mawlings declare their authored Claw then Dissolution Maw multiattack as one declaration with per-strike targets. Each strike keeps its own held reaction window across pauses and reloads; an unavailable strike drains unresolved, with no retargeting. Minion Mawlings keep a single attack.
- Dissolution Maw applies its CON DC 13 held-item durability rider to a DM-selected, equipped player item, chosen from target-scoped inventory facts that include guests. Role DC modifiers apply, and companions are excluded. Both validators reject riders on save- or condition-resolved attacks.
- A living ally grappled by a living, able Mawling takes 1d6 necrotic Dissolution Field damage at its turn start, even when stunned, Fallen or omitted from declarations. Damage to a Fallen character now adds one automatic death-save failure.
- Reaction spends checkpoint in the same transaction as their resource debit, so a reload cannot re-spend them. The checkpoint save refuses to run without the combat-state lock.
- Split XP roles across model families: codex plans and executes, and Claude reviews plans and diffs.

## 0.27.0 — 2026-10-04

- Adopt the v1 development constraints: test production behavior once at the outermost useful boundary, retire duplicate unit coverage, and remove documentation wording checks and test meta-checks.
- Keep pushes service-free with local lint and Bun tests. Run the full suite at sprint close; free patches use focused acceptance and normal PR CI.
- Reduce tracked test lines from 177,625 to 160,505 and the test/source ratio from 2.2106× to 1.9991×. Preserve unique behavior checks while removing redundant tests, setup, and commentary.
- Make the live material-inventory acceptance check independent of Bun's compact diagnostic output.
