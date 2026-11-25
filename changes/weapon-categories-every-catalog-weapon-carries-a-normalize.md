Bump: patch

Every catalog weapon now has a category, range and kind. Both catalog loaders validate weapon profiles and archetype proficiency. Artificers, spies and bards are proficient with their starting Warhammer, Rapier and Lute.

Release steps:

- Set `SEED_PRODUCTION=1` in the deployment seed environment and run `bun run seed` from the repository root after deploying the updated seed code and before restarting the catalog consumers. This unpaid command writes the production catalog.
