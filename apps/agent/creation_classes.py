"""Class (archetype) definitions for character creation. Audio-first descriptions."""

from __future__ import annotations

from dataclasses import dataclass


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


# ---------------------------------------------------------------------------
# Starting equipment
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

# ---------------------------------------------------------------------------
# Classes (18)
# ---------------------------------------------------------------------------

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
