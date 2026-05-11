"""Race definitions for character creation. Audio-first descriptions."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RaceData:
    id: str
    name: str
    description: str  # Sensory description for DM narration (ear-first)
    card_description: str  # Short text for visual card (~20 words)
    attribute_bonuses: dict[str, int]


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
