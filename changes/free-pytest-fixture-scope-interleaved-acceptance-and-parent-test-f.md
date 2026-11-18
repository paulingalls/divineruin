Bump: patch

The agent test tooling moves to pytest 9.2.0 and pytest-bdd 9.0.1. One pytest run that mixes acceptance and regular test files no longer loses the acceptance fixtures. Nothing players see changes.

Release steps: none. After pulling, run `uv sync --project apps/agent --frozen` in each local checkout.
