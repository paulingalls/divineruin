# Sprint 63 retrospective

Six stories shipped the catalog cutover and live inventory refresh. The ten
named encounters now span levels 1–14. M32 is complete; Named creature behavior
and generated encounters remain future milestones. The level-14 settlement
preserves Knight, Mawling and Shadeling with human-approved role/count changes.
Its real warrior/companion diagnostics are bounded examples, not win-rate claims.

Review and fault injections caught replayed enemy actives, invalid action shapes,
flat damage normalization, source walks that abstained, stale inventory responses,
missing home-screen polling and copied selected-item details. Real database,
browser and native checks exposed contracts mocked checks could not certify.

The close review also reproduced an older buffered agent snapshot overwriting a newer HTTP result. The repair gives each owner a transactional database revision and captures it with inventory in one statement; both transports use the same revision guard. Arrival order and local request generations cannot establish committed inventory order.

The lead missed completed background jobs by ending its turn. Interrupted pytest
also leaked containers because normal fixture cleanup could not run. Active
terminal polling now keeps handoffs visible; owned PID/UUID naming and the strict
sweeper recover abandoned Postgres fixtures without touching unrelated containers.
The permission interruption's cause remains unproved. The plugin cache updated
to 0.33.0 later; that observation does not establish the earlier cause.

Constraints 1, 9 and 12 earned their place by exposing false greens. Repeated
broad story suites cost more than they returned. The human replaced that policy
with focused AC checks, static story checks and one final full regression gate.
The executable changes are in config, hooks and constraints; this retro removes
the contradictory broad-Python handback rule from system.md and adds explicit
native CLI monitoring. Targeted close checks also repaired a seed fixture and
classified the new Python E2E corpus in the existing source-walk floor tests.

The temporary all-Codex/GPT-6.1-Sol role experiment remains through the initial
PR. Restore the original role block afterward while keeping the new test policy.

Human close scope: triage Sprint 63 findings. XP 0.33.0 surfaced historical
review notes during close; the older backlog remains unchanged for a separate
cleanup. This is a scope exception to historical triage, not a claim that those
findings are fixed or dropped. All current sprint findings have dispositions.
