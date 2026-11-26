Bump: patch

Aelora's guardians regain up to 2 Stamina when Intercept takes damage for an
ally. Her wardens regain the same amount when Bark Skin applies.

Release steps:
- After deploy, run `SEED_PRODUCTION=1 bun run seed` from the deployed repository
  root with its production environment. This unpaid command writes production
  content. Restart the agent and worker using the existing deployment procedure
  so they reload the patron catalog.
