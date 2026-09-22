# Strict gameplay tools without abandoning verbs and nouns

Date: 2026-09-18. Status: **Accepted for the GPT-5.6 Luna production route on 2026-09-20.**
Measured at `ceef9573`, with LiveKit Agents / Anthropic plugin 1.8.1,
Anthropic SDK 0.105.2, Pydantic 2.12.5, and `claude-haiku-4-5-20251001`.

This continues [the tool-surface design](agent_tool_surface.md) and
[ADR 0008](decisions/0008-sum-typed-verbs-and-next-in-results.md).
The verb/noun design stays. The proposed change is to **which schemas accompany
each model request**, not the game's verbs, noun types, or deterministic engine.
Sections 1–9 preserve the Anthropic research that led to the provider evaluation.
Section 11 records the production decision after the Luna release gates ran.

The human's constraint for this design: an extra model call is acceptable **if
measured voice latency is acceptable**. This is not permission to relax the
existing 1,500 ms end-of-speech-to-first-audio target.

## 1. Recommendation

Use **staged argument generation for a small, fixed set of verbs**. In the normal
DM request, these verbs have strict, zero-argument selection schemas. When the DM
selects one, an internal request receives that verb's original, complete strict
schema and generates its arguments. Only the completed call reaches LiveKit's
tool executor. All other verbs keep their existing schemas and execute normally.

This preserves the rich typed nouns. It makes both requests strict, including
the request generating the complex arguments. There is no JSON-in-a-string escape
hatch and no non-strict generic proxy. The adapter never executes game logic.

The tradeoff is **Simplicity versus Feedback**: a small transport coordinator and
an extra request buy provider-enforced arguments without flattening domain types.
**Honesty takes precedence**: compilation success is established; acceptable
player-facing latency is not. Build and measure the coordinator before committing
to a production switch. Do not enable strict globally as the first implementation step.

## 2. What strict actually protects

