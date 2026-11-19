Bump: patch

Scheduled super tests now check develop in a dedicated clone on the test host, with their own Docker project and port offset. Each run tears its Docker stack down when it ends, pass or fail, so an idle super stack no longer holds host ports between runs.

Release steps:

- After merge, stop any running old super job on each former host. In `$HOME/.xp/super/divineruin`, run `bash scripts/teardown-worktree.sh`. Then run `git worktree remove "$HOME/.xp/super/divineruin"` from the host repository that registered it. Both commands are unpaid and write no production data. Leave a dirty worktree in place for inspection.
- After merge, run `bash scripts/super-test-install.sh` from the checkout on the mini. This is unpaid and writes no production data. The runner defaults to `$HOME/.xp/super/divineruin-super` and port offset 9000.
