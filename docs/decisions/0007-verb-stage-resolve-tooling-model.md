# ADR 0007 — Verb / Stage / Resolve tooling model

Status: **Accepted** (2026-06-02) — design session, free branch
`paulingalls/free-2026-06-02-phase2-refactor`. Realized across the Phase-2 enabler
migration milestones (see `docs/agent_verbs_and_stages.md` §11).
Evolves: **ADR 0004** (agent-tool-scaling). SMM decision: `verbs-stages-architecture`.

## Decision

**Draw the agent/tool boundary by operation kind, not by feature.** Every operation is
one of three kinds:

- **Sense** — information that informs a decision. Two channels: the **Stage** (pushed
  warm/hot context, assembled by the async workers) and `query` (pulled on demand).
- **Act** — a decision at a genuine decision point. Acts are a **small fixed verb
  vocabulary** (12 core verbs), parameterized by typed targets resolved against
  content/DB. New content never adds a tool.
- **Resolve** — the deterministic mechanical fallout of an Act. A Resolve is **never a
  tool**; it runs inside an Act (rules-engine → DB write → `E.*` event) and reports back
  for narration.

And: **an agent is a group of verbs (coarse, tracks mode of play); a location is a Stage
(fine, fluid).** Region agents (`CityAgent`/`WildernessAgent`/`DungeonAgent`) collapse into
**one exploration agent** fed by a location-aware Stage. Numbers live in the rules engine +
HUD; the voice speaks narrative bands.

Full design: `docs/agent_verbs_and_stages.md`.

## Context

ADR 0004 capped the tool problem by **rationing** Anthropic's 20-strict-tool limit:
split overloaded agents along activity boundaries and hand off. It worked, but left City at
**exactly 20** — a ceiling, not headroom (debt `e665104c753a`) — and 0004 itself flagged
the next moves as deferred: consolidate the `query_*` family (done → `query_info`), then the
check family — `request_skill_check`/`request_saving_throw`/`roll_dice`/`discover_hidden_element`
fold into `check` (with `request_attack` moving to Combat's `attack`, §10), unifying on a
numeric DC.

Meanwhile the same root cause produced correctness debt: `quest_tools.update_quest`
hand-rolls a copy of `award_xp`'s level-up logic and drops the L10/15/20 auto-grants + L5
fork cue (`ee947a154b10`); `_resolve_milestone_impl` stays reachable for tiers it no longer
owns (`2bba66ace8a8`). These are **consequences modeled as decisions** — Resolves that leaked
up into LLM-invoked tools.

M2.4 (Spell Acquisition) would add `learn_spell_from_scroll`/`prepare_spells` to a City with
zero headroom. Rationing one more slot does not scale; the tool set grows with content.

## Options considered

1. **Keep rationing (extend ADR 0004).** Reclaim a slot per new tool (consolidate
   `award_xp`/`award_divine_favor`, relocate a settlement tool) each time the ceiling binds.
   **Rejected:** treats the symptom; tool count still grows with content; M2.5 hits it again.
2. **ToolProxyToolset** (0004's reserve option). Dynamic tool discovery behind 2 proxy
   tools. **Rejected as the primary fix:** preserves caching but keeps the underlying
   noun-per-feature explosion and adds a framework concept; doesn't address the Resolve
   leakage or the duplicated consequence logic. Still available if a *mode* agent ever
   exceeds 20 after this model.
3. **Verb / Stage / Resolve recharacterization** (chosen). Collapse nouns into a fixed verb
   vocabulary, push consequences down into Resolves, push "what's actionable here" into the
   Stage. The ceiling stops binding because the tool set no longer tracks content. Completes
   0004's own deferred consolidations (check family folds into `check`).

## Consequences

**Better**
- **M2.4 adds zero tools.** Spell acquisition is `learn(spell, id)`; casting is
  `activate(id)`. Spells are content, not tool surface. The ceiling stops being a recurring
  blocker.
- Closes a class of bugs: duplicated consequence logic disappears when Resolves are the only
  place consequences run (`ee947a154b10`, `2bba66ace8a8`).
- One exploration agent keeps the prompt cache warm across movement (Golden Rule 5/6); the
  Stage changes cheaply per room instead of thrashing agents.
- Tiny tool descriptions: targets come from the Stage, effects from the rules engine.

**Watch**
- **Raises the bar on the Stage machinery.** Collapsing region agents means the background
  process must resolve fine location and scope the warm/hot layer correctly. The win moves
  work into `warm_prompts.py` / `background_process.py` + a content-schema migration
  (`hidden_element.attaches_to`, gated `exit.requires`).
- Model selection now rides the **mode-agent boundary** (exploration = Haiku; Combat/Creation
  may use Sonnet) rather than per-region agents.
- Staged migration (5 steps) must stay green throughout; the Resolve-consolidation step is
  behavior-preserving + one bugfix and goes first.

## Deferred (with insertion points — see design doc §12)

Multiplayer warm-layer merge (`entities_present` is the seam); a location `mode` hook for
interaction-rewriting places like the Hollow (Golden Rule 7); a player-initiated
`devote`/`pray` Act for spontaneous divine favor.
