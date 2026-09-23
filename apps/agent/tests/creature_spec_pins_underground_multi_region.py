"""Stat, harvest, and behavior pins for underground and multi-region creatures.

Source: docs/game_mechanics/game_mechanics_bestiary.md:974-1144.
"""

SPEC = {
    "umbral_crawler": (
        "beast",
        2,
        4,
        32,
        14,
        30,
        100,
        (14, 16, 12, 3, 12, 2),
        ("DEX",),
        (
            ("Claw", "melee", 5, 5, "1d6+3", "slashing", None),
            (
                "Mandible",
                "melee",
                5,
                5,
                "1d8+3",
                "piercing",
                "Only on grappled targets. Injects paralytic: DC 13 CON save or Paralyzed 1 minute",
            ),
        ),
        "underground",
        ("underground", "keldaran_mountains"),
    ),
    "deepstone_guardian": (
        "construct",
        2,
        5,
        45,
        16,
        20,
        150,
        (18, 8, 16, 6, 10, 4),
        ("STR", "CON"),
        (
            ("Stone Fist", "melee", 5, 7, "1d10+4", "bludgeoning", None),
            (
                "Guardian Pulse",
                "area",
                15,
                0,
                "1d8",
                "force",
                "CON save DC 14. Pushes all creatures 10 ft. Recharge 5-6",
            ),
        ),
        "underground",
        ("underground", "keldaran_mountains"),
    ),
    "dire_bear": (
        "beast",
        2,
        6,
        60,
        14,
        40,
        200,
        (20, 10, 18, 3, 12, 6),
        ("STR", "CON"),
        (
            ("Claw", "melee", 10, 8, "1d8+5", "slashing", "Reach 10 ft"),
            (
                "Bite",
                "melee",
                5,
                8,
                "2d6+5",
                "piercing",
                "On hit: target grappled (escape DC 16). Can only bite grappled targets on subsequent rounds",
            ),
            ("Maul", "melee", 5, 0, "2d8+5", "piercing", "Auto-hit only against grappled targets. The full-body crush"),
        ),
        "multi_region",
        ("thornveld", "keldaran_mountains", "greyvale"),
    ),
    "troll": (
        "humanoid",
        2,
        6,
        65,
        13,
        30,
        200,
        (18, 12, 20, 6, 8, 6),
        ("CON",),
        (("Claw", "melee", 5, 7, "1d6+4", "slashing", None), ("Bite", "melee", 5, 7, "1d8+4", "piercing", None)),
        "multi_region",
        ("thornveld", "keldaran_mountains", "sunward_coast"),
    ),
    "bandit_captain": (
        "humanoid",
        2,
        5,
        45,
        15,
        30,
        150,
        (14, 16, 14, 12, 12, 14),
        ("DEX", "CHA"),
        (
            ("Longsword", "melee", 5, 6, "1d8+3", "slashing", None),
            ("Heavy Crossbow", "ranged", 100, 6, "1d10+3", "piercing", None),
        ),
        "multi_region",
        ("greyvale", "thornveld"),
    ),
    "thunderbird": (
        "beast",
        3,
        9,
        90,
        15,
        20,
        500,
        (18, 16, 16, 6, 14, 10),
        ("DEX", "CON"),
        (
            ("Beak", "melee", 5, 7, "2d6+4", "piercing", None),
            (
                "Talons",
                "melee",
                5,
                7,
                "1d8+4",
                "slashing",
                "Target grappled (escape DC 15). Thunderbird can fly while grappling — carries target",
            ),
            (
                "Lightning Breath",
                "area",
                60,
                0,
                "4d8",
                "lightning",
                "DEX save DC 15. Half on success. Recharge 5-6. The signature attack",
            ),
        ),
        "multi_region",
        ("keldaran_mountains", "drathian_steppe"),
    ),
}

LOOT = {
    "umbral_crawler": (
        ("crawler_chitin", "1d4", 1.0, ()),
        ("paralytic_gland", 1, 0.5, (("survival", "expert"),)),
        ("crawler_mandible", 2, 0.75, ()),
    ),
    "deepstone_guardian": (
        ("guardian_core_small", 1, 1.0, (("crafting", "trained"),)),
        ("enchanted_stone", "1d4", 1.0, ()),
        ("ancient_mechanism", 1, 0.25, (("crafting", "expert"),)),
    ),
    "dire_bear": (
        ("dire_bear_hide", 1, 1.0, (("survival", "trained"),)),
        ("dire_bear_claws", 4, 1.0, ()),
        ("dire_bear_heart", 1, 0.75, (("survival", "expert"),)),
        ("dire_bear_fat", 2, 1.0, (("survival", "trained"),)),
    ),
    "troll": (
        ("troll_blood", "1d4", 1.0, (("survival", "expert"),)),
        ("troll_hide", 1, 0.75, (("survival", "trained"),)),
        ("troll_bone", "1d4", 1.0, ()),
    ),
    "bandit_captain": (
        ("chain_shirt", 1, 1.0, ()),
        ("quality_longsword", 1, 1.0, ()),
        ("treasure_map_intel", 1, 0.25, ()),
    ),
    "thunderbird": (
        ("thunderbird_feather", "2d6", 1.0, ()),
        ("lightning_gland_large", 1, 0.75, (("survival", "expert"),)),
        ("thunderbird_egg", 1, 0.1, ()),
        ("storm_crystal", 1, 0.25, (("arcana", "trained"),)),
    ),
}

