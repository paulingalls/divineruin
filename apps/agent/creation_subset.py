"""The first-share roster and the choices needed to enter play."""

from session_data import CreationState

ALLOWED_IDS = {
    "race": ("human", "elari", "vaelti"),
    "class": ("warrior", "mage", "rogue", "cleric"),
    "deity": ("veythar", "kaelen", "aelora", "syrath"),
}
DEFAULT_RACE = "human"
DEFAULT_PATRONS = {"warrior": "kaelen", "mage": "veythar", "rogue": "syrath", "cleric": "aelora"}


def remaining_choices(state: CreationState) -> list[str]:
    return [name for name, value in (("class", state.class_choice), ("name", state.name)) if not value]
