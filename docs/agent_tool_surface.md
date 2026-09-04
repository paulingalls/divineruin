# DM Tool Surface and Context Timing — Design

Date: 2026-09-04. Measured against trunk `08fa9b8` (a `git archive` snapshot outside
the repo; nothing in the repo was touched). Written for story-019 ("re-enable strict
tool schemas under the 16 union-typed-parameter limit"; the body of the ADR-0004
addendum still calls it story-016, corrected in that addendum's ADR-0008 paragraph)
and for the "right information / right action at the right time" question behind it.

Story-019 runs FIRST: it is in Sprint 47 and the M29 reaction restore (016/017/018,
which reshapes `declare_phase`/`resolve_phase`) is Sprint 48, moved out because combat
400s on every real turn until strict fits. So 019 does not wait for the restore and
must not hand-pin the counts below — its budget test walks the emitted schema (section
5 step 1, appendix), and Sprint 48 re-runs that walk against the reshaped payloads.

---

## 0. Summary

1. **The verb/noun model is the right model and it scales. What did not scale is the
   payload shape.** Folding nouns into verbs turned each verb into a bag of optional
   parameters (a *product type with nulls*). Anthropic's strict-mode grammar compiler
   charges per optional, exponentially. The fix is one rule: **verbs take sum types**
   (a single `anyOf` of kind-tagged variants with only required fields). Probed live:
   an `anyOf` of 17 variants costs **one** union slot; the same information as 17
   optionals is a 400.
2. **Exact limits, verified today on Haiku 4.5** (section 2): 20 strict tools per
   request; 16 union-typed parameters per request across all strict tools, counted
   recursively (nested objects, array items, variants); a per-object cliff around 13
   nullables ("Schema is too complex"); `additionalProperties` must be `false`;
   `enum` with a null member is rejected; `oneOf` is rejected; non-strict tools count
   toward none of this, and strict and non-strict tools mix freely in one request.
3. **After reshaping, every agent lands at 2–4 unions** (from 17 / 13 / 23), with
   headroom of one union per future polymorphic verb. The union cap and the tool cap
   then bind at the same place, about 16 verbs per agent, which is also where LiveKit
   and Anthropic say selection accuracy starts to degrade. One budget, one number.
4. **Right action at the right time is a state-machine problem, not a tool-list
   problem.** Do not swap tool sets per turn (it thrashes the prompt cache; math in
   4.4). Keep one fixed tool list per mode agent, enforce legality in tool bodies
   (already done), and *tell* the DM the current phase and the legal verbs in two
   places: a small per-turn `NOW` block in the hot layer, and a `next` field in every
   tool result. This generalizes constraint 6 ("name the producer") to every state
   transition.
5. **Right information at the right time** follows one placement rule: put each datum
   in the layer whose refresh rate matches its volatility (cold = session, warm =
   event, hot = turn, result = call). Two current violations to fix: `ACTIVE COMBAT`
   is rendered in the warm layer where it goes stale after round 1, and
   `enter_location` pulls what the Stage already pushes.
6. **Do not reach for tool search / ToolProxy.** Both add a round trip inside the
   1500 ms budget and (in the LiveKit beta) route calls through a non-strict
   `call_tool(parameters: object)` that bypasses every guarantee you are trying to
   restore. They are the answer to "hundreds of tools", which this game never needs.

---

## 1. What trunk sends today

Measured with `llm.ToolContext(tools).parse_function_tools("anthropic", strict=True)`,
the exact call the plugin makes (`livekit-plugins-anthropic` 1.6.1 → `to_fnc_ctx`).

| Agent | Tools | Unions | Strict JSON | Worst offenders |
|---|---|---|---|---|
| exploration | 14 | **17** | 12.5k chars | `check` 9, `activate` 2, `travel` 2, `enter_mode` 2, `query_info` 1, `transact` 1 |
| combat | 9 | **13** + hard reject | 9.6k | `declare_phase.declarations` is `additionalProperties: object` (400 regardless of count), `check` 9, `activate` 2, `request_death_save` 1, `query_info` 1 |
| dispatch | 9 | **23** | 9.3k | `begin_activity` 11, `check` 9, `resolve_activity` 1, `learn` 1, `query_info` 1 |
| onboarding | 6 | 10 | 5.8k | `check` 9, `query_info` 1 |
| blacksmith | 3 | 1 | 2.5k | `query_info` 1 |
| creation | 3 | 0 | 1.1k | — |

Where the unions come from: every Python default (`skill: str = ""`, `dc: int = 0`,
`target_id: str | None = None`) becomes `"type": ["string", "null"]` in the strict
converter (`livekit/agents/llm/_strict.py`). `check` alone carries nine because its
six modes were flattened into one parameter list.

Other things worth knowing about the current request shape:

- Static system prompts: exploration ~3.2k tokens, combat ~2.7k, dispatch ~1.4k. Tool
  JSON adds ~3.1k tokens on exploration. Descriptions are the "novels" ADR-0007 warned
  about: `activate` 1616 chars, `check` 1363, `query_info` 1192; they carry target
  catalogs and rules that belong in the schema and the Stage.
- Gameplay model is `claude-haiku-4-5-20251001`; creation is
  `claude-sonnet-4-20250514` (an old snapshot, not this doc's concern, but it is the
  one place an outdated model id lives).
- `max_tool_steps` is the LiveKit default (3). Combat's declare → activate(reaction)
  → resolve → death_save chain can exceed it in one turn; the framework then makes a
  final tool-less call. Set it explicitly on the combat session.
- Hot-layer messages are added to a *temporary* chat context in
  `on_user_turn_completed` and are not persisted, so each turn's prefix diverges from
  the previous request at the hot block. Only the tail (hot + user + reply, a few
  hundred tokens) misses the cache; tools and system stay cached. Acceptable.
- Strict is interim-OFF via the private `_strict_tool_schema=False` (ADR-0004
  addendum). The `RawFunctionTool` path in the plugin is *always* non-strict, which
  means a per-tool escape hatch already exists without touching the kwarg (4.5).

---

## 2. The limits, precisely

Probed 2026-09-04 with 1-token `messages.create` calls on `claude-haiku-4-5-20251001`
(design-session scratch, not kept in the repo — see the appendix). Note that
`count_tokens` validates schema *shape* only; the grammar limits fire only on
`messages.create`.

| Probe | Result |
|---|---|
| 17 nullable params in one tool | 400 "Schemas contains too many parameters with union types (17 parameters with type arrays or anyOf). This causes exponential compilation cost… (limit: 16 parameters with unions)" |
| 9 + 9 nullable across two tools | 400, same message (18) — **the limit is per request** |
| 17 nullable inside a nested `params` object | 400 (17) — **nested counts** |
| 17 nullable inside array `items` | 400 (17) — **array items count** |
| `anyOf` of 17 kind-tagged variants, all fields required | **OK** — a discriminated union is **one** union |
| `anyOf` of 6 variants + 16 nullable | 400 (17) — the `anyOf` param itself counts as 1 |
| 2 variants each holding 1 nullable + 14 nullable, variants written **inline** | 400 (17) — **nullables inside inline variants count individually** |
| 17 nullable inside variants reached by `$ref` into `$defs` | **OK** — the counter does not traverse `$ref`; 20 in one such variant is also accepted, so the per-object cliff does not traverse it either. This is the shape the LiveKit converter emits (4.1), so the API will NOT catch a violation of rule 2 |
| `additionalProperties: {type: object}` / enum-with-null / `oneOf` **inside** a `$ref`'d variant | 400, same messages as their top-level rows — these three DO traverse `$ref`, so a budget walk that stops at `$ref` misses live 400s |
| 17 required `enum` strings | OK — enums are not unions |
| `enum: ["a","b",null]` with `type: ["string","null"]` | 400 "Enum value 'a' does not match declared type" — **`Literal[...] \| None` is unusable** (this is exactly what the LiveKit converter emits for it) |
| `oneOf` | 400 "not supported" (the converter rewrites pydantic's `oneOf` to `anyOf`, so this only bites raw schemas) |
| `additionalProperties: {type: object}` | 400 "set additionalProperties to false" — **no free-form dicts** |
| `declarations: array of anyOf[attack, ability, defend]` | **OK** |
| 12 nullable in one object | OK |
| 14 or 15 nullable in one object | 400 "Schema is too complex." — **per-object cliff at 13ish**, separate from the 16 cap |
| two sibling objects with 8 nullable each | OK — the complexity check is per object |
| 21 strict tools | 400 "maximum number of strict tools supported is 20" |
| 20 strict + 5 non-strict tools | OK — **the cap counts strict only; mixing works** |
| strict tool with 0 unions + non-strict tool with 17 nullable | OK — **non-strict tools are exempt from the union cap** |

Why the shape matters: the compiler builds a grammar for each object. Each optional
field doubles the branches (present/absent), so a bag of *n* optionals is 2^n; a
sum type of *k* variants is *k* branches, each linear. The 16 cap and the per-object
cliff are both that exponent. Sum types are the shape the compiler is priced for.

Documented but not probed: `input_examples` on tool definitions (schema-validated
examples, 20–200 tokens each, no beta header) is the recommended way to teach nested
inputs; the plugin does not pass them today (4.5).

---

## 3. Diagnosis

ADR-0007 got the boundary right: tools are decisions (Acts), consequences are
Resolves, targets come from the Stage. The evidence is in the numbers: exploration
went 25 → 14 tools while the game gained spells, abilities, variants, wards and
anchors, and M2.4 added zero tools. That is the verb model scaling on the axis it was
built for.

The cost moved, it did not vanish. "One verb, parameterized by a typed target" was
implemented as "one verb, N optional parameters, `mode` says which ones matter". The
schema stopped saying which fields go together, the description had to say it in
prose (hence the novels), and the compiler priced every optional. `check` is the
canonical case: six modes, nine optionals, a 1363-char description explaining which
three of the nine to fill. `begin_activity` is worse: five kinds, eleven optionals.

Sum types fix all three at once: the schema documents the field groups, strict mode
enforces them per kind (the server rejects an attack without a `target_id`, which the
engine currently has to check by hand), the description shrinks to "when", and the
union budget charges one.

---

## 4. Design

### 4.1 Verbs take sum types — schema rules

These are the rules the budget test should enforce (section 5 has the pins).

1. **A parameter is optional only when the decision is optional.** No defaults on
   `@function_tool` signatures. `hours: int = 4` and `forced_march: bool = False` are
   two unions for nothing; make them required and let the description say what
   "normal" is. This alone removes 6 of exploration's 17 (`travel` 2, `enter_mode` 2,
   `transact` 1, `query_info` 1); rule 5 takes `activate`'s 2 and rule 2 takes
   `check`'s 9, which accounts for all 17.
2. **Polymorphism is one `anyOf` parameter.** Variants are pydantic models with a
   `kind: Literal["..."]` discriminator and *only required fields*. Cost: 1 union per
   verb, independent of variant count. Do not put optionals inside variants; make a
   second variant instead. Hold that rule as *our* discipline, not as something the API
   enforces: an optional inside an inline variant is counted, but the converter emits
   variants behind `$ref` (below) and the counter does not traverse `$ref` — 20
   nullables inside one `$ref`'d variant were accepted. Nothing outside the budget test
   will red on a violation, and the day Anthropic resolves refs before counting, every
   agent 400s at once.
3. **Never `dict[str, ...]`.** `additionalProperties` must be `false`. A mapping
   becomes `list[Variant]` with the key as a required field (`actor_id`).
4. **Never `Literal[...] | None`.** The converter emits an enum with a null member,
   which is rejected outright. A required enum is free; use a `"none"` member if the
   absence is meaningful.
5. **Prefer `list[str]` over `str | None` + `list[str] | None`.** `activate`'s
   `target_id`/`target_ids` pair is two unions and a cross-field rule the server cannot
   check; `targets: list[str]` (empty = self) is zero unions and the engine already
   normalizes the list.
6. **At most ~12 nullable fields in any single object** (the per-object cliff), and in
   practice zero after rules 1–5.
7. **Keep the tool list deterministic and ordered.** The plugin puts the cache
   breakpoint on the last tool; reordering invalidates tools + system.

Proposed shapes for the polymorphic verbs (illustrative; names to taste):

```python
# check — six decisions, one verb, one union
class SkillCheck(BaseModel):    kind: Literal["skill"];    skill: Skill; difficulty: Tier; description: str
class SocialCheck(BaseModel):   kind: Literal["social"];   npc_id: str; skill: SocialSkill; difficulty: Tier
class DiscoverCheck(BaseModel): kind: Literal["discover"]; skill: Skill; target: str
class SaveCheck(BaseModel):     kind: Literal["save"];     save_type: Attribute; dc: int; effect_on_fail: str
class DiceRoll(BaseModel):      kind: Literal["dice"];     notation: str
class Gather(BaseModel):        kind: Literal["gather"];   category: Literal["any","herbs","metals","arcane"]

async def check(context, roll: SkillCheck | SocialCheck | DiscoverCheck | SaveCheck | DiceRoll | Gather) -> str:
    """Resolve an uncertain action with a dice roll. Call when the player attempts
    something whose outcome is in doubt; trivial actions need no check."""
```

```python
# begin_activity — five kinds, eleven optionals → one union
Training | CompanionErrand | Crafting | WorkspaceRental | Experiment   # each with only its required fields

# declare_phase — a mapping of free-form dicts → a list of typed declarations
declarations: list[AttackDecl | AbilityDecl | DefendDecl | ReactionDecl | ...]   # each carries actor_id
# (probed live in exactly this shape and accepted)

# activate
id: str; targets: list[str]                                   # 0 unions

# travel
destination_id: str; mode: Literal["compressed","scenic","dangerous"]; hours: int; forced_march: bool   # 0

# enter_mode
target: CombatEntry | DispatchEntry | BlacksmithEntry         # 1 (or mode enum + required strings = 0)

# request_death_save
player_id: str                                                # 0 — the Stage lists party ids

# query_info / transact / learn / resolve_activity
required strings (empty when a kind has no target), or a small sum type    # 0–1 each
```

The LiveKit converter handles all of this: pydantic emits `oneOf` + `discriminator`
+ `$defs` for a discriminated union; `_ensure_strict_json_schema` rewrites `oneOf` →
`anyOf`, strips `discriminator` and `title`, sets `additionalProperties: false`, and
marks every property required. A single-value `Literal` becomes `const`, which the API
accepts (probed). It does **not** inline `$ref` — `_strict.py` only unravels a ref on an
object carrying more than one key, so a bare variant ref survives and the emitted shape
is `{"$defs": {...}, "properties": {"<param>": {"anyOf": [{"$ref": "#/$defs/A"}, …]}}}`.
Anthropic accepts that shape (probed). Every walk over these schemas — the budget test
above all — must therefore resolve `$ref` into the root `$defs`, or it sees nothing
inside any variant.

Projected budget after reshaping (exploration assumes `enter_location` folds, 4.3):

| Agent | Tools | Unions (from) | Notes |
|---|---|---|---|
| exploration | 13 | **2–3** (17) | `check` 1, `enter_mode` 0–1, `query_info` 0–1 |
| combat | 9 | **3** (13 + reject) | `declare_phase` 1, `check` 1, `activate`/`query_info` 0–1 |
| dispatch | 9 | **3** (23) | `begin_activity` 1, `check` 1, `resolve_activity` 0–1 |
| onboarding | 6 | 1–2 (10) | |

Headroom: one union per future polymorphic verb, so the 16 cap becomes a cap on
polymorphic *verbs*, not on nouns. The 20 cap and the 16 cap now bind at the same
place; the effective ceiling is **~16 verbs per agent**, which matches LiveKit's
"past 10 selection degrades, past 20 it struggles" and Anthropic's 30–50. Treat 12 as
the warn line.

### 4.2 What to do when a verb set grows

- **Content never adds a verb.** Patrons (Phase 8, "~30 abilities need two new verbs"
  per REMAINING.md) are `activate(id)` data plus the already-deferred
  player-initiated `devote`/`pray`. Budget that as one Act, not a ceiling fight.
- **A new decision adds a verb** only if no existing verb's sum type can take a new
  variant. A new variant costs nothing.
- **Past ~16 verbs, split by mode of play**, the axis ADR-0007 chose (agent = verb
  set, Stage = place). Mode agents are already the pattern and each handoff is a cache
  miss you pay once per mode entry, not per turn.
- **Not tool search.** LiveKit's `ToolSearchToolset` swaps the tool list between turns
  (cache invalidation on every discovery) and `ToolProxyToolset` funnels calls through
  a non-strict `call_tool(name, parameters: object)`. Anthropic's server-side tool
  search (`defer_loading`) preserves the cache and composes with strict, but the
  plugin does not emit it, and every discovery is an extra model round trip inside the
  1500 ms budget. Reserve it for a hypothetical agent with dozens of rarely used
  verbs, which the verb model is designed to prevent.

### 4.3 Right information at the right time

Four channels reach the DM. Place each datum by its **volatility**, because a datum in
a layer that refreshes faster than it changes wastes cache, and one in a layer that
refreshes slower than it changes goes stale (Golden Rule 4).

| Channel | Refreshes | Cached | Carries |
|---|---|---|---|
| **Cold** (agent `instructions`, static half) | per agent lifetime | yes, all session | persona, voice style, the verb charter ("when" for each verb), static character facts |
| **Warm** (the Stage, rebuilt by the background process) | per event | yes, between rebuilds (system prompt change invalidates system + messages, keeps tools) | place, register, affordances grouped by verb, scene band, companion, corruption, active downtime cycles |
| **Hot** (`on_user_turn_completed`) | per turn | no (small) | the `NOW` block (4.4), pending choice, this-turn reveals, bands that crossed a threshold, affect |
| **Result** (tool return) | per call | no | narration cues, state changes, refusals, and `next` — what is now legal |
| **Pull** (`query_info`) | on demand | n/a | the long tail: lore, NPC depth, inventories, rosters |

Concrete fixes on trunk:

- **Remove `ACTIVE COMBAT` from the warm layer.** Only `COMBAT_STARTED`/`ENDED`
  trigger a rebuild, so the warm HP bands are stale from round 2 on while the hot
  block carries the truth. Two renderings of the same state, one wrong, is the exact
  hazard §8 of the verbs doc names.
- **Fold `enter_location` into the Stage push.** The warm layer already renders the
  scene on arrival, `move_player` already returns `_build_scene_context`, and the
  greeting instructs the DM to call `enter_location` anyway, costing a tool round trip
  on the first turn. Make the arrival Resolve (move/travel/session start) push the
  Stage and return the cues; drop the tool (−1 tool, −333 chars, −1 round trip).
- **Descriptions carry only "when".** Move field semantics into pydantic
  `Field(description=...)` on the variants (they render into the schema the model
  reads) and target catalogs into the Stage. Target ≤ 4 sentences per verb; Anthropic
  asks for 3–4, LiveKit for what/when/when-not. Expect exploration's 12.5k chars of
  tool JSON to drop by roughly a third while getting more precise.
- **Standardize the result envelope** (`agent_verbs_and_stages.md` §4, the design
  doc ADR-0007 realizes, promised `ActResult`; it does not
  exist yet). Every Act returns the same keys so Haiku learns one shape:

  ```json
  {"narrate": ["narrative_hint / cues, speech-ready"],
   "changed": {"hp": "bloodied", "quest": "stage advanced"},
   "reveal":  ["new affordances this turn: an exit, an item, a choice"],
   "refused": null | "reason the DM can voice",
   "next":    {"phase": "combat.resolution", "legal": ["activate", "resolve_phase"], "waiting_on": "player reaction or continue"}}
  ```

  `next` is the important addition; see 4.4.

### 4.4 Right action at the right time

The game has several small state machines (session arc, combat beats, the reaction
window, downtime cycle midpoints, the L5 fork, onboarding beats). The DM has to call
the right verb in the right state. Three mechanisms, in order of authority:

1. **Legality lives in the tool body** (already true): `_require_combat`, beat checks,
   `validate_reaction_activation`, `ToolError` with a voiceable reason. This is the
   wall. Nothing below replaces it.
2. **The hot layer states the phase and the legal verbs.** Add a `NOW` block, one
   line, built from `SessionData` with zero I/O like the rest of `_build_hot_context`:

   ```
   [NOW: combat round 3, beat: resolution — held: goblin_2 → player_1 (window on_hit) |
    legal: activate(reaction), resolve_phase | waiting on: the player]
   [NOW: exploration, guild hall — pending choice: L5 specialization (select) | quests: …]
   ```

   Constraint 6 in one place: every id the DM may pass (window names, held-action
   ids, choice ids, cycle ids) is produced here or in a result, never guessed.
3. **Every state transition returns `next`.** `resolve_phase` at the resolution beat
   returns the held enemy actions with their windows and `legal: [activate,
   resolve_phase]`; after the last window closes it returns `phase: wrap` and
   `legal: [request_death_save, consume_legendary_action, declare_phase]`. Story-016's
   AC ("each names its actor, its target and the reaction window it opens") is this
   rule applied once; make it the rule.

On story-016's open choice (new verb vs. a second `resolve_phase` call): from the
budget side a new verb is one strict slot and zero unions, so it is affordable either
way. The cleaner state-machine reading is a single "advance" verb whose behaviour
depends on the beat: `resolve_phase` at RESOLUTION resolves allies and holds enemies;
at the reaction window it releases the next held action. One verb, `next` tells the DM
which it will do. Plan review owns the call.

**Do not gate by swapping tool lists per turn.** The math, on Haiku at $1/MTok input:
the exploration prefix (tools + system + warm) is ~8k tokens. Tools render first, so
any change to the list rewrites the whole prefix at 1.25× (~$0.01) and the reads that
would have been 0.1× become full price. Flipping every turn over a 40-exchange
session is ~$0.40, roughly the whole per-session cost in `cost_model.md` (where LLM
is ~16% of it, about $0.06). The caveat
that makes a *small* number of variants affordable: the cache is keyed by exact
prefix, so two or three stable tool-list variants each keep their own entry within the
5-minute TTL; the cost is one write per variant plus a slightly larger history delta
per turn. That is why the policy below allows scoping for system-initiated replies
and treats per-beat combat scoping as an experiment, not a default.

Policy:

- **One fixed tool list per mode agent.** Never `update_tools` inside a mode.
- **System-initiated replies may scope tools with `generate_reply(tools=[...])`**
  (LiveKit 1.6, Python only, by tool id). Proactive beats, companion cues, the greeting
  and reconnection replies should pass `tools=[]` or a one-verb list so the DM cannot
  fire a mutation from a background nudge. Same cache entry as the main list is
  *not* reused, so keep these rare (they already are).
- **`tool_choice` is not a gate either.** Named `tool_choice` keeps tools + system
  cached but invalidates the messages cache; and Fable-class models reject forced
  choice outright. Instruct in the hot layer instead.
- **Combat per-beat scoping is an eval-gated experiment** (section 6): run the
  LiveKit simulation against the current single-list combat agent; only if wrong-beat
  calls actually occur with the `NOW` block in place is the three-variant rotation
  worth its cache overhead.

### 4.5 Plugin constraints and escape hatches

`livekit-plugins-anthropic` 1.6.1 (and main as of today) offers no per-tool strict
flag, no `input_examples`, no `defer_loading`, and `extra_kwargs` cannot inject tools
(the plugin assigns `extra["tools"]` after merging). Three graduated options:

1. **Nothing** — after 4.1 every agent is strict-clean; flip `_strict_tool_schema`
   back to the default and delete the pin tests. Preferred.
2. **Per-tool non-strict via `@function_tool(raw_schema=...)`** — the plugin emits
   `RawFunctionTool`s without `strict`, exempt from both caps. Use only for a verb
   that genuinely needs a shape strict cannot express; today there is none. It is
   sanctioned plugin API, unlike the private kwarg.
3. **A thin `anthropic.LLM` subclass overriding `chat()`** to post-process the schema
   list: attach `input_examples` per tool (one example per variant is the single most
   effective way to teach Haiku a sum type), set `strict` per tool, or add
   `defer_loading`. ~40 lines against a public method, but the plugin owns the loop;
   pin the plugin version and keep the existing signature test. Adopt only if the
   selection eval says examples are needed.

---

## 5. Sequencing

Ordered so each step is green on its own and the strict flip lands as early as
possible. Steps 1–3 are story-019's scope; 4–6 are follow-ons worth their own cards.

1. **Pin the real budget.** Extend `test_strict_tool_budget.py` to walk
   `parse_function_tools("anthropic", strict=True)` output per agent (the appendix
   describes the walk) and assert: strict tools ≤ 20, unions
   ≤ 16 with a warn at 12, no object with > 12 nullables, no `additionalProperties`
   object, no enum containing null, no `oneOf`. Pin the exact union count per agent
   next to the tool count. Add a source lint: no `@function_tool` parameter with a
   default. Keep the acceptance-lane real-LLM turn per agent, failing loud without a
   key (already in the AC).
2. **Reshape the verbs per 4.1**, behaviour-preserving, one verb per commit:
   `check`, `begin_activity`, `declare_phase` (reshape it NOW — its
   `additionalProperties` object is the hard 400, and Sprint 48 builds on the result),
   `activate`, `travel`, `enter_mode`, `request_death_save`, the four one-union
   strays. Tool bodies keep their existing validation (the engine remains the wall;
   strict is a second net).
3. **Flip strict on.** Remove `_strict_tool_schema=False`, flip
   `test_every_agent_session_runs_strict_tool_schema_off` to assert the default,
   supersede the ADR-0004 addendum. Set `max_tool_steps` explicitly on the combat
   session.
4. **`NOW` block + `next` in results + `ActResult` envelope** (4.3, 4.4). Start with
   combat (it has the richest state machine and story-016/017 already need `next`),
   then the L5 fork and downtime midpoints.
5. **Stage hygiene**: drop warm `ACTIVE COMBAT`; fold `enter_location` into arrival
   Resolves; shrink descriptions to "when" and move field semantics into variant
   `Field` descriptions.
6. **Eval-gated experiments**: `input_examples` via a plugin subclass; combat per-beat
   scoping; system-initiated-reply scoping (`tools=[]` on proactive beats is cheap
   enough to do in step 4 without an eval).

ADR: record this as ADR-0008 ("Verbs take sum types; state machines name their next
verbs"), superseding the 0004 addendum and refining 0007 §4 ("standard Act shape").

---

## 6. Risks and how to measure them

- **Haiku filling nested variants.** The main behavioural risk of sum types. Mitigate
  with `kind` first in every variant, `Field` descriptions, and (if needed)
  `input_examples`. Measure with a small tool-selection eval before/after: ~20 canned
  player utterances per agent → expected verb + variant + required fields, run through
  the LiveKit testing framework (`docs.livekit.io/agents/start/testing`), with a
  simulation pass for combat. Wire the same set into the acceptance lane's real-LLM
  scenarios so it stays measured.
- **Combat schema drift in Sprint 48.** The counts in section 1 are trunk and 019
  reshapes them; 016 and 017 then change `declare_phase`'s payload again and may add a
  verb. This is why decision 2's test WALKS the emitted schema instead of pinning
  hand-counted numbers — Sprint 48 re-runs the same walk and the drift is caught, not
  re-measured by hand.
- **Cache regressions are silent.** Add a standing assertion (acceptance lane) that
  the second turn of a scenario reports `cache_read_input_tokens > 0` on the plugin's
  usage chunk, so a future tool-list or system-prompt invalidator is red, not a bill.
- **Plugin upgrades.** Everything in 4.1 uses public API. Option 3 in 4.5 does not;
  gate it on the eval.

---

## 7. Open questions for the human

1. `query_info`: sum type (1 union, self-documenting) or required `target_id` with an
   empty-string convention (0 unions, slightly ugly)? Recommendation: sum type, for
   consistency with the rule.
2. `enter_mode`: is the combat entry's `encounter_description` a decision the DM makes,
   or should the encounter template supply it? If the latter, `enter_mode` is a plain
   enum + id, 0 unions.
3. Does `resolve_phase` become the single "advance" verb across the reaction window
   (this doc's recommendation), or does 016's plan review add a `release`/`continue`
   verb? Both fit the budget.
4. Is the creation agent's `claude-sonnet-4-20250514` deliberate?

---

## Appendix — how this was measured

The measurement scripts were design-session scratch and are not kept in the repo; the
numbers they produced are quoted inline above and in section 2, and the trunk snapshot
they ran against was a `git archive` of `08fa9b8` outside the working tree.

- **Per-agent schema walk** — build `llm.ToolContext(TOOLS)` for each agent list, call
  `parse_function_tools("anthropic", strict=True)`, and walk each tool's `input_schema`
  recursively, counting a property as union-typed when it carries `anyOf`/`oneOf` or a
  list-valued `type`. Recurse through `properties`, `items`, and each `anyOf` variant —
  **and resolve `{"$ref": "#/$defs/X"}` against the tool's root `$defs`, tracking
  visited refs so a self-referential variant cannot loop.** Flag any non-empty
  `additionalProperties`. Per tool: parameter count, union count, union paths,
  description length. The walk that produced section 1's table did not resolve refs and
  did not need to — no tool on trunk has a `$defs`. Every tool reshaped under 4.1 will,
  so a budget test that inherits that omission checks nothing inside the variants, which
  is where the whole payload moves.
- **Limit probes** — send synthetic tool schemas through `messages.create(max_tokens=1)`
  on Haiku 4.5. `count_tokens` validates shape only; the grammar limits fire on create.
  The live probes cost ~7k input tokens in total.

Story-019 lands the durable form of the first of these: a budget test that walks the
emitted strict schema and pins the caps in decision 2, beside the existing 20-tool
assertion in `apps/agent/tests/test_strict_tool_budget.py`. That test, not a script, is
what keeps these numbers honest.

---

## 8. Cost recommendations

Frame from `cost_model.md`: a solo session is ~$0.40, of which LLM is ~16% (~$0.06),
TTS 53%, STT 16%, transport 15%. Two things follow. First, the LLM baseline is small
and the real LLM risk is a **regression that multiplies it** (a cache invalidator, a
chatty background loop), so the guardrail matters more than shaving the baseline.
Second, anything that removes a *whole LLM turn* also removes a TTS synthesis, which is
where the money is. Ranked by expected effect; each is independent of the schema work.

### 8.1 Protect the prompt cache

1. **Fold blacksmith back into exploration.** `repair_item(item_id, npc_id)` becomes an
   exploration verb (two required strings, 0 unions; exploration 13 → 14 tools). The
   forge register moves to Stage content (`scene.instructions`, as ADR-0007 already
   does for every other place) and the Stage lists the smith under `address` and the
   repairable items under `repair`. `enter_mode("blacksmith")` and `conclude_blacksmith`
   disappear. Saves two prefix rewrites per forge visit (~8k tokens each at 1.25×,
   roughly $0.02 and two time-to-first-token hits) and one 1k-token prompt to maintain.
   ADR-0004 split it to stay under the tool cap; that reason is gone.
2. **Put the warm layer on a rebuild diet.** Eight event types trigger
   `update_instructions`, and every rebuild rewrites system + the whole history at
   1.25×. Keep the place-shaped triggers (`LOCATION_CHANGED`, `QUEST_UPDATED`,
   `COMBAT_STARTED/ENDED`, `HOLLOW_CORRUPTION_CHANGED`). Move the per-turn-volatile
   ones to the hot layer: `DISPOSITION_CHANGED` (one word on an address line),
   `DIVINE_FAVOR_CHANGED` (a band), `HIDDEN_REVEALED` (the hot layer already surfaces
   it; let the next place-driven rebuild absorb it into the affordances). The 30-second
   timer path is already deduped by string comparison; keep it.
3. **Keep clocks out of the warm layer.** The scene header renders `({world_time})`.
   Today that is the frozen string "evening"; when Phase 11's world clock lands, a
   per-minute value there would invalidate system + history every rebuild. Render a
   time-of-day *band* in warm and the exact time nowhere in the prompt (the HUD has it).
4. **Combat lives only in the hot layer** (4.3). Besides the staleness bug, this stops
   mid-fight rebuilds from touching the system prompt.
5. **Guardrail — but repair `TokenTracker` first; today it records zeros.**
   `on_metrics` iterates `getattr(metrics, "llm_metrics", [])`, and the
   `metrics_collected` payload is `MetricsCollectedEvent(metrics=AgentMetrics)` — no
   `llm_metrics` attribute, so the loop body never runs; the four field names it then
   reads (`input_token_count`, `output_token_count`, `cache_read_input_token_count`,
   `cache_creation_input_token_count`) exist on none of them either, and every read is
   a `getattr` default. `LLMMetrics` carries `prompt_tokens` / `completion_tokens` /
   `prompt_cached_tokens` (`livekit/agents/metrics/base.py`), and `metrics_collected`
   is itself deprecated in favour of `session_usage_updated`. Until that is fixed,
   every cost assertion below is measuring a constant 0 — a guard that certifies
   (constraint 1). Then log the cached ratio per session and assert in the acceptance
   lane that turn two of a scenario reads from cache, so a future invalidator (a UUID
   in a prompt, a reordered tool list, a per-turn `update_tools`) goes red rather than
   showing up on the bill.

### 8.2 Fewer LLM turns per session

6. **Stop spending a full LLM turn on companion idle chatter.** Every 45 s of silence
   (`COMPANION_IDLE_SECS`) queues a `generate_reply`, a complete turn over the full
   context plus a fresh TTS synthesis. In the "open-ended hang" mode the design doc
   describes, that is up to 80 filler turns an hour, each costing more than a real
   player exchange because the player said nothing. `companion_idle.generate_idle_pool`
   already produces a pool of pre-rendered lines (one small LLM call, batched TTS to
   file) and nothing on the live path consumes it. Play ROUTINE-priority idle lines
   from a pool via `session.say` (LiveKit's own recommendation for repeat fillers);
   refresh the pool per location on arrival, off the critical path, so lines still
   name the place; keep `generate_reply` for IMPORTANT/CRITICAL beats and scene-beat
   hints that need the conversation. Also gate idle chatter on affect: skip it when
   engagement is high (the player is mid-thought), which the prompt already asks the
   DM to respect.
7. **Remove predictable pull calls.** Each avoided tool call is a whole extra model
   call (input re-read, output, ~0.5–1 s). `enter_location` on the greeting (4.3) and
   `query_info(kind="abilities")` before every combat declaration (the combat prompt
   asks for it; the reaction windows and owned ability ids are predictable and belong
   in the combat-entry context or the `NOW` block, which story-017 partly does).
8. **Trim tool results.** `move_player` and `enter_location` return the full scene
   (NPCs, targets, player status) and that JSON sits in history for the rest of the
   session, re-read every turn. The Stage already carries the scene in the system
   prompt, so the result only needs the envelope (4.3): cues, what changed, what was
   revealed, what is next. Expect a few hundred tokens saved per move, compounding.
9. **Prune history on long sessions.** Nothing truncates the chat context. Cached
   reads are 0.1×, but a 90-minute session can carry 30k+ tokens of history, and at
   that size the read alone is ~$0.003 per turn on Haiku, which over 60 turns exceeds
   the whole LLM budget. Server-side compaction and context editing are not available
   on Haiku 4.5 or through the plugin, so do it client-side: every ~25 turns, replace
   old `function_call_output` items and the oldest exchanges with a short summary
   (the `session_summary` machinery already exists for session end) via
   `update_chat_ctx`. One cache miss per prune, then every turn reads a prefix a third
   the size. Measure first with `TokenTracker` (repaired — see 8.1); the cost
   model's exchange count will
   say whether typical sessions ever get there.
10. **Inject affect only when it changed.** The affect line is ~60–100 uncached
    tokens on every turn as its own message. Emit it when a band changes or every
    fifth turn. Small in dollars; it also removes noise from the prompt.

### 8.3 Models and parameters

11. **Creation agent model.** It is pinned to `claude-sonnet-4-20250514` ($3/$15 per
    MTok). If creation needs more than Haiku, `claude-sonnet-5` is current and cheaper
    ($2/$10). If Haiku can drive a three-tool, zero-union card flow, cheaper still.
    Once per player, so small in absolute terms, but zero risk and it retires an old
    snapshot id.
12. **Don't switch models mid-session** (caches are model-scoped) and don't vary
    `temperature`/`tool_choice` per turn; the plugin's placement puts tools + system
    under one breakpoint and those parameters can invalidate the messages cache.
    `max_tokens` (plugin default 1024) is fine under the 60-word cap.

### 8.4 TTS, briefly

Out of this doc's scope but the same principle applies to the 53%: pre-render stock
lines (idle pool above, god-whisper stingers, the "threads of fate tangle" fallback)
through the existing `tts_prerender` module, and hold the 60-word cap; the prompt's
economy rules are the single biggest cost control in the system.

### 8.5 A cost budget test

The tool budget test caught the 20-tool 400 before production; nothing does the same
for spend. Add a fast-lane test that runs a canned 10-turn scenario through the
prompt assembly (no API) and pins uncached input tokens per turn and the number of
system-prompt rebuilds it triggers, so a change that starts rebuilding the warm layer
every turn is red in the unit lane. Pair it with the acceptance-lane cache-read
assertion in 8.1.
