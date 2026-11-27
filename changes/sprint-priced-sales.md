Bump: minor

You can sell to the shops now. Tell the DM you want to trade, and the shop door creaks open. Then tell the shopkeeper what you're selling. A sale pays half the item's value in silver. Friendly shopkeepers pay more, unfriendly ones pay less, and hostile ones won't buy at all. Each shop buys only its own trade. Grimjaw takes weapons and armour, the temple takes potions and remedies, and the general stores take common goods. If a shop doesn't deal in what you're carrying, the shopkeeper tells you who might.

Finished crafts can be kept or sold by voice. Tell the DM which you choose, or use the button in the app. Selling a craft pays 80% of its value, once.

Release steps:
- Before the agent starts after deploy, reseed content: `bun run seed` against the production database. This writes production. It isn't paid. It loads the new sale prices, the shops' buying rules, the four shopkeepers' stock lists and the two new trade sounds.
- The trade sounds also need a mobile build that includes `content/action_sounds.json`. Older builds stay silent on the two new cues.
