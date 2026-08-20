# apps/agent — Python DM agent

## Python test lanes (placement by directory)

- **Fast lane** — everything under `apps/agent/tests/` *except* `tests/acceptance/`. Run by `test:python` / `test:all` (`pytest -m "not acceptance"`). Holds pure-logic tests **and** simple real-PG tests against the shared dev DB at `:55432` — `tests/conftest.py` auto-starts docker compose if it's down (fail-loud if Docker is absent; tests are never silently skipped). Real-PG tests here isolate via unique keys + cleanup (see the `_db_lifecycle` / `dev_db_pool` pattern). Put a real-PG test here when it's a single-table / single-concern round-trip.
- **Acceptance lane** — `apps/agent/tests/acceptance/` only (marker auto-applied by directory). Run by `test:acceptance` (pre-push). Per-run **testcontainer** Postgres + LiveKit dev-server. Put a test here when it's a multi-system / LiveKit / end-to-end capstone needing per-run isolation.
