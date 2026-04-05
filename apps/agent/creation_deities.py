"""Deity definitions for character creation. Audio-first descriptions."""

from __future__ import annotations

from dataclasses import dataclass


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
