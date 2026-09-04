# ADR 0008 — Verbs take sum types; state machines name their next verbs

Status: **Proposed** (2026-09-04) — design session, read-only against trunk `08fa9b8`.
Supersedes the 2026-09-02 interim addendum of **ADR 0004**; refines **ADR 0007**'s
standard Act shape (`docs/agent_verbs_and_stages.md` §4). Realized by story-019
(Sprint 47) and its follow-ons.
Design source: `docs/agent_tool_surface.md`.

## Decision

1. **Polymorphic verbs take a sum type, never a bag of optionals.** A verb that acts on
   several kinds of noun takes **one** parameter that is a discriminated union of
   kind-tagged variants (`kind: Literal[...]` first, then *only required* fields).
   `@function_tool` parameters carry no defaults; `dict[...]` parameters and
   `Literal[...] | None` parameters are banned. A mapping becomes a list of variants
   carrying the key.
2. **The union budget is pinned beside the tool budget.** Per agent, the emitted strict
   schemas (`parse_function_tools("anthropic", strict=True)`) must satisfy: ≤ 20 strict
   tools, ≤ 16 union-typed parameters counted recursively (warn at 12), ≤ 12 nullable
   fields in any single object, no `additionalProperties` object, no enum containing
   null, no `oneOf`. The exact per-agent union count is pinned, as the tool count is.
   **The walk resolves `$ref` into the root `$defs`** (visited-set guarded): decision 1's
   shape puts every variant behind a bare `$ref`, and a walk that stops there checks
   nothing inside them — an `additionalProperties` object, an enum with null, or a
   `oneOf` inside a variant is a live 400 the API still raises (probed 2026-09-04).
3. **Strict tool schemas are on.** `agent.py` stops passing `_strict_tool_schema=False`;
   the pin tests flip. A verb that genuinely needs a shape strict cannot express uses
   `@function_tool(raw_schema=...)` (emitted non-strict by the plugin, exempt from both
   caps) and says why in its docstring. None exists today.
4. **Every state transition names the next legal verbs.** Acts return a standard
   envelope (`narrate`, `changed`, `reveal`, `refused`, `next`), and `next` carries the
   machine's phase, the verbs legal in it, and what it is waiting on. The hot layer
   renders the same as a one-line `NOW` block each turn. Any id the DM may pass (a
   reaction window, a held action, a pending choice, a cycle id) is produced there or
   in the Stage, never inferred (constraint 6, generalized).
5. **One fixed tool list per mode agent.** Tool sets are not swapped per turn or per
   combat beat. System-initiated replies (proactive beats, greetings, reconnects) may
   restrict tools per reply via `generate_reply(tools=[...])`. Tool search and proxy
   toolsets are not used on the play path.

## Context

ADR 0004 rationed Anthropic's 20-strict-tool cap by splitting agents. ADR 0007 made
the cap stop binding by folding nouns into verbs; exploration went 25 → 14 tools while
the game gained spells, abilities, variants, wards and anchors. The sprint-046 close
then found a second limit: strict requests may carry at most **16 union-typed
parameters**, and the folded verbs had become bags of optionals (`check` 9,
`begin_activity` 11). Exploration sent 17, dispatch 23, and combat's
`declare_phase.declarations` (`additionalProperties: object`) was refused outright.
Strict went interim-OFF.

Probed live on 2026-09-04 (Haiku 4.5, `messages.create`): the 16 cap is per request
across strict tools and counts nested objects, array items and nullables inside
variants; a separate "Schema is too complex" cliff sits at ~13 nullables in one
object; a discriminated `anyOf` of N required-field variants costs **one**; required
enums cost zero; `enum` with a null member and `oneOf` are rejected; non-strict tools
count toward neither cap and mix with strict ones. Two of those probes were re-run at
this ADR's landing and split by shape: nullables inside *inline* variants are counted
(17 → 400), nullables inside variants reached by `$ref` are **not** (20 → accepted),
while `additionalProperties`/enum-null/`oneOf` are rejected either way. LiveKit emits
the `$ref` form, which is why decision 2 resolves refs rather than trusting the API to
catch a rule-1 violation. The compiler's cost is exponential
in optionals per object and linear in variants. Sum types are the shape it is priced
for; they are also the shape that lets the schema, not the description, say which
fields go together.

