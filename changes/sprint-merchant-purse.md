Bump: minor

Shopkeepers now have a day's coin. Each one starts the day with a purse that suits their town. A prosperous Accord merchant can buy a fine piece; Millhaven's innkeeper has a few silver to spare. When a shop can't pay in full, the shopkeeper offers what they have. A friendly shopkeeper will also take the piece on consignment: it sells in one to four days, and you come back for 90% of its price. Leave the coin for more than a week and the item comes back to you.

Shops won't buy endless copies of one thing in a day: up to three of a common weapon, five of a consumable, two of an uncommon item, one of a rare one. Past that they'll take one more at half price, then nothing until dawn. Purses refill at dawn on the new Aethos clock, which runs on US Eastern time.

Release steps:
- Before the agent starts after deploy, apply migration `scripts/migrations/071_merchant_state.sql` and reseed content (`bun run seed`) against the production database. Both write production; neither is paid. The migration adds the merchant purse table, and the reseed loads the purse allocations and the Aethos clock epoch.
