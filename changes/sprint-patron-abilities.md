Bump: minor

Patron tier abilities are in play. A follower at Acknowledged, Devoted or Exalted favor can now ask the DM to use the seven abilities the DM resolves by narration: Veythar's Lorekeeper's Library, Syrath's Whisper Network and Veilwatcher's Eye, Mortaen's Speak with Dead, Nythera's Charted Course, Valdris's Discern Lies and Zhael's Prophecy Fragment. Valdris's Layer 1 gift, Weight of Truth, works the same way. Each use is spent and comes back on its authored rest or, for once-per-session abilities, at the next session. Abilities lock when favor drops below their tier and come back, with the same spent state, when it climbs again. The other 23 tier abilities are listed as not yet in play.

Rule change: a long rest now also restores abilities and gifts that recharge on a short rest. This includes Veythar's Lorekeeper's Insight and Syrath's Shadow Veil, which before came back only on a short rest.

The character sheet lists the follower's patron abilities as ready, spent or locked, and the favor bar stays current. A player who joins someone else's session now gets their own sheet and favor bar right away, and a reconnect refreshes them. Session start data is sent only to its own player.

Under the hood, spell_casting.py is split into smaller modules with no behavior change.

Release steps:
- Apply migration 065_patron_revision.sql (adds players.patron_revision and its update trigger) with the normal migrate step before deploying the agent and server. Free; it writes the production schema.
