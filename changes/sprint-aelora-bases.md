Bump: minor

A guardian can spend 3 Stamina to take a hit's damage for an ally within 5 ft.
The guardian's own reductions apply, and the struck ally still gets the hit's
non-damage effects. One guardian can Intercept each hit. Shield wear and broken
concentration follow whoever took the damage.

Druids and wardens can use Bark Skin to turn a narrow hit into a miss. It adds
2 AC against the triggering attack and until the end of the round. A natural 20
still hits.

Aelora's guardians regain up to 2 Stamina when Intercept takes damage for an
ally, and her wardens regain the same when Bark Skin applies. Her artificers,
bards and diplomats gain +1 from Common Bond on live Crafting checks, recipe
experiments and newly started crafting projects, and it stacks with Craft
Blessing. Projects queued before this release resolve without it.

Still pending, and recorded in docs/milestones/REMAINING.md and
14_engine_completeness.md:
- Guardian upgrades: Shield Mastery's 1d8 reduction, Warden-Commander's 10 ft
  range, and the Thornridge's Stand 15 ft override and Last Wall.
- Bark Skin: the Primal Bark Skin spell (no reaction path offers it) and the
  Thornveld Guardian Shield's free cast.

Release steps:
- Run these after the existing deploy (scripts/deploy-up.sh), from the deployed
  repository root with its production environment loaded:
  `SEED_PRODUCTION=1 bun run seed`. It is unpaid, writes production content
  (patron catalog, abilities, spells) and invalidates catalog caches.
- Then restart the agent and the worker using the existing deployment procedure,
  so they reload the patron catalog.
