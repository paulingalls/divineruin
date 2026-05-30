# Runbook: Reset a stuck async-activity resolution

**When to use:** the async worker logs a warning like

```
Activity <id> reverted N times (>= 5) — resolution may be persistently failing;
a manual reset clearing cached outcome/segments may be needed
```

This means one async activity (a crafting result or companion-errand) keeps
failing to finalize. The worker resolves outcomes in three steps — compute
outcome → render TTS audio → mark resolved — and on any failure it calls
`revert_claim`, which **intentionally preserves** the cached `outcome` and
`narration_segments` so the next tick skips the LLM and retries only the failed
step (the TTS-retry fast path, see `apps/agent/async_worker_claim.py`).

That fast path is a trap when the *cache itself* is bad — e.g. a poisoned
narration segment that fails TTS every tick. The worker reclaims, replays the
same bad cache, fails, reverts, forever. `resolve_attempts` counts these reverts;
once it crosses `RESOLVE_ATTEMPT_WARN_THRESHOLD` the warning above fires. The
fix is to clear the cached fields so the next tick re-resolves from scratch.

## 1. Find stuck activities

```sql
SELECT id, player_id, (data->>'resolve_attempts')::int AS attempts, data->>'status' AS status
FROM async_activities
WHERE (data->>'resolve_attempts')::int >= 5
  AND data->>'status' IN ('in_progress', 'resolving')
ORDER BY attempts DESC;
```

## 2. Reset one activity

Bind `$1` to the stuck activity id (or replace it with the literal id in psql).
This strips the cached outcome/narration and the transient claim fields, and puts
the row back to `in_progress` so the next worker tick resolves it cleanly:

```sql
UPDATE async_activities
SET data = (data - 'outcome' - 'narration_text' - 'narration_summary'
            - 'narration_segments' - 'decision_options'
            - 'resolve_attempts' - 'resolving_at')
           || '{"status": "in_progress"}'::jsonb
WHERE id = $1;
```

The activity's `parameters` (recipe id / errand details) are **not** touched —
they're the inputs the re-resolution needs.

## 3. Verify recovery

The next worker tick (≤ 5 min, `POLL_INTERVAL`) picks the row up. Confirm:

```sql
SELECT data->>'status' AS status, data->>'narration_audio_url' AS audio
FROM async_activities WHERE id = $1;
```

`status` should reach `resolved` with a non-null `narration_audio_url`, and the
`reverted N times` warning should stop. If it immediately climbs again, the
failure is upstream (TTS provider, audio dir, or the outcome inputs) — escalate
rather than re-reset.

## Notes

- This is the operator counterpart to the deliberate cache-preservation in
  `revert_claim` (concern `cc6195d3cc87`). The reset is verified end-to-end
  against a real schema by `apps/agent/tests/acceptance/test_ops_async_reset_runbook.py`,
  which runs the exact SQL block above — keep them in sync.
- A future terminal `failed` circuit-breaker state (decision
  `async-revert-circuit-breaker`) would automate this; until then it's manual.
