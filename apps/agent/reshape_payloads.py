"""The sections the Architect can reshape in a declaration."""

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, TypeAdapter


class Destination(BaseModel):
    model_config = {"extra": "forbid"}
    x: float = Field(strict=True, allow_inf_nan=False)
    y: float = Field(strict=True, allow_inf_nan=False)
    z: float = Field(strict=True, allow_inf_nan=False)


class WallEndpoints(BaseModel):
    model_config = {"extra": "forbid"}
    start: Destination
    end: Destination


class CreateWall(WallEndpoints):
    kind: Literal["create_wall"]


class MoveWall(WallEndpoints):
    kind: Literal["move_wall"]
    wall_id: str


class DestroyWall(BaseModel):
    model_config = {"extra": "forbid"}
    kind: Literal["destroy_wall"]
    wall_id: str


class Footprint(BaseModel):
    model_config = {"extra": "forbid"}
    min: Destination
    max: Destination


class OpenFloor(Footprint):
    kind: Literal["open_floor"]


class LowerCeiling(Footprint):
    kind: Literal["lower_ceiling"]


ReshapeSelection = Union[CreateWall, MoveWall, DestroyWall, OpenFloor, LowerCeiling]
_operations = TypeAdapter(list[Annotated[ReshapeSelection, Field(discriminator="kind")]])


def parse_operations(raw: object) -> list[dict]:
    if not isinstance(raw, list):
        raise ValueError("reshape requires a list of operations")
    return [operation.model_dump() for operation in _operations.validate_python(raw)]