MULTIATTACK = {
    "umbral_crawler": "2 Claw attacks",
    "deepstone_guardian": None,
    "dire_bear": "2 attacks — one Claw and one Bite",
    "troll": "3 attacks — one Bite and two Claw",
    "bandit_captain": "2 attacks with Longsword or 2 Crossbow shots",
    "thunderbird": "2 attacks — one Beak and one Talons",
}

BEHAVIOR = {
    "umbral_crawler": (
        "Hunts in packs in deep tunnels. Drops from ceilings. Targets weakest-looking creature. Uses paralytic on downed prey.",
        "Flees if 50% of pack killed.",
        "Pack of 3-5",
        ("Umbral Deep", "Keldaran deep mines", "underground ruins"),
        ("Blindsight", "Sunlight Sensitivity", "Pack Ambush"),
        (),
    ),
    "deepstone_guardian": (
        "Guards ancient underground structures. Activates when intruders enter its zone. Will not pursue beyond its assigned area.",
        "Fights to destruction within its zone.",
        "Solitary or pair (flanking a doorway)",
        ("Umbral Deep ruins", "Keldaran ancient holds", "pre-Sundering structures"),
        ("Damage Immunity", "Resistance", "Sentry Protocol", "Tremorsense"),
        ("Lockdown",),
    ),
    "dire_bear": (
        "Extremely territorial. Charges largest threat. Grapples and mauls. A dire bear in its rage state is one of the most dangerous natural encounters in the game.",
        "Fights to death defending territory. Outside territory: retreats below 50% HP unless cubs nearby.",
        "Solitary or mother with 1-2 cubs (cubs are non-combatants)",
        ("Thornveld", "Keldaran mountain forests", "northern Greyvale"),
        ("Keen Smell", "Thick Hide", "Territorial Rage"),
        (),
    ),
    "troll": (
        "Aggressive but dim. Charges in, attacks whatever is closest. Does not use tactics. Will switch targets if current target deals fire damage.",
        "Fights while regenerating. Flees if on fire.",
        "Solitary or pair",
        ("Thornveld", "mountain passes", "marshes", "ruins"),
        ("Regeneration", "Keen Smell", "Loathsome Limbs"),
        (),
    ),
    "bandit_captain": (
        "Stays behind bodyguards. Uses crossbow at range, switches to sword when pressed. Commands bandits tactically — has them flank, focus fire, and retreat when losing.",
        "Flees when last bodyguard falls. Surrenders if cornered and outmatched — will offer information or treasure for life.",
        "With 3-6 bandits",
        ("Roads", "forest camps", "ruins used as hideouts"),
        ("Leadership Aura", "Cunning Action"),
        ("Rally", "Dirty Fighting"),
    ),
    "thunderbird": (
        "Apex predator of mountain and steppe skies. Dives from extreme altitude, uses Lightning Breath on groups, picks up isolated targets with talons. Intelligent enough to avoid large armed groups.",
        "Retreats to altitude if badly wounded. Returns when healed. Does not fight to the death unless defending nest.",
        "Solitary or mated pair",
        ("Keldaran mountain peaks", "Drathian Steppe (during storms)", "high altitude everywhere"),
        ("Flyby", "Lightning Absorption", "Storm Sense"),
        (),
    ),
}

ABILITIES = {
    "umbral_crawler": (
        (
            "Blindsight 60 ft; hunts by vibration and scent. Climbs 30 ft.",
            "Disadvantage in daylight.",
            "First attack from hidden has advantage and deals +1d6 damage.",
        ),
        (),
    ),
    "deepstone_guardian": (
        (
            "Immune to poison and psychic damage.",
            "Resists non-magical physical damage.",
            "Cannot be surprised.",
            "Detects creatures within 30 ft even through walls.",
        ),
        (("All doors and passages within 60 ft seal for 1 minute; STR DC 16 to force open.", "1/encounter"),),
    ),
    "dire_bear": (
        (
            "Advantage on Perception by smell.",
            "Resists cold damage.",
            "Below 25% HP: advantage on all attacks and +2 damage.",
        ),
        (),
    ),
    "troll": (
        (
            "Regains 5 HP at start of each turn; stops for 1 round after fire or acid damage.",
            "Keen smell.",
            "Severed limbs act independently for 1 round; flavor only.",
        ),
        (),
    ),
    "bandit_captain": (
        ("Bandits within 30 ft gain +1 to attack rolls.", "Can Dash, Disengage, or Hide as a bonus action."),
        (
            ("All allied bandits within 30 ft regain 1d8 HP.", "1/encounter"),
            ("Advantage on next attack; on hit, target Blinded 1 round.", "1/encounter"),
        ),
    ),
    "thunderbird": (
        (
            "No opportunity attacks when flying away. Flies 80 ft.",
            "Immune to lightning; heals equal to lightning damage dealt to it.",
            "Senses storms 6 hours ahead; fights more commonly during storms.",
        ),
        (),
    ),
}
