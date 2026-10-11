# Changelog

## 0.29.0 — 2026-10-11

- Every location carries a physical terrain from one closed ten-value list (Decisions 129–132), mirrored in Python and TypeScript. Seeding and server startup refuse a missing or unknown terrain, or one that does not fit the location's region type. The travel-difficulty field formerly named `terrain` is now `navigation`.
- Primal magic draws on the land: a cast generates its catalog Resonance scaled by the terrain's base (healthy wilds are the baseline), so ancient forest is gentler than a city. Per-spell terrain overrides and the stale "normal" default are gone.
- Korath's earth-anchored −1 primal Resonance applies only on earth or stone, not coast or wetland. The Druid's Veil Ward is refused off natural terrain and costs 3 Focus instead of 5 in ancient forest.
- Combat resolves its terrain once at the start and keeps it with the fight; casts and wards mid-combat never look the location up again. A combat at a location without terrain refuses to start.
- Four new wilderness locations give every terrain a real place: the Old-Growth Grove (Thornveld), Keldaran Southern Pass, the Tidal Shore and the Reed Marsh (Sunward Coast). `world_data_simulation.md` gains an "Authoring a Location" guide.
- Free test lanes can no longer bill a paid provider: an unapproved request to Anthropic, OpenAI, Deepgram or Inworld is refused and fails the test, even when the calling code swallows the error.
- The agent dev-command boot check allows a loaded four-core machine time to start.

## 0.28.0 — 2026-10-08

- Mawlings declare their authored Claw then Dissolution Maw multiattack as one declaration with per-strike targets. Each strike keeps its own held reaction window across pauses and reloads; an unavailable strike drains unresolved, with no retargeting. Minion Mawlings keep a single attack.
- Dissolution Maw applies its CON DC 13 held-item durability rider to a DM-selected, equipped player item, chosen from target-scoped inventory facts that include guests. Role DC modifiers apply, and companions are excluded. Both validators reject riders on save- or condition-resolved attacks.
- A living ally grappled by a living, able Mawling takes 1d6 necrotic Dissolution Field damage at its turn start, even when stunned, Fallen or omitted from declarations. Damage to a Fallen character now adds one automatic death-save failure.
- Reaction spends checkpoint in the same transaction as their resource debit, so a reload cannot re-spend them. The checkpoint save refuses to run without the combat-state lock.
- Split XP roles across model families: codex plans and executes, and Claude reviews plans and diffs.

## 0.27.0 — 2026-10-04

- Adopt the v1 development constraints: test production behavior once at the outermost useful boundary, retire duplicate unit coverage, and remove documentation wording checks and test meta-checks.
- Keep pushes service-free with local lint and Bun tests. Run the full suite at sprint close; free patches use focused acceptance and normal PR CI.
- Reduce tracked test lines from 177,625 to 160,505 and the test/source ratio from 2.2106× to 1.9991×. Preserve unique behavior checks while removing redundant tests, setup, and commentary.
- Make the live material-inventory acceptance check independent of Bun's compact diagnostic output.