## Options considered

1. **Keep strict off** (`_strict_tool_schema=False`). Works today, loses schema-valid
   arguments on exactly the verbs that most need them, rides a private kwarg.
   **Rejected** (already rejected in 0004; the addendum was dated and interim).
2. **Split the polymorphic verbs into per-kind tools.** Spends the 20-tool budget to
   buy back the 16-union budget, degrades selection, and reverses 0007.
   **Rejected**.
3. **Per-tool non-strict for the polymorphic verbs.** Cheap, but exempts the most
   complex payloads from validation. **Kept as the documented escape hatch only.**
4. **Tool search / ToolProxyToolset.** Preserves caching (server-side variant) but adds
   a model round trip inside the 1500 ms budget, and the LiveKit beta routes calls
   through a non-strict `call_tool(parameters: object)`. **Rejected** for the play
   path.
5. **Sum-typed payloads + pinned union budget + `next` in results** (chosen). Every
   agent lands at 2–4 unions; the union cap and the tool cap then bind at the same
   place (~16 verbs per agent), which is also where selection accuracy degrades. One
   budget, one number.
6. **Per-turn tool scoping for "right action at the right time".** Tools render first
   in the prompt, so each list change rewrites the ~8k-token prefix at 1.25× and
   forfeits the 0.1× reads; per-turn flipping over a session costs about what the whole
   session is budgeted to cost. **Rejected as a gate**; legality stays in tool bodies
   and the DM is *told* the phase (decision 4).

## Consequences

**Better**
- Strict returns with the schema doing the cross-field work the engine now does by
  hand (an attack without a target is rejected before the tool runs).
- Descriptions shrink to "when"; field semantics move into variant `Field`
  descriptions, target catalogs stay in the Stage.
- Adding a noun kind is a new variant (cost 0); adding a decision is a new verb
  (cost 1). Content never adds a tool; patrons and future ability families are
  `activate` data.
- The DM gets one place per turn that says what phase it is in and what is legal,
  which is the mechanism story-016/017's reaction window needs anyway.

**Watch**
- Haiku filling nested variants is the behavioural risk. Measure with a
  tool-selection eval (≈20 utterances per agent → expected verb + variant) before
  and after; add `input_examples` via a thin plugin subclass only if the eval says so.
- Combat's payloads move again under the M29 reaction restore (story-016/017/018,
  Sprint 48) — *after* this decision lands in Sprint 47. That is precisely why
  decision 2 pins by WALKING the emitted schema rather than by hand-counted numbers:
  Sprint 48 re-runs the same walk and drift is caught, not re-measured.
- Cache regressions are silent; assert `cache_read_input_tokens > 0` on turn two in
  the acceptance lane — but repair `TokenTracker` first, which records a constant 0
  today (bug filed 2026-09-04; design doc §8.1). Asserting against it certifies nothing.
- The union cap not traversing `$ref` is undocumented behaviour we are on the safe side
  of, not one we may spend: if Anthropic ever resolves refs before counting, an agent
  whose variants carry optionals 400s with no warning. Decision 2's walk is the only
  thing that would have been red first.
- Mode-agent splits are now driven by the eval, not by counts: split when the verb
  set differs by ≥ 4 verbs, the player stays ≥ 5 turns, and the interaction model
  changes. Blacksmith fails the first test and is a candidate to fold back into
  exploration (see the design doc's cost section).

## Deferred

- `input_examples` / per-tool `strict` / `defer_loading` through a plugin subclass —
  until the eval shows a need.
- Combat per-beat tool scoping (three cached list variants) — an experiment gated on
  wrong-beat calls actually occurring with the `NOW` block in place.
- Persisting the hot block in history to stabilize the prefix — only if the per-turn
  tail miss ever shows up in the usage numbers.
