# Agent Verbs & Stages — Tooling and Context Architecture

> **Status: DRAFT.** Settled principles and open decisions are marked explicitly.
> This doc is the design source for the Phase-2 "enabler" refactor milestones in
> `execution_plan.json`. It refines (does not replace) the three-layer prompt model
> in `technical_architecture.md` (§System Prompt: Static + Warm Layers, §Per-Turn
> Hot Layer) and **evolves** the tool-scaling decision in
> `docs/decisions/0004-agent-tool-scaling.md`. The headline decision is recorded as
> **`docs/decisions/0007-verb-stage-resolve-tooling-model.md`** (ADR 0007).

## 1. Why this exists (the problem)

We are hitting limits that are all the same limit wearing different hats:

- **Tool ceiling.** `CITY_TOOLS` sits at `MAX_STRICT_TOOLS = 20` (`llm_config.py`). M2.4
  spell tools cannot be added without reclaiming a slot. 21+ is a hard Anthropic 400
  (ADR 0004). *(debt `e665104c753a`)*
- **Duplicated consequence logic.** `quest_tools.update_quest` hand-rolls a copy of
  `progression_tools._award_xp_impl`'s level-up logic and silently drops the L10/15/20
  auto-grants and the L5 fork cue. *(debt `ee947a154b10`)*
- **Consequences reachable as decisions.** `_resolve_milestone_impl` still applies
  L10/15/20 grants despite its docstring saying `award_xp` owns them — two paths to one
  effect, so they drift. *(debt `2bba66ace8a8`, concerns `2ff6a9a9ab10`/`b96ddddf6542`)*
- **Tool growth tracks content.** Every new "thing" (recipe, spell, item) tends to add a
  new tool (`learn_recipe`, future `learn_spell_from_scroll`, …).

These are symptoms of the tool/context boundary being drawn at the wrong level. The fix
is to draw it where each side's strengths actually live.

## 2. The core model: Sense / Act / Resolve

Every operation in the game is one of three kinds. Drawing the boundary here is the
whole point.

| Kind | Who owns it | What it is |
|---|---|---|
| **Sense** | the world (deterministic) + the LLM's choice to look | information that informs a decision |
| **Act** | the user and the LLM (judgement) | a decision made at a genuine decision point |
| **Resolve** | the rules engine (deterministic) | the mechanical fallout of an Act — and it is **never a tool** |

The LLM's job is **judgement + narration**. The rules engine's job is **deterministic
computation**. A tool exists only where there is a genuine decision (an Act). Everything
that "just happens" as a consequence is a Resolve and has no tool surface.

