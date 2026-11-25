Bump: minor

Three more patron gifts work in play. An Exalted follower of Veythar can arm Wellspring Echo: their next spell that costs Focus is free, but it stirs the Veil twice as much. Cantrips leave the echo armed. Aelora's Acknowledged followers craft a quarter faster, and a plain success has a one-in-four chance of a blessed bonus property, by voice or through the app. The world now has a season, starting in spring, and Thyra's Acknowledged followers feel it: extra healing in spring (Dawn's Embrace included), extra fire and lightning damage in summer, sharper Insight in autumn, and quieter Stealth in winter.

Release steps:
- After deploy, run `bun run migrate` from the deployed repository root against the production database. It applies 066_world_season, which seeds the world season as spring and is idempotent. This is an unpaid production write.
- Then run `bun run seed` there, so gods.json carries the three active gift rows. This is an unpaid production write.
