"""Authored context clauses the registered synergy scenarios exercise: tag, id, name, effect, skill."""

Clause = tuple[str, str, str, str, str | None]

NPC = "guildmaster_torin"
MERCHANT = "aelora_guildmaster_dara"
SHARED = (
    "shared_meal",
    "aelora_shared_table",
    "Shared Table",
    "Gain +1 Religion when blessing a shared meal.",
    "religion",
)
CIVIC = (
    "community_duties",
    "aelora_civic_promise",
    "Civic Promise",
    "Gain +1 Persuasion when negotiating a community’s shared duties.",
    "persuasion",
)
HEARTH = (
    "household_omen",
    "aelora_hearth_omen",
    "Hearth Omen",
    "Gain +1 Insight when interpreting a household omen.",
    "insight",
)
COMMERCE = ("commerce", "aelora_commerce_persuasion", "Honest Hustle", "Commerce Persuasion +1.", "persuasion")
GROVE = (
    "sacred_grove",
    "thyra_wild_covenant",
    "Wild Covenant",
    "Gain +1 Religion when honoring a sacred grove.",
    "religion",
)
SEASONAL = (
    "seasonal_omen",
    "thyra_seasonal_omen",
    "Seasonal Omen",
    "Gain +1 Nature when interpreting a seasonal omen.",
    "nature",
)
SHORELINE = (
    "coast_shelter",
    "nythera_shoreline_keeper",
    "Shoreline Keeper",
    "Gain +1 Survival when finding safe shelter along an unfamiliar coast.",
    "survival",
)
HARBOR = (
    "port_passage",
    "nythera_harbor_courtesy",
    "Harbor Courtesy",
    "Gain +1 Persuasion when seeking peaceful passage through an unfamiliar port.",
    "persuasion",
)
VOYAGER = (
    "vessel_repair",
    "nythera_voyagers_tools",
    "Voyager's Tools",
    "Gain +1 to checks to repair a vessel during a journey.",
    None,
)
MENDER = (
    "sanctuary_repair",
    "orenthel_menders_dawn",
    "Mender's Dawn",
    "Gain +1 to checks to repair equipment for a damaged sanctuary.",
    None,
)
GREEN_MORNING = (
    "blighted_grove",
    "orenthel_green_morning",
    "Green Morning",
    "Gain +1 Nature when restoring a blighted grove.",
    "nature",
)
RECONCILIATION = (
    "wounded_enemy_care",
    "orenthel_reconciliation",
    "Reconciliation",
    "Gain +1 Persuasion when negotiating care for wounded enemies.",
    "persuasion",
)
OATHBREAK = (
    "broken_oath_evidence",
    "valdris_oathbreak_sight",
    "Ordered Testimony",
    "Gain +1 Arcana when examining magical evidence of a broken oath.",
    "arcana",
)
MEASURE = (
    "tampered_measures",
    "valdris_true_measure",
    "Honest Measure",
    "Gain +1 Investigation when examining tampered scales or measuring tools.",
    "investigation",
)
CUSTODY = (
    "evidence_ownership_hearing",
    "valdris_chain_of_custody",
    "Chain of Evidence",
    "Gain +1 Investigation when tracing ownership of evidence in a public hearing.",
    "investigation",
)
BOUNDARY = (
    "unlawful_incursion",
    "valdris_boundary_law",
    "Common Ground",
    "Gain +1 Survival when tracing an unlawful incursion into protected land.",
    "survival",
)
SCALES = (
    "equal_terms_petition",
    "valdris_even_scales",
    "Fair Terms",
    "Gain +1 Persuasion when securing equal terms for opposing petitioners.",
    "persuasion",
)
DECEIT = (
    "just_cause_deception",
    "valdris_just_deceit",
    "Truth in Disguise",
    "Deception for just causes (evidence, infiltration) gains +1. Valdris blesses deception in service of truth",
    "deception",
)

WITNESSED_OATH = (
    "ancient_oath",
    "veythar_witnessed_oath",
    "Witnessed Oath",
    "Gain +1 Religion when interpreting an ancient oath.",
    "religion",
)
REMEMBERED_VISION = (
    "remembered_vision",
    "veythar_remembered_vision",
    "Remembered Vision",
    "Gain +1 Arcana when interpreting a remembered vision.",
    "arcana",
)
LAST_SALUTE = (
    "fallen_soldier_rites",
    "kaelen_last_salute",
    "Last Salute",
    "Gain +1 Religion when conducting a fallen soldier’s funeral rites.",
    "religion",
)
BATTLE_OMEN = (
    "martial_omen",
    "kaelen_battle_omen",
    "Battle Omen",
    "Gain +1 History when interpreting a martial omen.",
    "history",
)
SECRET_DEVOTION = (
    "concealed_symbol",
    "syrath_secret_devotion",
    "Secret Devotion",
    "Gain +1 Religion when interpreting a concealed devotional symbol.",
    "religion",
)
UNSPOKEN_VOW = (
    "erased_oath",
    "syrath_unspoken_vow",
    "Unspoken Vow",
    "Gain +1 History when identifying an oath whose patron’s name was erased.",
    "history",
)
PEACE_AT_PARTING = (
    "burial_return",
    "mortaen_peace_at_parting",
    "Peace at Parting",
    "Gain +1 Persuasion when negotiating the return of a body for burial.",
    "persuasion",
)
PATIENT_GEAR = (
    "clock_repair",
    "zhael_patient_gear",
    "Patient Gear",
    "Gain +1 to checks to repair a clock or timing mechanism.",
    None,
)
CONVERGING_CLUES = (
    "foretold_accounts",
    "zhael_converging_clues",
    "Converging Clues",
    "Gain +1 Investigation when comparing two accounts of the same foretold event.",
    "investigation",
)
