Bump: patch

Proof's agent test sandboxes now reuse the checkout's agent virtualenv when it already matches the tree's lock, instead of building a cold one per sandbox; a tree with a different lock still gets its own fresh venv, and the shared one is never modified. A full sprint run on the Intel Mac dropped from 63 to 19 minutes. Two test races that the faster run exposed are fixed: the Choir refusal guard no longer counts the startup `session_init` as a gameplay effect, and the Leave summary spec pauses the browser clock at the browser's own time.

Release steps: run `uv sync --project apps/agent --frozen` in each checkout so its venv matches the lock and can be shared.