The provider under study in this section was Anthropic, through
`livekit.plugins.anthropic.LLM`; that rollback route passes
`_strict_tool_schema=False`. Strict tool use constrains
the **model-generated tool name and input arguments**. It does not validate a
Python tool's returned JSON or ensure that a mechanically valid action is legal.
[Anthropic strict tool use](https://platform.claude.com/docs/en/agents-and-tools/tool-use/strict-tool-use)
describes this input boundary.

With strict off, a call can have malformed JSON, missing fields, wrong types, or
wrong variant fields. It does not follow that every such call executes. The installed
LiveKit `llm.utils.prepare_function_arguments` parses and validates before dispatch;
validation failures become `ToolError`. Its parser also repairs some JSON, and its
Pydantic validation can coerce values or ignore extra fields.

Executed locally against the real vendor validator:

| Input | Observed behavior |
|---|---|
| `check` with a skill variant missing required fields | `ValidationError` |
| `check` with an unknown `kind` | `ValidationError` |
| Dice variant with an extra, unrecognized field | Accepted; extra field discarded |
| Travel with `hours: "4"`, `forced_march: "false"` | Accepted; coerced to `4`, `False` |

Strict reduces these generation errors and their retry/latency cost. Keep local
validation and engine checks for ownership, valid IDs, resources, targets, phase,
duplicate actors, and cross-field rules. Refusal, truncation, interrupted streams,
and transport failures still require explicit handling. Provider documentation
also describes enum-capitalization exceptions; do not silently reinterpret an ID.

Tool results remain an application contract. The separate narration pipeline in
`narration.py` already sends its own strict `narration_result` tool; the gameplay
flag does not switch that request off. Its shape/normalization issues are a
different boundary.

## 3. Diagnosis and fresh evidence

The pressure moved from **number of tools**, to **optional/union argument shapes**,
to **combined grammar complexity**. Sum types fixed the middle problem; they did
not remove the last one. Payload byte length is not the controlling budget.

The installed plugin calls `build_strict_openai_schema` even for Anthropic. That
normalizer makes object fields required and represents defaults using nullable
fields. Consequently, `travel(hours=4, forced_march=False)` spends two union slots.
This reflects LiveKit's shared conversion, not a requirement to change providers.
[OpenAI's strict schema requirements](https://developers.openai.com/api/docs/guides/function-calling)
explain the required-field/closed-object convention used by that builder.

Anthropic currently documents 20 strict tools, 24 optional parameters, and 16
union-typed parameters per request, plus an internal grammar-complexity limit.
Passing the numeric limits is necessary but insufficient.
[Schema complexity limits](https://platform.claude.com/docs/en/build-with-claude/structured-outputs#schema-complexity-limits)

The following counts were recomputed through
`ToolContext(tools).parse_function_tools("anthropic", strict=True)` and the repo's
reference-resolving walker. Acceptance was checked against the live API, not inferred
from those counts.

| Agent | Tools | Walked unions | Original full strict request on Haiku |
|---|---:|---:|---|
| Exploration | 14 | 9 | Rejected: compiled grammar too large |
| Combat | 9 | 6 | Rejected: compiled grammar too large |
| Dispatch | 9 | 6 | Rejected: compiled grammar too large |
| Onboarding | 6 | 2 | Accepted |
| Blacksmith | 3 | 1 | Accepted |
| Creation | 3 | 0 | Accepted |

**Production model coverage is a separate prerequisite.** The existing probe uses
Haiku for every agent. New-player sessions in `agent.py` actually use
`claude-sonnet-4-20250514`; a separate live request with that model and the creation
tools returned **404: model not found**. This is model unavailability for the
current account, not a schema rejection or evidence about global retirement.
Resolve that configuration before claiming creation is production-ready. Probe
the actual model/profile combinations reachable through handoffs: creation returns
an onboarding agent in the same session, so a new agent class does not itself
establish a new model. No replacement model is selected by this design.

Dispatch is now six unions, not the five recorded in ADR 0008: training's
`spell_id` is nullable. An `anyOf` counts as one walked union regardless of branch
count; that count does not measure its compiled cost. No universal complexity
formula is claimed here.

Additional live experiments on exploration, combat, and dispatch:

| Candidate | Result for all three | Implication |
|---|---|---|
| Remove nullable alternatives recursively, keeping the tool/variant sets | Rejected | Removing defaults alone is insufficient; this experiment also narrows semantics and is not a proposed implementation |
| Inline `$ref` targets and remove `$defs` | Rejected | Equivalent schema packaging does not solve this case |
| Keep original schemas; disable parallel tool use | Rejected | Serial tool selection does not remove the grammar limit |
| Stage selected verbs as specified below | Accepted | Partitioning strict generation across requests works |

The original `check`, `declare_phase`, `begin_activity`, `activate`, and `travel`
schemas were also accepted individually. These typed nouns fit strict mode;
the combined request is the demonstrated obstacle. This does not prove that every
future larger noun will compile alone.

## 4. The two requests

Use the following fixed initial policy. It is a **measured sufficient partition**,
not a claim that the number of staged verbs is mathematically minimal.

| Agent profile | Verbs with separately generated arguments | Other verbs |
|---|---|---|
| Exploration | `check`, `activate`, `travel` | Original full strict schemas |
| Combat | `check` | Original full strict schemas, including `declare_phase` and reaction `activate` |
| Dispatch | `check` | Original full strict schemas, including `begin_activity` |
| Onboarding, blacksmith, creation | None | Original full strict schemas |

Keeping combat `activate` direct avoids adding an argument request to the normal
reaction path. No new mode handoff, tool search, per-beat tool replacement, or
content-specific tool is introduced.

```mermaid
sequenceDiagram
    participant DM as DM request
    participant A as Strict coordinator
    participant F as Argument request
    participant L as LiveKit executor
    participant E as Existing engine
    A->>DM: Stable strict selection surface + current context
    DM-->>A: check({})
    A->>F: Full strict check schema + same context; force check
    F-->>A: check({roll: {kind: gather, category: herbs}})
    A->>L: One completed check call
    L->>E: Existing validated tool implementation
    E-->>L: Existing result
    L->>DM: Result; continue normal narration
```

The first wire definition for a deferred verb keeps its **existing name and
description**, but has `input_schema` equal to:

```json
{"type":"object","properties":{},"required":[],"additionalProperties":false}
```

It also has `strict: true`. These are internal selection tools, created as typed
LiveKit `FunctionTool`s with a zero-argument signature. Their bodies raise if ever
executed. Do not use `raw_schema`: in installed LiveKit 1.8.1, `RawFunctionTool`
emission omits `strict` even when global strict is enabled.

The argument request contains **only the selected original FunctionTool**, with
`_strict_tool_schema=True` and a forced named tool choice. Do not leave the full
schema list attached while setting `tool_choice`; it is the transmitted list that
must fit. Preserve the original descriptions, field types, and discriminated nouns.

The coordinator copies the current chat context, including the latest player
utterance, Stage/NOW state, and prior tool results, and adds a private instruction
to populate the selected verb. It does not summarize context into another freeform
plan. The argument request may only produce that named call; it cannot hand off,
execute a tool, or recursively request more tools. Its text is not spoken.

The actual LiveKit probe selected `check` automatically for “I want to forage for
herbs,” then produced `{"roll":{"kind":"gather","category":"herbs"}}` through
the forced original tool. The vendor validator accepted it. A second turn with a
completed call and an explicitly synthetic tool result in history also succeeded.
No game implementation ran. The plugin represented zero-argument selection as an
empty argument string; normalize **only that known selection case** to `{}`.

## 5. Integration and execution invariants

Implement a coordinator at `BaseGameAgent.llm_node`, backed by small modules such as
`strict_tool_policy.py` and `strict_tool_generation.py`. Keep the underlying
Anthropic plugin for request conversion, streaming, caching, and provider errors.
Declare each agent's profile explicitly; do not infer it from location or tool count.
Keep the original full tool objects registered on each agent.

1. **Respect the effective tool list.** Intersect the profile's deferred names with
   the tools passed to `llm_node`. A restricted `generate_reply(tools=[...])` cannot
   regain excluded tools. Honor `tool_choice="none"`; a forced named choice can
   go straight to that tool's full-schema request without a selection request.
2. **Selection never escapes.** Intercept selection calls before yielding tool-call
   chunks. They never enter canonical chat history, consume a LiveKit tool step,
   or reach a game function. Assert that their arguments are empty.
3. **One completed logical call.** Require a complete response, the selected name,
   exactly one argument call, valid JSON, and validation against the original
   argument model before emission. Map it to the selection's call ID; retain one
   canonical call/result pair. Never parse and execute partial arguments.
4. **Keep execution with LiveKit.** Emit the real name and full arguments through
   ordinary `ChatChunk`/`FunctionToolCall` objects. Existing `RunContext`, duplicate
   handling, `@db_tool`, ToolError, handoff, and engine checks remain authoritative.
   The coordinator never calls `_impl` functions itself.
5. **Preserve batch semantics.** If selection returns several calls, hold the batch,
   fill its deferred arguments, and emit the completed calls in original order to
   LiveKit's existing scheduler. No part executes on an argument-preparation failure.
   Bound concurrent preparation by that returned batch; do not recursively fan out.
   Do not silently disable ordinary parallel calls to simplify the adapter: doing
   so adds another latency change. The initial sequential probe does not test batches.
6. **Propagate cancellation.** Player interruption, agent handoff, session closure,
   and generation cancellation cancel both requests. Check generation ownership
   before emitting a completed call. Engine state may change between preparation
   and execution, so legality is checked again in the existing execution path.
7. **Fail visibly, without mutation.** API rejection, truncation, malformed output,
   wrong tool name, or validation failure emits no executable call. Bound retries
   to argument preparation and the existing connection policy. Exhaustion reports
   an unresolved turn; it never quietly retries with strict off or narrates success.
8. **Count real requests once.** Capture usage for selection, preparation, and any
   retries separately through `TokenTracker`. Do not hide the extra cost or count
   inner usage again as an aggregate outer response.

There is a specific integration hazard in the current `BaseGameAgent.llm_node`:
`yielded_any` is set even for a usage-only chunk, and a subsequent exception then
returns silently. Internal selection/usage progress must not make a failed argument
request look like a completed player response. Add an explicit failure path and
fault-inject it both before and after any spoken preamble. This is part of this
coordinator's implementation, not a claim that the current retry loop is sufficient.

## 6. Cache, latency, and cost

Keep one stable selection schema list per mode and one stable preparation schema
per deferred verb. Schema policy is a release artifact; do not adapt it after a
400 in a player's turn. An individual full schema that outgrows the provider gets
a measured domain redesign, not silent projection to a looser schema.

Anthropic caches prompt prefixes in tools → system → messages order. A preparation
request has a different tools prefix, so it cannot reuse the selection prefix.
Repeated requests for the same preparation schema may reuse their own prefix;
verify this rather than assuming every switch is free or every switch evicts a
single shared cache. [Prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)

Preflight and warm every actual request surface for each production model before
routing sessions to a release. Include all selection profiles and every deferred
full schema, not just the three large schemas investigated here. Compilation took
tens of seconds in the initial acceptance experiments (one exploration selection
request took about 85 seconds); a player's first action must not discover this.
Treat warmup as readiness work, with bounded operational failure handling, not an
unbounded wait inside a voice turn. Grammar caching is distinct from prompt caching.

The two LiveKit preparation trials took **6.50 s and 2.61 s** from selection start
to validated arguments. Both reported zero prompt-cache reads. These are tiny,
non-production prompts, not a latency distribution, baseline comparison, or full
voice measurement. They exclude execution and post-result narration. They do
**not** demonstrate compliance with the voice target.

The implementation benchmark must compare strict staging with the present
non-strict path on identical full prompts, user audio, seeded state, model,
sampling settings, and representative repeated sessions:

| Measurement | Release condition |
|---|---|
| End of player speech → first meaningful audio, p50/p95 | Retain the project's 1,500 ms target; propose p95 as the acceptance statistic |
| End of speech → first audible resolved outcome, p50/p95 | Report baseline and added delay separately; human listening approval required before rollout |
| Action completion and repeated combat chains | No dropped action, duplicate mutation, or hidden exhaustion of tool steps |
| Requests, input/output tokens, cache reads/writes, cost per session | Count the added preparation calls; compare with the existing session cost model |
| Cold/expired-cache and warm sessions | Report separately; demonstrate readiness/warmup and player-visible failure behavior |

Measure at least 100 paired affected turns across checks, travel, activation,
dispatch, and combat, plus unaffected conversational/direct-tool turns. Exercise
multiple deferred calls in a turn. For D deferred calls, the normal path gains D
preparation requests, before retries; no-tool and direct-only turns gain none.
Do not claim the work fits by speaking filler early. A real acknowledgement may
stream from the DM, but the time until the player hears the result remains visible.

If latency fails, stop before the production flip. First reduce unnecessary
staging using new live measurements and improve context/cache handling. If those
are insufficient, compare a provider/model that accepts the complete surface or
redesign the specific noun shapes. Neither is assumed equivalent in cost or DM
quality. The current measurements do not justify a promised latency win.

## 7. Verification and rollout

The work is a proposed implementation sequence, not added sprint cards.

**First, make the provider boundary reproducible.** Extend
`apps/agent/probe_strict_limits.py` to enumerate the actual selection and preparation
requests produced by the coordinator. Report model, dependency versions, schema
fingerprint, acceptance, stop reason, and timing. Require `strict: true` on every
tool. A missing key or skipped live request cannot pass the acceptance gate.
Keep local budget checks, but apply them to actual outbound requests. Retain a
separate logical-verb-count guard; never relabel a passing structural count as proof
that the provider will compile it.

**Second, implement and test the coordinator with strict enabled in its test
configuration.** Use the installed vendor ToolContext, serializer, argument binder,
and stream types. Mock our transport seam where appropriate; use live requests to
test the real compiler. Proposed tests belong under `apps/agent/tests/strict_tools/`.
Each guard needs an injected defect that makes it fail:

| Contract | Fault injection |
|---|---|
| Every request fits and is strict | Reattach original full exploration schemas; drop one strict flag |
| Original typed noun reaches execution once | Leak the empty selector, change the selected name, or emit the final call twice |
| No action before complete validated arguments | Truncate JSON; omit a required field; return a wrong variant; fail one member of a batch |
| Cancellation prevents execution | Interrupt while preparation is in flight; hand off before completion |
| Tool results and errors remain paired | Mismatch call ID; propagate an engine ToolError and exercise the following turn |
| Reply scoping is preserved | Restrict tools, then attempt an excluded verb; force no tools and attempt selection |
| Failures remain visible | Fail preparation after usage-only progress and after a spoken preamble |
| Cost/latency reporting is complete | Drop preparation usage, double-count it, or time only the first request |

**Third, drive real gameplay and voice.** Extend the existing real-LLM acceptance
lane with all six agents, each deferred verb, handoffs, and representative noun
variants. Include every `check` kind, training with/without spell selection,
multi-actor declarations, self/single/multiple activation targets, reaction
windows, multi-step turns, retries, and interrupted speech. A compiler request
that merely says “hi” is not a tool-selection or gameplay test.

**Finally, switch production and its harnesses together after both correctness and
latency pass.** Replace duplicated construction with one tested gameplay LLM factory
that explicitly enables strict. The current false-flag inventory is:

- `apps/agent/agent.py`.
- `apps/agent/tests/test_livekit_upgrade.py`.
- `apps/agent/tests/test_strict_tool_budget.py` (the deliberate strict-off assertion).
- `apps/agent/tests/acceptance/test_m1_5_training_cycle.py`.
- `apps/agent/tests/acceptance/test_m1_6_companion_errands.py`.
- `apps/agent/tests/acceptance/test_m29_combat_reactions.py` and its feature description.
- `apps/agent/tests/acceptance/test_combat_cache_prefix.py`.

Re-inventory at implementation time. Replace source-only flag assertions with tests
of the factory and actual emitted requests. Run the Python lane and required
acceptance checks; measure the new behavior at the voice surface. No TypeScript
wire format, authored content, or database schema needs to change for this design.
If implementation introduces such a change, name and verify both language sides.

Roll out by explicit release/configuration selection. Rollback is a deliberate
return to the prior non-strict release if correctness or latency regresses; never
an automatic per-call fallback. Only after the production switch lands should
ADR 0004's interim exception be retired and ADR 0008's outcome be marked achieved.
This proposal also revises ADR 0008's ban on an extra selection/preparation request;
the rich noun schemas and stable mode surfaces are retained.

## 8. Alternatives and boundaries

| Alternative | Judgment |
|---|---|
| Keep strict off and rely on local validation | Current baseline; retains repair/coercion and avoidable failures |
| Strict only for simple verbs | Helps the least complex arguments; does not meet the full-strict objective |
| Make every default explicit | Useful future schema hygiene; measured insufficient alone |
| Shorten descriptions | Can reduce tokens; historical stripping experiment did not fix compilation |
| Split each noun kind into its own tool | Spends tool slots and reverses the useful verb/noun interface |
| Pass a JSON string or an open dictionary | Only the outer wrapper is constrained; defeats the objective |
| Put ephemeral noun IDs in a generic execute tool | Requires a complete producer and freshness/authorization contract; arbitrary checks still need their arguments produced somewhere |
| Swap toolsets every combat beat | Adds context/cache complexity and capability-availability risks; not required by the measured partition |
| Change model/provider | Potential single-request alternative; requires separate compatibility, quality, latency, and cost evaluation |

This is an application design, not a proposed patch to LiveKit internals. No new
game action or player-visible “prepare” step is introduced. New content continues
to select existing verbs by IDs surfaced in Stage/NOW/query results, preserving
the producer requirement and keeping game rules in deterministic code.

## 9. Reproducing the research

The current baseline is the existing command, run from `apps/agent`:

```sh
uv run --env-file ../../.env python probe_strict_limits.py
```

To reproduce the partition independently, import `AGENTS` from that module, emit
each tool list with `ToolContext(...).parse_function_tools("anthropic", strict=True)`,
and copy the emitted dictionaries. Replace only the `input_schema` of names in
the policy table with the closed empty object from section 4. Keep all `strict`
flags true. Submit each complete list to `messages.create` on the pinned Haiku
model, with a small greeting and `max_tokens=16`. Separately submit each original
deferred tool as a one-tool list. This tests compilation, not successful execution;
`max_tokens` termination in these greeting probes is not a valid argument call.

The streaming feasibility probe instead constructed real zero-argument
`@function_tool` selectors, used `anthropic.LLM(..., _strict_tool_schema=True)`,
and consumed `chat(...).collect()`. It forced the selected original tool in the
second request, parsed its complete arguments, and called LiveKit's
`validated_arguments`. Repeat with full call/result history. Increase the output
budget for actual arguments and reject incomplete calls.

Research probes were temporary and did not edit runtime code. The existing
schema-budget pytest run was attempted but could not start: shared test setup
tried to start PostgreSQL and collided with an allocated `127.0.0.1:55432` port.
No pytest pass or end-to-end voice validation is claimed. The emitted-schema
measurements, local vendor-validation observations, live compiler experiments,
and two streaming tool-generation trials above did execute.

## 10. Seeded Luna gameplay evidence

On 2026-09-20, the real OpenAI Luna acceptance lane executed one seeded case for
each of 27 representative actions across exploration, combat, dispatch,
onboarding, blacksmith, and creation. The cases use the production Luna factory,
strict schemas, LiveKit's real argument binder and tool executor, a migrated
isolated PostgreSQL database, and the deterministic game engine. Handoff rows
assert the resulting agent type. Mutation rows re-read persisted state; query and
conversation rows assert that state did not change.

The manifest is
`apps/agent/tests/acceptance/strict_luna_case_manifest.json`. Its loader rejects a
missing or moved file, an empty corpus, duplicate, missing or unknown IDs, and
unknown tool, variant, or prerequisite keys. Each seed and assertion must match
its case id. Every id must also
route to a named persisted-state branch — an unrouted row would be graded by
nothing at all. Skill, social, discovery, save, and dice rows check their
result fields and the expected persisted change or absence of change. The gather
row compares the whole changed inventory set against the materials the tool
reported, and the activation rows compare the persisted Stamina and Focus pools
against the cost the tool reported. The live run writes one JSON object per row to
`/tmp/divineruin_strict_luna_gameplay.jsonl`, including completion, pass/failure,
diagnostic, calls, request count, token usage, model, estimated cost, and
pricing provenance. Failed rows are written in `finally` and
retain `completion: "failed"` and `passed: false`.

Run the closed matrix with:

```sh
uv run --project apps/agent --env-file .env pytest apps/agent/tests/strict_tools/test_gameplay_quality.py apps/agent/tests/acceptance/test_strict_luna_gameplay.py -q
```

The measured run passed all 27 rows and the report completeness guard: 56 model
requests, 268,411 input tokens, 266,296 cached input tokens, and 1,849 output
tokens. Estimated cost was **$0.00796772**. The estimate uses the OpenAI
`gpt-5.6-luna` standard text rates retrieved 2026-09-20: $0.20 per million input
tokens, $0.02 per million cached input tokens, and $1.20 per million output tokens.
[The model page is the pricing source.](https://developers.openai.com/api/docs/models/gpt-5.6-luna)

This is single-model semantic gameplay evidence. It does not rank providers.

## 11. Production decision

On 2026-09-20 the human approved GPT-5.6 Luna for the current production rollout.
An unset `GAMEPLAY_LLM` selects `openai-luna`; `GAMEPLAY_LLM=anthropic` remains an
explicit rollback. Luna uses `reasoning_effort="none"` and
`_strict_tool_schema=True`. Startup requires `OPENAI_API_KEY` for the default and
requires `ANTHROPIC_API_KEY` independently for background narration, summaries,
world news, companion idle writing, and god whispers; the rollback selection also
uses that Anthropic key for gameplay.

The decision accepts the measured direct-session diagnostic: direct replies
started in 0.994–1.395 seconds, while the constrained gather tool path started in
1.813–3.460 seconds and missed the 1.5-second target. This runner does not use the
production multiplayer input path. It uses 0.5-second endpointing rather than the
production 1.0-second floor and excludes the per-player transcriber queue and
`MultiplayerInput` serialization. These values therefore cannot establish production
end-to-end latency. Stage-level production measurement and real microphone testing
remain follow-up optimization, not rollout gates.

## 12. GPT-6 Luna route (2026-09-22)

The default gameplay route now names `gpt-6-luna`. It retains
`reasoning_effort="none"`, strict tool schemas, and `GAMEPLAY_LLM=anthropic` as an
explicit rollback. The current cost report uses the [GPT-6 Luna model page](https://developers.openai.com/api/docs/models/gpt-6-luna)
standard text rates retrieved 2026-09-22: $0.10 per million input tokens, $0.01
per million cached input tokens, and $0.50 per million output tokens.

The 2026-09-20 measurements above belong to GPT-5.6 Luna. On 2026-09-22 the human
approved one paid run of each GPT-6 acceptance. The gather continuation passed:
narration with no follow-up call, 5,679 input and 26 output tokens. The 27-case
seeded matrix passed all 27 rows and the completeness guard: 56 model requests,
268,402 input tokens, 226,600 cached input tokens, 1,753 output tokens, and an
estimated **$0.0073227**. The GPT-5.6 run cost $0.00796772, but 266,296 of its
input tokens were cached; at GPT-5.6's cache hit rate, the GPT-6 rates would price
this run near $0.0038. Cache warmth, not the model, explains most of the gap
between the two runs. Voice latency was not measured for GPT-6.
