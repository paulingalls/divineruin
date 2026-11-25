Bump: minor

Every catalog weapon now has a category, range and kind, and both catalog loaders validate weapon profiles and archetype proficiency. A character can equip a weapon they are not trained with, and the DM warns them when they do. Their attacks with it roll at disadvantage, which cancels with advantage as usual. The proficiency bonus still applies. Artificers, spies and bards are now proficient with their starting Warhammer, Rapier and Lute, so every starting kit is proficient.

Release steps:

- Set `SEED_PRODUCTION=1` in the deployment seed environment and run `bun run seed` from the repository root after deploying the updated seed code and before restarting the catalog consumers. This unpaid command writes the production catalog.
