Bump: minor

Druids and wardens can use Bark Skin to turn a narrow hit into a miss. The
reaction adds 2 AC against the triggering attack and through the end of the
round. A natural 20 still hits. The Primal spell and the Thornveld Guardian
Shield's free cast still need reaction or item support.

Release steps:
- After deploy, run `SEED_PRODUCTION=1 bun run seed` from the deployed repository
  root with its production environment. This unpaid command writes production
  content and invalidates catalog caches.
