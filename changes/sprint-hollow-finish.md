Bump: minor

The Hollowing now gets worse if it goes untreated, and it can be cured:
- An untreated Hollowed character worsens from Stage 1 to Stage 2 at a long rest. At Stage 2 the DM starts describing sounds and sights only that character notices. Each one is woven in once, at a quiet moment.
- At Stage 3, every untreated long rest drains a point of Wisdom, never below 1. Focus and Stamina limits follow the new Wisdom.
- Greater Restoration lifts the Hollowing at any stage and gives back the Wisdom it took, up to 20. Death clears it the same way. With no Hollowing on the target, it removes Charmed or Petrified instead, including the Still's charm.

Magic weapons now count against the Hollowed Knight. An equipped magical weapon gets past its resistance to nonmagical damage on basic attacks, martial techniques and opportunity strikes, even after a reload.

The artificer's Infuse Item makes its equipped plain weapon magical, with +1 to attack and damage, until the next long rest. At level 10 the bonus is +2 and Arcane Armory keeps up to three weapons infused, so a fourth replaces the oldest.

The Choir now waits in its own corner of the deep Ashmark, where a party of the right level can find it, and fights there to the end with its whole kit. Silence stops its abilities for exactly one of its turns.

The Architect now has 205 HP, up from 175 (the spec is 300). The reference party takes its strongest electives, and at 205 HP it beats the Architect 12 times in 20.

Release steps: `bun run migrate` then `bun run seed`, after deploy, on the target stack, not paid. Migration 068 adds the Hollowed hallucinations catalog, and content/hollowed_hallucinations.json, creatures.json, archetype_abilities.json, encounter_templates.json, locations.json and scenes.json changed.
