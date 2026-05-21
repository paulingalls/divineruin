# ADR 0004 — Scaling agent tools past the strict-tool limit

Status: **Accepted** (2026-05-20) — sprint-009 story-011
Concerns: `4da5c6f4d298`

## Decision

**When a gameplay agent would exceed Anthropic's 20-strict-tool limit, split it
along in-fiction activity boundaries into a focused sub-agent reached by a
location-driven handoff — rather than disabling strict tool schemas.**

The first application: `CityAgent` (25 tools) is decomposed by extracting
`TrainingAgent` (the mentor/training activity) and pruning two danger mechanics,
landing City at 20.

## Context

The acceptance harness (story-008) drove the real `CityAgent` against Claude for
the first time and hit `HTTP 400: Too many strict tools (25). The maximum number
of strict tools supported is 20` (concern `4da5c6f4d298`). The
`livekit-plugins-anthropic` LLM defaults `_strict_tool_schema=True`, and
`CityAgent` registered 25 tools — so every real city turn would 400. It was never
caught because city turns were previously exercised only by mocked tests.

Only `CityAgent` exceeded the cap; wilderness (15), dungeon (17), and combat (9)
are within it.

## Options considered

1. **Disable strict tool schema** (`_strict_tool_schema=False`). Sanctioned by
   LiveKit (it ships as the default for the Cerebras/Perplexity plugins) and a
   one-line change. **Rejected**: it papers over the limit, loses guaranteed
   schema-valid tool arguments (pushing validation into tool bodies), and gives
   none of the prompt-focusing / latency / cost benefits of splitting. It is debt,
   not a fix.
2. **Activity-handoff decomposition** (chosen). Split the overloaded agent into
   smaller context agents reached by handoff, matching LiveKit's documented
   "specialized contexts / conflicting tool access" guidance and the codebase's
   existing combat-handoff pattern. Each agent keeps a small, strict-clean tool
   set and a tighter system prompt.
3. **ToolProxyToolset** (dynamic tool discovery, BETA). Sends the LLM only 2 proxy
   tools and preserves prompt caching. Kept in reserve for an agent that still
   exceeds 20 after splitting; not needed here.

## The decomposition

- **TrainingAgent** (`training_agent.py`, mirrors `CombatAgent`): the 3 training
  `@function_tool`s + a navigation/query subset (so the player can talk to the
  mentor and leave). Reached when the player moves into a location flagged
  `agent_context: "training"`; control returns to the region agent when they move
  out.
- **Location-driven handoff**: `move_player` already swapped agents on a region
  crossing via a tuple return. It now also swaps on an **activity-context change**
  (`dest_is_training != current_is_training`). Unlike combat (which stores
  `pre_combat_agent_type` because `end_combat` doesn't move), training needs **no
  stored return state** — moving out of the training location re-resolves to the
  region agent naturally.
- **Pruned from City**: `request_attack` (city violence escalates via
  `start_combat`) and `request_saving_throw` (hazard saves live in dungeon/combat).
  Both remain in their proper agents. See decision `request-attack-vs-start-combat`.

Result: `CityAgent` 25 → 20.

## Rejected: a MerchantAgent

Commerce is **not** a real activity yet — there is no shop/buy/sell/currency
mechanic; `add_to_inventory`/`remove_from_inventory` are generic loot/grant/consume
tools used in dungeon too. A MerchantAgent would be a speculative split that breaks
generic item grants. Revisit if a real commerce mechanic lands.

## Consequences

**Better**
- City stays strict-clean; each context agent has a focused tool set + prompt.
- Reuses the proven combat-handoff pattern; no new framework concepts.

**Watch**
- City is at **exactly 20** — a budget ceiling, not headroom. Adding any city tool
  re-triggers the 400. Plan future city tools against this budget; adopt
  ToolProxyToolset if City must grow.
- Per-context agents need their system prompts to name only the tools they hold
  (see the prompt-tool drift fix, concern `b1591cb23262`).

## Deferred — check-family consolidation

`request_skill_check` / `request_saving_throw` / `request_attack` /
`discover_hidden_element` form a "roll vs a target" family. Consolidating them into
fewer parameterized tools is only moderately clean (polymorphic tool, harder LLM
selection) and is **deferred** (debt `75caa4bd340b`). The enabling simplification:
difficulty-tier and DC are the same concept (DC = Difficulty Class), and
`resolve_skill_check_dc` already rolls a skill vs a raw DC — unifying on numeric DC
would make a future `request_check(kind=...)` merge clean.
