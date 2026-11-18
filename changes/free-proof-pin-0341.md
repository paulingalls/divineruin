Bump: patch

The test runner is pinned to proof v0.34.1. Before the fix, staged runs (every free patch's acceptance and every commit hook) read every input file through git for every task, so setup on a staged sprint run took 25 minutes or more. Setup now takes about 24 seconds. There is no player-facing change.

Release steps: none.
