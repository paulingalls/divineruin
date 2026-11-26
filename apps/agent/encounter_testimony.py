"""An authored witness and the encounter participants named in their testimony."""

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass
class Testimony:
    witness: str
    accused: list[str]

    @classmethod
    def from_dict(cls, row: object, label: str) -> "Testimony":
        if not isinstance(row, Mapping):
            raise ValueError(f"{label}: testimony must be an object")
        witness = row.get("witness")
        accused = row.get("accused")
        if not isinstance(witness, str) or not witness.strip():
            raise ValueError(f"{label}: witness must be a nonempty NPC id")
        if (
            not isinstance(accused, list)
            or not accused
            or any(not isinstance(enemy, str) or not enemy.strip() for enemy in accused)
        ):
            raise ValueError(f"{label}: accused must be a nonempty list of enemy ids")
        return cls(witness, list(accused))