> This sharpens Golden Rule 3 ("rules engine deterministic; LLM decides *when* to invoke
> and *how* to narrate") rather than changing it. The rules engine is already pure; the
> gap is that consequences leaked up into LLM-invoked tools.

## 3. Sense has two channels: push (the Stage) and pull (`query`)

Information reaches the judgement layer two ways — the same function, delivered
differently:

- **Push — the Stage.** Ambient context the LLM didn't have to ask for, assembled by the
  async workers from the DB into the warm/hot prompt layers. *What's true and actionable
  here, now.*
- **Pull — `query`.** On-demand lookup for something the Stage doesn't carry.

The line between them is a **cost/latency optimization per datum**, not an arbitrary one:

> Predictable + frequently-needed + latency-sensitive → **push** into the Stage (no
> round-trip; the 1500ms budget can't afford fetching what you predictably need).
> Rare + branch-specific → leave as a **pull** (`query`) to keep the Stage lean.

This gives three independent levers on the tool ceiling, not one:
1. Collapse Resolves into Acts (removes consequence-tools).
2. Promote predictable reads into push-context (removes redundant `query_*` tools).
3. The remaining genuine pull-tools are few.

## 4. Acts are verbs, never nouns

**Settled.** Tools represent *decisions*, and the variation between similar operations
lives in **data**, not in **new tools**. Two tests bound the tool set:

- **Decision test.** Is there a choice here — by the user, the LLM, or the world? No → it
  is a Resolve, not a tool.
- **Verb test.** Would a content author adding new *data* (a spell, recipe, ability, item)
  need a new tool? If yes, the tool is a *noun* — wrong. Same decision on different data →
  **one verb, parameterized by a typed target** resolved against content/DB.

### Description discipline — each carrier holds exactly one thing

Tool descriptions become novels when they carry judgement + effects + valid-target
catalogs at once. Split the load:

| Carrier | Carries | Does NOT carry |
|---|---|---|
| Tool **name** | the verb / the decision | — |
| Tool **description** | *when* to reach for it (1–2 sentences) | effects; the catalog of valid targets |
| Tool **schema** | the typed payload shape | prose |
| The **Stage** | what's available to act on right now (the targets) | — |
| The **rules engine** | what happens as a result (the Resolve) | — |

A verb's description never enumerates its targets — the Stage supplies them. `go`'s entire
description is "the player moves somewhere"; the Stage lists the exits.

### Standard Act shape

```python
@function_tool
async def <verb>(context, target: <TypedRef>, *<decision_params>) -> ActResult:
    """<When the DM should make this decision. 1–2 sentences. No effects, no target catalog.>"""
```

`ActResult` is a **standard return envelope** every Act shares (`{narration_cues,
state_changes}`). Uniform shape = the LLM learns one pattern. The Resolve fires inside the
Act, writes the DB, and emits the event that updates the Stage.

## 5. Resolve is never a tool

**Settled.** A Resolve is the deterministic body that runs *inside* an Act: rules-engine
call → DB write → event emit. The LLM never invokes a Resolve directly because there is no
decision there.

The canonical proof lives in the codebase: `resolve_milestone` conflated two things and
should be **removed as a tool entirely**:

- **The grant** (L5/10/15/20) → pure consequence → a Resolve inside `award_xp`/`advance_quest`.
- **Presenting the L5 fork** → *not* a verb either; the level-up Resolve surfaces a **pending
  choice** in its response and parks it in the Stage (offering a choice is a Resolve output,
  like a narration cue).
- **The player's pick** → the only decision → the generic **`select`** verb, which resolves
  *any* pending choice (an L5 fork today, a branching quest decision tomorrow).

`award_xp` and `award_divine_favor` likewise become Resolves inside the Acts that trigger
them (`advance_quest`, combat exit).

**Resolves must report back richly.** "Just happens" must not mean "happens invisibly" —
the DM has to narrate it (audio-first). Every Resolve returns narration cues for the
current turn *and* emits an event so the ongoing Stage reflects the new reality.

## 6. Agents vs Stages — two axes, very different costs

**Settled.** "Agent" and "Stage" are separate axes and must not move together.

- **Stage** = the warm/hot context (what's true/actionable here, now), assembled by async
  workers from the DB. Changing it is **cheap and fluid** — it's designed to change every
  turn.
- **Agent** = a tool set + cold prompt + model + lifecycle. Crossing an agent boundary is
  **expensive**: the new cold prompt is a fresh prompt-cache prefix (cache miss → higher
  TTFT, the latency bottleneck; the 90%-savings cost model depends on staying cached),
  plus `on_enter` lifecycle work.

The cost of an agent boundary scales with **how often you cross it**.

> **Rule.** Stage granularity = as fine as you like (room-level), driven by the player's
> exact location. **Agent granularity = coarse, and tracks *mode of play* (the verb set),
> not space.** You switch agents when *what the player can do* changes — not when they
> walk through a door.

**Agent-vs-Stage test for a location:** (1) does entering it change the *verbs*? (2) will
the player *stay long enough* to amortize the handoff? Both yes → agent (e.g.
`BlacksmithAgent` adds `repair_item` and you stay; Combat adds the fight verbs and you
stay). Only flavor/NPC/description changes → it's a **Stage** change on the same agent.

### Consequence: collapse the region agents

City/Wilderness/Dungeon differ today by small tool deltas plus narration register. Under
the verb model those deltas become core verbs or Stage fields:

- inventory → `transact` (core); disposition → core; blacksmith → `enter_mode` (core)
- region type (city/ruin/wild) → a **Stage attribute** (`region_type` already exists)
- narration register → **Stage content**: the cold persona stays "you are the DM"; the
  per-place register moves to the warm layer. `scene.instructions` *already carries this*
  (e.g. the Guild Hall scene: "guide toward Torin or the board; professional but
  welcoming").

Result: **one exploration agent** (core verbs, cold prompt cached all session, never
thrashed) fed by a fine-grained, location-aware Stage; **mode agents** (Combat, Downtime,
verb-changing locations like Blacksmith) entered via `enter_mode`. Fewer agents, finer
stages.

Coarse, significant spatial boundaries can still earn an agent when the *interaction model*
changes — e.g. the **Hollow** (Golden Rule 7: intentionally breaks audio/voice norms).

## 7. The Stage in detail

### Tiers (refines technical_architecture.md)

- **Cold (static, cached all session):** DM persona, mechanics reference, the core verb
  set, static character facts. Location-independent.
- **Warm (rebuilt by the background process on arrival/events, cached between rebuilds):**
  the *location* — see schema below.
- **Hot (fresh per-turn DB read, ephemeral):** who's being addressed, the result of a
  `check` just made, a proactive `beat` now due, a pending player-facing choice,
  threshold-crossing resource bands, and **newly revealed affordance targets** — a
  discovered exit, item, or feature appears here the moment a Resolve reveals it, before
  the warm layer rebuilds (the §8 coherence guardrail in action).

### Placement discriminator

> **Does the LLM or player make a different *decision* knowing this? Yes → Stage. No → it
> is Resolve-internal, owned by the rules engine, consumed inside the verb.**

This splits the character sheet three ways:

| What | Where | Why |
|---|---|---|
| Static facts (name, race, class, fixed traits) | Cold | narration flavor; never changes |
| Decision-relevant dynamic state (current Stamina/Focus, HP, conditions, level) | Warm/Hot | the player decides whether to spend/risk these |
| Resolution math (skill modifiers, proficiency, save DCs) | **Rules engine — never Stage** | consumed inside `check`/`activate`; changes no decision |

Example: current Stamina **is** Sense (you decide whether you *can* `activate`); the
perception modifier **is not** (you decide to search regardless — success is computed).

### Numbers vs bands (audio-first)

**Settled.** Golden Rules 1 + 2: **the HUD shows the numbers; the voice never speaks them.**
And the LLM never *gates* on resources — the Resolve does — so it never needs the integer.

- Player: "I use Power Strike" → `activate(power_strike)`. The Resolve checks the *real*
  Stamina vs the *real* cost and deducts or refuses ("your arms are leaden — nothing
  left"). The LLM didn't need "6 vs 3".
- The exact number lives **only** in the rules engine and the HUD. The Stage carries a
  **narrative band**, surfaced **only when it crosses a threshold worth narrating**.

| Domain | Stage (voice) | Engine + HUD (exact) |
|---|---|---|
| Stamina/Focus | "winded," "nearly spent" | 6/8 |
| HP | unhurt → bloodied → critically hurt → down | 14/30 |
| Divine favor | "the patron is pleased / distant" | favor level |
| Quest | the current beat | stage index |
| Time | "late afternoon" | 16:00 |

*(Open: commerce/pricing — see §12.)*

### `check(skill, visible_target)`

**Settled.** A check mirrors what the *player* expressed: a **visible target** from the
Stage + an **approach** (skill the DM infers). The hidden element's id is the Resolve's
**output on success**, never an input — otherwise the secret has already leaked and the LLM
would be deciding to reveal it.

```
check(perception, notice_board)  → Resolve: which hidden_elements scope to the board?
                                   roll vs DC → reveal guild_notice_greyvale on success
check(athletics, north_wall)     → climb attempt
check(persuasion, torin)         → social check
```

`discover_hidden_element` therefore folds into `check` and disappears as a tool.

**Hidden elements associate to a visible target in data.** Each `hidden_element` declares
the visible thing it hangs off (an `attaches_to`: a `key_feature` id or an exit), so
`check(skill, target)` scopes precisely — examining the research station can surface the
journal beneath it; examining the inner door cannot. (Migrating existing content: where a
hidden element names no feature, fall back to room-wide-by-skill until it's annotated.)

**Gated traversal is a check; `go` stays pure.** A locked/sealed exit (e.g. the dungeon's
`deeper` door, `requires: veythar_seal_mark.discovered || arcana:14`) surfaces as a **check
target**, not a `go` affordance. `check(arcana, sealed_door)` succeeds → its Resolve
unlocks the exit (and the new `go(deeper)` affordance appears in the hot layer immediately)
→ `go(deeper)` is then a plain move. `go` never embeds a mechanic. This is the canonical
Act→Resolve→Stage example: a `check` Resolve flips a discovery flag that re-renders the
exit set.

### Affordance-structured warm layer

Present the Stage's nouns **grouped by the verb that consumes them**, so the agent's
instructions shrink to "verb meanings + voice" and "what can I do here" becomes
deterministic data:

```
NARRATION:   <register from scene.instructions + location description/atmosphere>
AFFORDANCES:
  go            → <ungated exits>                    (gated exits appear under check until unlocked)
  enter_mode    → <agent_context exits, as a choice> (player decides — no auto-handoff)
  address       → <entities_present, with voice_id for ventriloquism>
  advance_quest → <quest hooks here>
  check         → <visible targets: key_features, gated exits, examinable entities>
SCENE:         <ambient audio · time-of-day · danger band · relevant quest beat>
BANDS:         <only resources that crossed a threshold, as words>
```

Newly discovered/revealed targets join the relevant affordance group via the **hot** layer
the moment they're revealed; the warm layer absorbs them on its next rebuild.

**Affordances are grounding, not rails.** This is a freeform voice RPG — the player can try
anything; off-list intents still map to a verb (often `check`/`query`). The list must never
*limit* the player. And the DM narrates prose, never reads the menu aloud (Golden Rule 1).

### Stage schema (validated against Guild Hall + dungeon room + mode-location)

Field set the warm layer emits for every location. Pressure-tested against a quiet quest
hub (Guild Hall), a dungeon room with gated exits + hidden elements (Greyvale Entrance),
and a mode-location (Training Hall, `agent_context`). The schema held; it grew gated exits,
hidden→target association, and a danger band, and generalized `npcs_present` → entities.

```
place:        id, name, region_type, district, tier, danger (BAND, not the integer)
description:  condition-evaluated prose + atmosphere
              (conditions key off time-of-day AND world-state vars, e.g. hollow_corruption;
               modifiers are additive)
register:     scene.instructions  (may be absent — then narrate from description/atmosphere)
affordances:  go(ungated exits),
              enter_mode(agent_context exits, presented as a choice),
              address(entities_present[+voice_id]),
              advance_quest(hooks),
              check(visible targets: key_features, gated exits, examinable entities)
scene:        ambient audio, time-of-day, relevant quest beats
bands:        threshold-crossing resource state, as words
```

Content-schema implications surfaced by the test (feed the migration milestones):
- `hidden_element.attaches_to` — the `key_feature` id or exit it hangs off (scopes `check`).
- `exit.requires` — a gate (discovery flag and/or skill check); gated exits render as
  `check` targets, not `go` affordances, until unlocked.
- "present entities" generalizes past *scheduled NPCs* to *threats/hazards*; hostiles route
  to `enter_mode(combat)` with enemies sourced from `encounter_templates` (not a location
  present-list).

## 8. The loop and the three actors

```
Stage (push + pull) → Decide → Act → Resolve (DB write + event) → workers update Stage → …
```

Three decision sources, by design:
- **User** — intent via voice.
- **LLM/DM** — reactive judgement + narration.
- **World** — async workers (simulation tick, background process) that maintain the Stage
  and can **proactively act** (inject DM speech via `beats`/proactive events) with no user
  turn.

**Coherence guardrail (Golden Rule 4).** The DB is the source of truth; the hot layer is a
fresh per-turn DB read. A Resolve is *immediately* true in the hot layer and *eventually*
true in the warm layer. Never let the warm layer be authoritative for anything a decision
turns on. The Stage is **assembled by code, never authored by the LLM**.

**This loop already exists in code.** Acts publish `E.*` events to `event_bus.py`; the
background process drains them each tick (`background_process._run()`), maps them via
`bg_event_handlers.handle_events()` to a `needs_rebuild` decision, and rebuilds the warm
layer. The refactor *standardizes* this (every Resolve publishes its event) rather than
inventing it — see §12.4.

## 9. Worked example — the Accord Guild Hall

Real content (`content/locations.json`, `npcs.json`, `scenes.json`):

```
COLD:  DM persona · mechanics · core verbs · static character facts
WARM (the Guild Hall):
  place:        Guild Hall (region_type city · district accord_central · tier 1 · danger 0)
  description:  "Heavy oak doors open onto a hall that smells of lamp oil, leather,
                 and old paper…"  (night → condition override)
  register:     "Adventurers get assignments here. If no active quest, steer toward
                 Torin or the board. Professional but welcoming."   (scene.instructions)
  AFFORDANCES:
    go            → south: Market Square · north: Training Hall  [enter_mode: training]
    address       → Torin (giver, voice torin_v1) · Valdris · Dara
    advance_quest → greyvale_anomaly (via Torin)
    check         → (nothing hidden here)
  scene:          ambient guild_hall_bustle · daytime · greyvale_anomaly @ stage N
HOT:   who's being addressed · a check result · a due beat (companion hint @45s) ·
       a pending L5 fork · threshold resource bands
PULL (query only): Torin's backstory · faction politics · full quest text · pricing ·
       stat blocks · other rooms
```

The mechanisms are **already in the data**: `agent_context` (location-confers-a-mode),
`conditions` (dynamic overrides), `scene.instructions` (per-location register), `schedule`
(presence resolution), `beats` (proactive hints). The refactor mostly *promotes* these into
the warm/hot layer consistently and *deletes* the per-region agent prompts that duplicate
them.

## 10. Verb vocabulary

### Core verbs (the exploration agent)

| Verb | Decision | Replaces |
|---|---|---|
| `query` | I need info not in front of me | `query_info` (+ option-lookups → mostly Stage) |
| `go` | the player moves | `move_player`, `enter_location` |
| `check` | resolve an uncertain action | `request_skill_check`, `request_saving_throw`, `roll_dice`, `discover_hidden_element` |
| `advance_quest` | a quest moves forward | `update_quest` (+ folds in the XP/level/milestone Resolve) |
| `transact` | physical goods change hands (gain/lose/spend, with quantity) | `add_to_inventory`, `remove_from_inventory` |
| `learn` | the player gains permanent knowledge | `learn_recipe`, future `learn_spell` |
| `activate` | the player uses a capability | `request_ability_activation`, all future spellcasting |
| `set_disposition` | an NPC's standing shifted | `update_npc_disposition` |
| `select` | the player resolves a pending choice | the L5-fork path of `resolve_milestone`; generalizes to any pending choice |
| `enter_mode` | play shifts into a focused context | `start_combat`, `enter_dispatch`, `enter_blacksmith` |
| `record_moment` | mark something memorable | `record_story_moment` |
| `end_session` | wrap the session | `end_session` |

**Core verb set = 12** — the *exploration agent's* shared vocabulary, not a global cap.
Mode agents (Combat, Dispatch, Creation, Onboarding) add their own verbs on top and reuse
the core verbs they need (see "Mode-local verbs" below), so total distinct verbs across the
game is more than 12 — but no single agent carries the union, so each stays well under the
strict-20 ceiling.

Folded entirely (no verb):

- **Ad-hoc XP `reward`** — dropped. All XP rides inside `advance_quest` / combat-exit
  Resolves; no LLM-initiated spontaneous XP. Matches modern tabletop (which moved from
  ad-hoc XP to quest/milestone XP + non-mechanical recognition) and avoids reward inflation.
- **Divine favor** — accrues deterministically inside patron-aligned Acts (`advance_quest`).
  A narrow *player-initiated* `devote`/`pray` Act is a possible later addition — player-, not
  LLM-, initiated, so it doesn't reintroduce the inflation risk.
- **Audio** — `play_sound` + `set_music_state` dropped. Ambient soundscape derives from the
  location (`ambient_sounds`) via Stage assembly; discrete SFX derive from events as
  Resolves; the DM's voice carries any other punctuation.
- **`resolve_milestone`** — removed. Milestone grants are Resolves inside
  `award_xp`/`advance_quest`; the L5 fork is surfaced as a pending choice in the level-up
  Resolve's response + the Stage; the player's pick is the generic `select` verb. Presenting
  a choice is a Resolve output, not a verb.

### Mode-local verbs (off the core list)

- **Combat:** `attack`, `enemy_turn`, `death_save`, `exit_mode` (= `end_combat`); shares
  core `activate`.
- **Downtime/Dispatch:** `begin_activity(kind)` (= `initiate_training_cycle` +
  `dispatch_companion_errand` + `start_crafting_project` + `rent_workspace` +
  `experiment_with_materials`), `resolve_activity(id, decision)` (= `resolve_training_midpoint`
  + `resolve_companion_errand`); shares core `acquire`/`go`/`query`/`exit_mode`.
- **Creation / Onboarding:** separate constrained modes; same standard applies internally,
  deferred.

**Payoff:** a region agent built from the core carries ~12 verbs vs City's 20 today — and
**M2.4 adds zero tools**: spell acquisition is `acquire(spell, id)`, casting is
`activate(id)`. Spells become content, not tool surface.

## 11. Migration sequence (green throughout)

The two original Phase-2 enabler milestones become the **bookends**:

1. **Resolve consolidation + `select`** — extract `_award_xp_core`; route `update_quest`
   through it; **remove `resolve_milestone`** (grants become Resolves; the L5 fork is surfaced
   as a pending choice in the level-up response + Stage); add the generic `select` verb to
   resolve pending choices. *(closes `ee947a154b10`, `2bba66ace8a8`, concerns
   `2ff6a9a9ab10`/`b96ddddf6542`)*
2. **Verb consolidation** — collapse noun-tools into verbs (`transact`, `learn`,
   `enter_mode`; fold `discover` into `check`; fold `award_xp`/`award_divine_favor`/`reward`
   and audio into Resolves/Stage). Drops City below the ceiling.
3. **Stage schema** — affordance-structured warm/hot layer + banding; promote
   `scene.instructions` register into the Stage. *(finalizes the schema after pressure-test)*
4. **Exploration-agent collapse** — City/Wilderness/Dungeon → one agent on the Stage.
   *(the agent-types/CityAgent split; also closes the DispatchAgent tap gap `15da0e89fa97`)*
5. → existing **M2.4 Spell Acquisition** proceeds with zero new tools.

## 12. Decisions (resolved) and deferrals

All design seams from the working sessions are resolved or explicitly deferred to the phase
that builds the relevant surface. **None remain blocking the migration milestones.**

### Resolved

1. **Verb granularity** — `go` absorbs `enter_location` and stays pure (gates are checks).
   Goods vs knowledge → split `transact` + `learn`. `reward` folded entirely. `record_moment`
   kept as an Act. Audio fully Stage/Resolve-driven. Core verb set = 12 (§10).
2. **Stage-schema field set** — validated against Guild Hall + dungeon room + mode-location
   (§7): `hidden_element.attaches_to` a visible target; gated exits are `check` targets
   (`go` stays pure); mode-locations present `enter_mode` as a player choice (no
   auto-handoff); danger is banded; revealed targets surface via the hot layer.
3. **Commerce/pricing** — band in voice, exact figure + confirm on the **HUD**; `transact`'s
   Resolve owns prices (`content/pricing.json`). Commerce is **not** a voice-numeric
   exception — it's the HUD doing its job (Golden Rule 2).
4. **Event-wiring** — the Act→Resolve→Stage loop already exists: `event_bus.py` →
   `background_process._run()` → `bg_event_handlers.handle_events()` (returns `needs_rebuild`)
   → `_rebuild_warm_layer()`. Standard: **every Resolve publishes its `E.*` event**;
   affordance-affecting events (`LOCATION_CHANGED`, `QUEST_UPDATED`, `INVENTORY_UPDATED`,
   `DISPOSITION_CHANGED`, `HOLLOW_CORRUPTION_CHANGED`) flip `needs_rebuild`; the hot layer is
   the same-turn backstop. **One addition:** `E.HIDDEN_REVEALED`, emitted by `check` on a
   successful discovery → hot-layer reveal this turn + a warm rebuild.
5. **Model selection** — one model for the exploration agent (Haiku, routine). Interaction
   complexity rides the **mode-agent boundary** (Combat/Creation may use Sonnet), preserving
   "Sonnet for complex" (Golden Rule 5) without per-turn switching. Per-turn escalation is a
   documented future option, not built now.

### Deferred to their phase (insertion point noted)

- **Multiplayer warm-layer merge** — not designed now (Phase 2 is single-player; the
  multiplayer architecture doesn't exist yet). Insertion point: the schema's
  `entities_present` is where co-located party members slot in, and the DM addresses the
  group from it. Designing the merge belongs in the multiplayer phase.
- **Hollow interaction-mode hook** — a location that *rewrites the interaction model*
  (Golden Rule 7) needs a declaration beyond `agent_context` activities (e.g. a location
  `mode` routing to a special agent). Decided when the Hollow is built.
- **Player-initiated `devote`/`pray` Act** — for spontaneous divine-favor accrual; decided
  when the divine-favor surface is built (player-, not LLM-, initiated, so no inflation
  risk).

## 13. Relationship to the Golden Rules

- **Audio-first (1):** bands not numbers; affordances are grounding, narrated as prose.
- **DM is the game (2):** Sense feeds judgement; HUD carries exact numbers the voice omits.
- **Deterministic mechanics (3):** Resolves are pure and tool-less; this doc sharpens the
  rule at the tool boundary.
- **State in the database (4):** the Stage is assembled from the DB, never authored by the
  LLM; hot layer is the freshness backstop.
- **Cost conscious (5):** coarse agents keep the prompt cache warm; the push/pull line is a
  cost/latency optimization.
- **Latency budget (6):** push predictable context so decisions don't pay a fetch round-trip.
- **Hollow breaks rules (7):** a legitimate reason for a distinct agent (interaction model
  changes).
