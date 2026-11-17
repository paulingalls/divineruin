# Release notes in flight

`develop` is the trunk. Sprints and free patches land there, and `main` is what is live.
Each branch that lands adds one note here: `changes/<git-branch>.md`. A `/` in the branch
name becomes a subdirectory. The branch does not edit `package.json`'s version or
`CHANGELOG.md`; land refuses a branch that does.

A note has:

- exactly one `Bump: major|minor|patch` line (sprints use `minor`);
- prose for the changelog, written for players and the team;
- a `Release steps:` line, either `Release steps: none.` or a list of exact commands. For
  each command, say where it runs, whether it is paid or writes production, and whether it
  runs before or after deploy.

```markdown
Bump: minor

The ruins have a fight tuned for a level-2 player.

Release steps: none.
```

After the PR merges and `xp.py sprint post-merge` (or `free post-merge`) has run, the
merger runs `xp.py release stamp` on a clean `develop` equal to `origin/develop`. It folds
every pending note into one version after the latest `vX.Y.Z` tag on origin, using the
highest `Bump`. It writes `package.json` and one `CHANGELOG.md` section, deletes the
notes, and pushes `develop` and the annotated tag together.

To make a stamped release live, deploy it, verify it, then run
`scripts/promote-main.sh <tag>`. That fast-forwards `main` to it and never merges.
