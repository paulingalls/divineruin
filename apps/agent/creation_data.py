"""Static data for character creation options.

Source of truth for all race, class, and deity data presented to the player
during the creation flow. Descriptions are audio-first — written for the ear.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RaceData:
    id: str
    name: str
    description: str  # Sensory description for DM narration (ear-first)
    card_description: str  # Short text for visual card (~20 words)
    attribute_bonuses: dict[str, int]


@dataclass(frozen=True)
class ClassData:
    id: str
    name: str
    category: str  # martial / arcane / primal / divine / shadow / support
    description: str  # Audio-first description for DM narration
    card_description: str
    hit_die: int  # e.g. 10 for d10
    primary_attribute: str
    saving_throw_proficiencies: tuple[str, ...]
    skill_options: tuple[str, ...]  # Pool to pick from
    num_skill_choices: int
    starting_equipment: dict  # {main_hand, armor, shield}
    starting_gold: int


@dataclass(frozen=True)
class DeityData:
    id: str
    name: str
    title: str  # e.g. "the Radiant Blade"
    domain: str
    description: str  # Audio-first personality sketch
    card_description: str
    synergy_classes: tuple[str, ...]


# ---------------------------------------------------------------------------
# Races (6)
# ---------------------------------------------------------------------------

RACES: dict[str, RaceData] = {
    "draethar": RaceData(
        id="draethar",
        name="Draethar",
        description=(
            "Warmth radiates from dense, powerful hands. Your skin runs hot — "
            "not like fever, but like a forge banked low. You're large, imposing, "
            "and when your pulse quickens the air around you shimmers."
        ),
        card_description="Large and powerful, with inner fire. Skin radiates heat in moments of exertion.",
        attribute_bonuses={"strength": 2, "constitution": 1},
    ),
    "elari": RaceData(
        id="elari",
        name="Elari",
        description=(
            "Long, fine fingers that tingle with awareness of something beyond the visible. "
            "You sense the fabric of reality the way others feel temperature — a low hum "
            "behind everything, the membrane between worlds. Since the Sundering, that hum "
            "has never been quiet."
        ),
        card_description="Tall and long-lived, with an innate sense of the Veil between worlds.",
        attribute_bonuses={"intelligence": 2, "wisdom": 1},
    ),
    "korath": RaceData(
        id="korath",
        name="Korath",
        description=(
            "Broad hands with a faint mineral sheen, solid as the stone beneath you. "
            "Your bones are dense, your patience deeper. You feel the earth's pulse — "
            "tremors before anyone else, the grain of stone, the song of metal still "
            "locked in ore."
        ),
        card_description="Broad and stone-touched. Dense bones, earth-sense, and the patience of mountains.",
        attribute_bonuses={"constitution": 2, "strength": 1},
    ),
    "vaelti": RaceData(
        id="vaelti",
        name="Vaelti",
        description=(
            "Quick, nimble hands. Every nerve alive to the air currents around you. "
            "Your senses are sharper than anyone in the room — you hear the creak of "
            "a floorboard three rooms away, catch movement at the edge of vision that "
            "others miss entirely."
        ),
        card_description="Slight and quick, with senses sharper than any other race. Impossible to surprise.",
        attribute_bonuses={"dexterity": 2, "wisdom": 1},
    ),
    "thessyn": RaceData(
        id="thessyn",
        name="Thessyn",
        description=(
            "Your hands feel adaptable, as though they could become anything given time. "
            "Your body slowly attunes to wherever you are — spend time by the sea and "
            "something aquatic stirs in you. Among scholars, your mind sharpens. "
            "You are living proof that environment shapes identity."
        ),
        card_description="Fluid and adaptable. Your body attunes to your environment over time.",
        # Thessyn: +1 to class primary attribute, +1 DEX, +1 CHA
        # Actual bonuses computed dynamically in creation_rules based on class
        attribute_bonuses={"dexterity": 1, "charisma": 1},
    ),
    "human": RaceData(
        id="human",
        name="Human",
        description=(
            "Steady, capable hands — unremarkable except for the determination behind them. "
            "No innate magic, no physical extremes. But an urgency others lack — shorter "
            "lives mean you push harder, learn faster, and refuse to accept limits."
        ),
        card_description="Adaptable and determined. No extremes, but thrives anywhere and learns anything.",
        attribute_bonuses={
            "strength": 1,
            "dexterity": 1,
            "constitution": 1,
            "intelligence": 1,
            "wisdom": 1,
            "charisma": 1,
        },
    ),
}

# ---------------------------------------------------------------------------
# Classes (18)
# ---------------------------------------------------------------------------

_LONGSWORD = {"name": "Longsword", "damage": "1d8", "damage_type": "slashing", "properties": []}
_SHORTSWORD = {"name": "Shortsword", "damage": "1d6", "damage_type": "piercing", "properties": ["finesse"]}
_DAGGER = {"name": "Dagger", "damage": "1d4", "damage_type": "piercing", "properties": ["finesse"]}
_MACE = {"name": "Mace", "damage": "1d6", "damage_type": "bludgeoning", "properties": []}
_QUARTERSTAFF = {"name": "Quarterstaff", "damage": "1d6", "damage_type": "bludgeoning", "properties": []}
_SHORTBOW = {"name": "Shortbow", "damage": "1d6", "damage_type": "piercing", "properties": [], "ranged": True}
_WARHAMMER = {"name": "Warhammer", "damage": "1d8", "damage_type": "bludgeoning", "properties": []}
_RAPIER = {"name": "Rapier", "damage": "1d8", "damage_type": "piercing", "properties": ["finesse"]}
_SPEAR = {"name": "Spear", "damage": "1d6", "damage_type": "piercing", "properties": []}
_HANDAXE = {"name": "Handaxe", "damage": "1d6", "damage_type": "slashing", "properties": []}
_LUTE = {"name": "Lute", "damage": "1d4", "damage_type": "bludgeoning", "properties": []}

_CHAIN_SHIRT = {"name": "Chain Shirt", "ac_bonus": 13}
_LEATHER = {"name": "Leather Armor", "ac_bonus": 11}
_HIDE = {"name": "Hide Armor", "ac_bonus": 12}
_ROBES = {"name": "Robes", "ac_bonus": 10}
_HALF_PLATE = {"name": "Half Plate", "ac_bonus": 15}
_SHIELD = {"name": "Wooden Shield", "ac_bonus": 1}

CLASSES: dict[str, ClassData] = {
    # --- Martial ---
    "warrior": ClassData(
        id="warrior",
        name="Warrior",
        category="martial",
        description=(
            "The front-line combatant. When steel meets steel, you're first in and last standing. "
            "Decisive, aggressive — you don't wait for the right moment, you make it."
        ),
        card_description="Front-line combatant. Decisive, aggressive, first to strike.",
        hit_die=10,
        primary_attribute="strength",
        saving_throw_proficiencies=("strength", "constitution"),
        skill_options=("athletics", "perception", "stealth", "survival", "acrobatics"),
        num_skill_choices=3,
        starting_equipment={"main_hand": _LONGSWORD, "armor": _CHAIN_SHIRT, "shield": _SHIELD},
        starting_gold=15,
    ),
    "guardian": ClassData(
        id="guardian",
        name="Guardian",
        category="martial",
        description=(
            "The protector. You read threats before they land and step between danger and "
            "those you shield. Reactive, patient — your strength is knowing when to brace."
        ),
        card_description="Protector of allies. Absorbs punishment, controls the battlefield.",
        hit_die=12,
        primary_attribute="constitution",
        saving_throw_proficiencies=("constitution", "wisdom"),
        skill_options=("athletics", "perception", "insight", "medicine", "religion"),
        num_skill_choices=2,
        starting_equipment={"main_hand": _LONGSWORD, "armor": _HALF_PLATE, "shield": _SHIELD},
        starting_gold=10,
    ),
    "skirmisher": ClassData(
        id="skirmisher",
        name="Skirmisher",
        category="martial",
        description=(
            "The mobile fighter. You wait for the opening, then strike like a whip crack — in, "
            "out, gone before the enemy turns. Speed and precision over brute force."
        ),
        card_description="Mobile fighter. Quick strikes, flanking, exploiting every opening.",
        hit_die=8,
        primary_attribute="dexterity",
        saving_throw_proficiencies=("dexterity", "strength"),
        skill_options=("acrobatics", "athletics", "stealth", "perception", "survival"),
        num_skill_choices=3,
        starting_equipment={"main_hand": _SHORTSWORD, "armor": _LEATHER, "shield": None},
        starting_gold=15,
    ),
    # --- Arcane ---
    "mage": ClassData(
        id="mage",
        name="Mage",
        category="arcane",
        description=(
            "You command the ambient arcane energy of the world. Casting is verbal — incantations "
            "shaped by intent, magic woven through words. The most voice-native class there is."
        ),
        card_description="Classic spellcaster. Commands arcane energy through spoken incantations.",
        hit_die=6,
        primary_attribute="intelligence",
        saving_throw_proficiencies=("intelligence", "wisdom"),
        skill_options=("arcana", "history", "investigation", "nature", "religion"),
        num_skill_choices=2,
        starting_equipment={"main_hand": _QUARTERSTAFF, "armor": _ROBES, "shield": None},
        starting_gold=10,
    ),
    "artificer": ClassData(
        id="artificer",
        name="Artificer",
        category="arcane",
        description=(
            "The maker of magical things. You craft enchanted items, deploy constructs, solve "
            "problems through invention. Between sessions, your workshop never sleeps."
        ),
        card_description="Magical inventor. Crafts enchanted items and deploys constructs.",
        hit_die=8,
        primary_attribute="intelligence",
        saving_throw_proficiencies=("intelligence", "constitution"),
        skill_options=("arcana", "history", "investigation", "perception", "sleight_of_hand"),
        num_skill_choices=2,
        starting_equipment={"main_hand": _WARHAMMER, "armor": _CHAIN_SHIRT, "shield": None},
        starting_gold=20,
    ),
    "seeker": ClassData(
        id="seeker",
        name="Seeker",
        category="arcane",
        description=(
            "The arcane investigator. You use magic to perceive, analyze, and uncover — the "
            "detective who finds what's hidden. Central to any mystery worth solving."
        ),
        card_description="Arcane investigator. Uses magic to perceive and uncover hidden truths.",
        hit_die=6,
        primary_attribute="intelligence",
        saving_throw_proficiencies=("intelligence", "wisdom"),
        skill_options=("arcana", "investigation", "perception", "insight", "history"),
        num_skill_choices=3,
        starting_equipment={"main_hand": _QUARTERSTAFF, "armor": _LEATHER, "shield": None},
        starting_gold=15,
    ),
    # --- Primal ---
    "druid": ClassData(
        id="druid",
        name="Druid",
        category="primal",
        description=(
            "You channel the power of the natural world. Shape terrain, command weather, speak to "
            "the ecosystem — and it answers. You don't cast spells. You have a conversation with "
            "the earth."
        ),
        card_description="Channels nature's power. Shapes terrain, commands weather, speaks to the wild.",
        hit_die=8,
        primary_attribute="wisdom",
        saving_throw_proficiencies=("wisdom", "intelligence"),
        skill_options=("nature", "survival", "animal_handling", "perception", "medicine", "religion"),
        num_skill_choices=2,
        starting_equipment={"main_hand": _QUARTERSTAFF, "armor": _HIDE, "shield": None},
        starting_gold=10,
    ),
    "beastcaller": ClassData(
        id="beastcaller",
        name="Beastcaller",
        category="primal",
        description=(
            "You bond with the creatures of this world. Your companion fights beside you, warns "
            "you, and adds a second voice to the party. The bond runs deeper than words."
        ),
        card_description="Bonds with creatures. Commands animal companions and draws on bestial instinct.",
        hit_die=8,
        primary_attribute="wisdom",
        saving_throw_proficiencies=("wisdom", "dexterity"),
        skill_options=("animal_handling", "nature", "survival", "perception", "stealth"),
        num_skill_choices=3,
        starting_equipment={"main_hand": _SHORTBOW, "armor": _HIDE, "shield": None},
        starting_gold=10,
    ),
    "warden": ClassData(
        id="warden",
        name="Warden",
        category="primal",
        description=(
            "Guardian of a place — a forest, a mountain, a stretch of coast. Your strength is "
            "tied to the land. In your territory, you are nearly unstoppable."
        ),
        card_description="Primal guardian bound to the land. Strongest in their home territory.",
        hit_die=10,
        primary_attribute="wisdom",
        saving_throw_proficiencies=("wisdom", "constitution"),
        skill_options=("nature", "survival", "perception", "athletics", "animal_handling"),
        num_skill_choices=2,
        starting_equipment={"main_hand": _SPEAR, "armor": _HIDE, "shield": _SHIELD},
        starting_gold=10,
    ),
    # --- Divine ---
    "cleric": ClassData(
        id="cleric",
        name="Cleric",
        category="divine",
        description=(
            "You channel power directly from your patron god. Your deity choice shapes everything — "
            "a Cleric of Orenthel heals, a Cleric of Kaelen inspires warriors, a Cleric of Syrath "
            "works in shadow."
        ),
        card_description="Divine channeler. Your patron god shapes your abilities entirely.",
        hit_die=8,
        primary_attribute="wisdom",
        saving_throw_proficiencies=("wisdom", "charisma"),
        skill_options=("religion", "insight", "medicine", "history", "persuasion"),
        num_skill_choices=2,
        starting_equipment={"main_hand": _MACE, "armor": _CHAIN_SHIRT, "shield": _SHIELD},
        starting_gold=15,
    ),
    "paladin": ClassData(
        id="paladin",
        name="Paladin",
        category="divine",
        description=(
            "The sworn champion. Martial prowess meets divine mandate. Your oath is spoken aloud "
            "and binds you — power for a price. Break the oath, and there are consequences."
        ),
        card_description="Sworn champion. Combines martial skill with a divine oath.",
        hit_die=10,
        primary_attribute="strength",
        saving_throw_proficiencies=("strength", "charisma"),
        skill_options=("athletics", "religion", "persuasion", "insight", "medicine"),
        num_skill_choices=2,
        starting_equipment={"main_hand": _LONGSWORD, "armor": _CHAIN_SHIRT, "shield": _SHIELD},
        starting_gold=15,
    ),
    "oracle": ClassData(
        id="oracle",
        name="Oracle",
        category="divine",
        description=(
            "Touched by fate itself. You receive visions, read patterns, speak prophecy. "
            "Unpredictable — your abilities shift probability and twist destiny. "
            "The DM channels plot through you."
        ),
        card_description="Fate-touched prophet. Receives visions and manipulates probability.",
        hit_die=6,
        primary_attribute="wisdom",
        saving_throw_proficiencies=("wisdom", "charisma"),
        skill_options=("religion", "insight", "perception", "history", "arcana"),
        num_skill_choices=2,
        starting_equipment={"main_hand": _QUARTERSTAFF, "armor": _ROBES, "shield": None},
        starting_gold=10,
    ),
    # --- Shadow ---
    "rogue": ClassData(
        id="rogue",
        name="Rogue",
        category="shadow",
        description=(
            "Stealth, locks, traps, precision strikes. You scout ahead, disable traps before "
            "anyone arrives, and strike from surprise. The quiet moments are yours."
        ),
        card_description="Skill specialist. Stealth, precision, and striking from the shadows.",
        hit_die=8,
        primary_attribute="dexterity",
        saving_throw_proficiencies=("dexterity", "intelligence"),
        skill_options=("stealth", "sleight_of_hand", "acrobatics", "perception", "investigation", "insight"),
        num_skill_choices=4,
        starting_equipment={"main_hand": _DAGGER, "armor": _LEATHER, "shield": None},
        starting_gold=20,
    ),
    "spy": ClassData(
        id="spy",
        name="Spy",
        category="shadow",
        description=(
            "The social infiltrator. Disguise, deception, intelligence gathering. In a voice game, "
            "you're remarkable — using your actual voice to deceive NPCs, talk past guards, and "
            "extract secrets through conversation."
        ),
        card_description="Social infiltrator. Deceives, disguises, and extracts secrets through talk.",
        hit_die=8,
        primary_attribute="charisma",
        saving_throw_proficiencies=("charisma", "dexterity"),
        skill_options=("persuasion", "insight", "stealth", "sleight_of_hand", "perception", "investigation"),
        num_skill_choices=4,
        starting_equipment={"main_hand": _RAPIER, "armor": _LEATHER, "shield": None},
        starting_gold=25,
    ),
    "whisper": ClassData(
        id="whisper",
        name="Whisper",
        category="shadow",
        description=(
            "Shadow-magic hybrid. Your spells are subtle, undetectable — not fireballs but "
            "influence, misdirection, planted suggestions, erased memories. Ethically complex "
            "and narratively rich."
        ),
        card_description="Shadow-magic hybrid. Subtle spells of influence and misdirection.",
        hit_die=6,
        primary_attribute="charisma",
        saving_throw_proficiencies=("charisma", "wisdom"),
        skill_options=("stealth", "arcana", "insight", "persuasion", "sleight_of_hand"),
        num_skill_choices=3,
        starting_equipment={"main_hand": _DAGGER, "armor": _ROBES, "shield": None},
        starting_gold=15,
    ),
    # --- Support ---
    "bard": ClassData(
        id="bard",
        name="Bard",
        category="support",
        description=(
            "The performer. In a voice game, you're the most natural class there is — you literally "
            "perform. Sing to inspire, tell stories to demoralize, play music to heal. "
            "Your voice is your weapon."
        ),
        card_description="Performer and storyteller. Inspires allies, demoralizes foes with voice.",
        hit_die=8,
        primary_attribute="charisma",
        saving_throw_proficiencies=("charisma", "dexterity"),
        skill_options=("persuasion", "perception", "insight", "acrobatics", "history", "arcana"),
        num_skill_choices=3,
        starting_equipment={"main_hand": _LUTE, "armor": _LEATHER, "shield": None},
        starting_gold=15,
    ),
    "diplomat": ClassData(
        id="diplomat",
        name="Diplomat",
        category="support",
        description=(
            "The negotiator. You solve encounters through conversation — talking enemies into "
            "surrendering, brokering alliances, defusing conflicts through pure roleplay. "
            "You may never swing a sword and still be the most valuable party member."
        ),
        card_description="Master negotiator. Solves encounters through persuasion and social leverage.",
        hit_die=6,
        primary_attribute="charisma",
        saving_throw_proficiencies=("charisma", "wisdom"),
        skill_options=("persuasion", "insight", "history", "perception", "religion", "investigation"),
        num_skill_choices=4,
        starting_equipment={"main_hand": _QUARTERSTAFF, "armor": _ROBES, "shield": None},
        starting_gold=25,
    ),
    "marshal": ClassData(
        id="marshal",
        name="Marshal",
        category="support",
        description=(
            "The battlefield leader. You don't fight alone — you command. Every ally near you "
            "fights better, moves smarter, and survives longer because you told them exactly "
            "what to do."
        ),
        card_description="Tactical commander. Leads allies in battle through voice and presence.",
        hit_die=10,
        primary_attribute="charisma",
        saving_throw_proficiencies=("charisma", "wisdom"),
        skill_options=("intimidation", "insight", "perception", "history"),
        num_skill_choices=4,
        starting_equipment={"main_hand": _LONGSWORD, "armor": _CHAIN_SHIRT, "shield": _SHIELD},
        starting_gold=15,
    ),
}

# ---------------------------------------------------------------------------
# Deities (10 + none)
# ---------------------------------------------------------------------------

DEITIES: dict[str, DeityData] = {
    "veythar": DeityData(
        id="veythar",
        name="Veythar",
        title="the Lorekeeper",
        domain="Knowledge, discovery, memory, the arcane arts",
        description=(
            "Contemplative and warm, though slightly distant. Values questions over answers. "
            "Has a genuine fondness for mortals — sees them as endlessly fascinating. "
            "Temples are libraries. Quests involve discovery and the recovery of lost knowledge."
        ),
        card_description="God of knowledge and the arcane. Temples are libraries.",
        synergy_classes=("mage", "artificer", "seeker"),
    ),
    "mortaen": DeityData(
        id="mortaen",
        name="Mortaen",
        title="the Threshold",
        domain="Death, the afterlife, transition",
        description=(
            "Calm, impartial, speaks in absolutes. Neither cruel nor kind — simply certain. "
            "Views death not as an ending but as a necessary transition. Speaks rarely, "
            "but with weight."
        ),
        card_description="God of death and transition. Calm certainty, rare words.",
        synergy_classes=("cleric", "druid", "warrior"),
    ),
    "thyra": DeityData(
        id="thyra",
        name="Thyra",
        title="the Wildmother",
        domain="Nature, seasons, growth, the physical world",
        description=(
            "Primal, emotional, fierce. Not a gentle forest goddess — she encompasses the "
            "hurricane and wildfire as much as the meadow. Speaks through storms and roots "
            "as much as words."
        ),
        card_description="Goddess of nature. Primal and fierce — wildfire and meadow alike.",
        synergy_classes=("druid", "beastcaller", "warden"),
    ),
    "kaelen": DeityData(
        id="kaelen",
        name="Kaelen",
        title="the Ironhand",
        domain="War, conflict, valor, martial discipline",
        description=(
            "Blunt, honorable, direct. Does not enjoy destruction — views war as a necessary tool "
            "wielded with discipline. Respects courage in all forms. Despises cruelty and "
            "senseless violence."
        ),
        card_description="God of war and valor. Blunt, honorable, disciplined.",
        synergy_classes=("warrior", "guardian", "skirmisher", "paladin"),
    ),
    "syrath": DeityData(
        id="syrath",
        name="Syrath",
        title="the Veilwatcher",
        domain="Shadows, secrets, espionage, hidden knowledge",
        description=(
            "Quiet, amused, sees everything. Operates in the margins. Believes secrets are "
            "power and hidden knowledge protects as much as it harms. Speaks softly, often "
            "in double meanings."
        ),
        card_description="God of shadows and secrets. Quiet, amused, sees everything.",
        synergy_classes=("rogue", "spy", "whisper"),
    ),
    "aelora": DeityData(
        id="aelora",
        name="Aelora",
        title="the Hearthkeeper",
        domain="Civilization, commerce, crafting, community",
        description=(
            "Warm, practical, deeply invested in mortal flourishing. Not a soft god — understands "
            "civilization requires hard work and sometimes ruthless pragmatism. Speaks plainly "
            "and kindly."
        ),
        card_description="Goddess of civilization and craft. Warm, practical, community-driven.",
        synergy_classes=("artificer", "bard", "diplomat"),
    ),
    "valdris": DeityData(
        id="valdris",
        name="Valdris",
        title="the Scalebearer",
        domain="Justice, law, order, truth, accountability",
        description=(
            "Stern, incorruptible, deeply principled. Not rigid — understands justice requires "
            "wisdom and context. But absolutely unwavering when principle is at stake. "
            "The moral backbone of the pantheon."
        ),
        card_description="God of justice and truth. Stern, principled, incorruptible.",
        synergy_classes=("paladin", "guardian", "cleric"),
    ),
    "nythera": DeityData(
        id="nythera",
        name="Nythera",
        title="the Tidecaller",
        domain="Sea, travel, exploration, boundaries, the unknown",
        description=(
            "Adventurous, restless, drawn to the edges of things. The most free-spirited god — "
            "always looking outward. Speaks with the cadence of waves — sometimes calm, "
            "sometimes urgent."
        ),
        card_description="Goddess of exploration and the unknown. Restless, adventurous.",
        synergy_classes=("beastcaller", "seeker", "skirmisher"),
    ),
    "orenthel": DeityData(
        id="orenthel",
        name="Orenthel",
        title="the Dawnbringer",
        domain="Light, healing, renewal, hope",
        description=(
            "Compassionate, tireless, sometimes naive. Genuinely believes the world can be saved. "
            "Can be frustratingly optimistic — but that optimism is real strength. Speaks with "
            "warmth and conviction."
        ),
        card_description="God of healing and hope. Compassionate, tireless, radiant.",
        synergy_classes=("cleric", "paladin", "druid"),
    ),
    "zhael": DeityData(
        id="zhael",
        name="Zhael",
        title="the Fatespinner",
        domain="Fate, time, prophecy, luck, the pattern of things",
        description=(
            "Enigmatic, unpredictable, speaks in riddles. The most alien god — even other deities "
            "find Zhael unsettling. Exists slightly out of step with everyone, seeing the "
            "conversation from a different angle."
        ),
        card_description="God of fate and prophecy. Enigmatic, riddling, unsettling.",
        synergy_classes=("oracle", "whisper", "seeker"),
    ),
    "none": DeityData(
        id="none",
        name="No Patron",
        title="the Unsworn",
        domain="Independence",
        description=(
            "You walk without a god's hand on your shoulder. Some call it foolish in times like "
            "these. Others call it honest. The gods have their own agendas — you'd rather "
            "keep yours clear."
        ),
        card_description="No divine patron. Walk your own path, free of divine obligation.",
        synergy_classes=(),
    ),
}
