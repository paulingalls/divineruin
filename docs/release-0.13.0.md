# v0.13.0 — Sprint 55

Combat sound events now resolve to bundled playable assets, including a dedicated save-damage cue. Weapon misses and low-health heartbeats use the human-selected v1 Stable Audio 3 takes. The event path exercises actual player creation and playback; shared sound IDs agree across Python and TypeScript.

Training narration follows the returned tool state and remaining time. Spell-study offers come from the actual eligible choices; unavailable spells are not offered, and an existing cycle prevents a second cycle. Real-agent scenarios and positive/negative judge calibration cover these behaviors.

Development lifecycle operations validate clone and checkout identity, resource labels, live service publication and listener ownership before connecting or changing resources. Pre-push acceptance uses checkout-owned settings while server/E2E retain their per-run services. Unit lanes mask external credentials. The release includes main's v0.12.0 dependency upgrades with the overlapping lifecycle changes reconciled.

Validation before sprint review: 7,106 Python tests, all workspace unit suites, 84 Playwright tests, 270 non-LLM acceptance tests, 300 full acceptance tests with one unrelated measurement skip, a real Expo web export, and the retained sprint-close falsifier batch. Final release remains subject to sprint review and its shipping-tree acceptance check.

## Operational handoff

Before deploying the agent, audit existing live spell-training cycles for missing, unknown or ineligible spell IDs under the new worker rules. This audit has not been performed against production; release does not imply deployment cleanup is complete.

During development, an old teardown accepted copied primary settings and deleted the original local primary database volume. That original data was not recovered. The retained backup and restored working database contain only data recreated after the incident. The lifecycle safeguards above are the corrective change; a seeded database is not recovery of the lost data.

See [the sprint retrospective](../.xp/retro-sprint-055.md) for the review findings and executable corrections.
