# ADR 0002 — Agent tool error shape

Status: **Accepted** (2026-05-20) — sprint-009 story-007
Concerns: `130a5180c4cd`
Debt: `effcd01dc050`

## Decision

**LiveKit's `ToolError` exception is the canonical way for agent `@function_tool`
functions to report a recoverable, player-facing error.**

```python
from livekit.agents.llm import ToolError

raise ToolError("Unknown training program: nonexistent")
```

The framework catches `ToolError`, places the message into the tool-result envelope,
and the LLM sees the message when generating its next turn (`livekit/agents/llm/
tool_context.py` — `ToolError` at L111, whose message is documented "visible to the
LLM", L118). Tools no
longer hand-build a JSON error dict and `return json.dumps(...)`.

This is documentation + direction only. **This ADR does not migrate any code.** It
records the target shape so the two coexisting shapes (below) stop multiplying, and
charters the migration as a separately-scheduled story (debt `effcd01dc050`).

## Context

Story-003's close-reviewer raised concern `130a5180c4cd`: `training_tools.py` (M1.5)
returns errors as `{"error": <prose>, "code": <slug>}` JSON, while the ~11 peer agent
tools return code-less `{"error": <prose>}` JSON. Two shapes coexist, and zero tools
use the LiveKit-idiomatic `ToolError`. `training_tools.py`'s own module docstring
(L1-10) already names `ToolError` as the migration target — this ADR ratifies that.

Crucially, the architecture doc **already prescribes `ToolError`**:
`docs/technical_architecture.md` § Error Recovery (L875-881) states "The tool raises
`ToolError` with a descriptive message. LiveKit's framework returns this to the LLM,
which narrates around it." So both JSON-dict shapes are **drift** from the documented
design — this ADR is not a new direction, it re-aligns the code with the architecture.

### Inventory — current error shape per agent tool (apps/agent/)

| File | Current shape | Notes |
| --- | --- | --- |
| `training_tools.py` | `{"error", "code"}` | Only file with `code`. Helper `_error_json()` (L38-40). 9 slugs. |
| `movement_tools.py` | code-less `{"error"}` | |
| `quest_tools.py` | code-less `{"error"}` | |
| `progression_tools.py` | code-less `{"error"}` | |
| `query_tools.py` | code-less `{"error"}` | |
| `inventory_tools.py` | code-less `{"error"}` | |
| `environment_tools.py` | code-less `{"error"}` | |
| `check_tools.py` | code-less `{"error"}` | Wraps caught `ValueError` as `{"error": str(e)}`. |
| `onboarding_tools.py` | code-less `{"error"}` | |
| `session_tools.py` | code-less `{"error"}` | |
| `creation_tools.py` | code-less `{"error"}` | Wraps caught `ValueError`/`Exception`. |
| `scene_tools.py` | code-less `{"error"}` | |
| `combat_tools.py` | n/a (router) | Delegates to `combat_{support,init,turn,end}.py`. |

Summary: 1 dual-key, 11 code-less, 0 `ToolError`. `ToolError` is exported by
`livekit.agents.llm` and used throughout LiveKit's own example agents.

## Rationale

1. **Framework-native.** `ToolError` is the documented LiveKit mechanism for surfacing
   a tool error to the LLM. Returning a JSON string is a workaround that re-implements
   what the framework already does — and inconsistently, across two shapes.
2. **The audience is the LLM, not code.** Agent tool errors are read by the DM model to
   decide how to narrate, then spoken to the player. The model reads prose. A
   raised-exception message reaches it identically to a JSON `"error"` value.
3. **Less ceremony.** `raise ToolError("...")` replaces `return json.dumps({"error":
   "..."})` and removes per-module helpers like `_error_json`.

## Disposition of the `code` slugs

`ToolError(message: str)` carries **no machine-readable code** — message only. The
`training_tools` slugs (`INVALID_PROGRAM_ID`, `UNKNOWN_PROGRAM`, `UNKNOWN_ACTIVITY_TYPE`,
`TRAINING_SLOT_FULL`, `INVALID_TRAINING_ID`, `UNKNOWN_TRAINING`, `TRAINING_NOT_OWNED`,
`TRAINING_WRONG_STATE`, `INVALID_DECISION`) **are dropped** under this decision.

Justification: **no production caller switches on `code`.** Errors flow tool → framework
→ LLM → narration; nothing in the agent branches on the slug. The slugs exist only in
`training_tools.py` and are asserted by `test_training_tools.py` (both as `result["code"]`
subscripts and full-dict equality) — those tests pin the *current* shape, not a production
contract. The migration story retires those assertions along with the JSON shape.

If a future need for machine-switchable error classification arises (e.g. a client-side
retry policy), the prose message can carry a stable leading token (`"TRAINING_SLOT_FULL:
a training cycle is already in progress"`) — but this ADR does not pre-commit to that;
it would be designed against the concrete need.

## Migration path (deferred — NOT this story)

Charters debt `effcd01dc050`. A future migration story will, per tool:

1. Replace `return json.dumps({"error": msg, ...})` with `raise ToolError(msg)`.
2. Delete per-module error helpers (`training_tools._error_json`).
3. Update each tool's tests: assert the raised `ToolError` (and its message) instead of
   a returned dict; drop `code` assertions.
4. Confirm no caller treats the tool's return value as an error sentinel (current audit:
   none do).

The migration is mechanical but touches all 12 files + their tests, so it is its own
story rather than a rider on this ADR.

## Consequences

**Simpler**
- One error mechanism across all agent tools, matching LiveKit idiom.
- Removes hand-rolled JSON error envelopes and per-module helpers.

**Harder / accepted trade-offs**
- The `code` slugs are lost (see disposition above) — accepted, since no caller uses them.
- The migration is a cross-cutting change to 12 files; sequenced as a dedicated story so
  it lands with full test review rather than piecemeal.
- Until the migration runs, the two shapes still coexist. This ADR is the interim
  authority: **new** agent tools should raise `ToolError` from day one rather than adding
  to the code-less majority.

## Out of scope (do not do in story-007)

- Any code change to `training_tools.py` or peer tools.
- The migration itself (debt `effcd01dc050`).
- Designing a machine-code-carrying message convention (only if a real need appears).
