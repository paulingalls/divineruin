"""Catalog and player-data contract for sworn oaths."""

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Objective = Literal["defeat_target", "keep_ally_standing"]
ObjectiveInput = Literal["none", "defeat_target", "keep_ally_standing"]
OathStatus = Literal["active", "fulfilled", "broken", "lapsed"]
Id = Annotated[str, StringConstraints(min_length=1)]
Round = Annotated[int, Field(gt=0)]

JUSTICE_NAME = "Oath of Justice"
TIMED_NAME = "Promised Hour"

JUSTICE_TERMS = {
    "strike_first": "Do not strike first against a foe.",
    "strike_surrendered_enemy": "Do not strike an enemy who surrendered.",
    "strike_yielded_ally": "Do not strike an ally who yielded.",
}
TIMED_TERMS: dict[Objective, str] = {
    "defeat_target": "Defeat the named foe by the end of the promised round.",
    "keep_ally_standing": "Keep the named ally standing through the end of the promised round.",
}


class Oath(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    id: Id
    owner_id: Id
    choice_id: Id
    status: OathStatus
    latest_state_change_event_id: Id
    terms: list[str]
    bound_entity_ids: list[Id]


class JusticeOath(Oath):
    kind: Literal["justice"]
    patron: Literal["valdris"]

    @model_validator(mode="after")
    def validate_terms(self) -> Self:
        if self.terms != list(JUSTICE_TERMS) or self.bound_entity_ids:
            raise ValueError("Invalid Oath of Justice terms or bindings")
        return self


class TimedOath(Oath):
    kind: Literal["timed"]
    patron: Literal["zhael"]
    combat_id: Id
    round_number: Round
    last_round: Round
    objective_kind: Objective
    target_id: Id

    @model_validator(mode="after")
    def validate_terms(self) -> Self:
        if not deadline_is_current(self.last_round, self.round_number) or self.terms != [self.objective_kind]:
            raise ValueError("Invalid timed oath terms or round window")
        if self.bound_entity_ids != [self.target_id]:
            raise ValueError("Invalid timed oath target binding")
        return self


OathRecord = Annotated[JusticeOath | TimedOath, Field(discriminator="kind")]


class OathBook(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    records: list[OathRecord]

    @classmethod
    def from_player(cls, player: dict, owner_id: str) -> Self:
        book = cls.model_validate(player["oaths"]) if "oaths" in player else cls(records=[])
        choices = {record.choice_id for record in book.records}
        if len(choices) != len(book.records) or any(record.owner_id != owner_id for record in book.records):
            raise ValueError("Invalid oath record ownership or duplicate choice")
        return book


def deadline_is_current(last_round: int, current_round: int) -> bool:
    return last_round >= current_round


def receipt(record: OathRecord) -> dict:
    descriptions = (
        list(JUSTICE_TERMS.values()) if isinstance(record, JusticeOath) else [TIMED_TERMS[record.objective_kind]]
    )
    name = JUSTICE_NAME if isinstance(record, JusticeOath) else TIMED_NAME
    return {**record.model_dump(), "oath_id": record.id, "name": name, "term_descriptions": descriptions}
