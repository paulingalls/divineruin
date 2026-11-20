"""Player temporary HP and the shared damage calculation."""

from typing import TYPE_CHECKING, NamedTuple

import asyncpg

if TYPE_CHECKING:
    from combat_participant import CombatParticipant


def validate(value: object) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"temp_hp must be a nonnegative integer, got {value!r}")
    return value


def from_player(player: dict) -> int:
    return validate(player.get("temp_hp", 0))


def player_pool(participant: "CombatParticipant") -> int:
    return participant.temp_hp if participant.type == "player" else 0


class Damage(NamedTuple):
    hp: int
    temporary: int
    absorbed: int
    overkill: int

    def receipt(self, gift: dict) -> dict:
        facts = {**gift, "temp_hp_absorbed": self.absorbed, "temp_hp_remaining": self.temporary}
        if self.absorbed:
            cue = f"Temporary HP absorbed {self.absorbed} damage."
            facts["dm_cue"] = f"{gift.get('dm_cue', '')} {cue}".strip()
        return facts


def absorb(damage: int, hp: int, temporary: int, *, hp_floor: int = 0) -> Damage:
    absorbed = min(temporary, damage)
    remaining = hp - (damage - absorbed)
    return Damage(max(hp_floor, remaining), temporary - absorbed, absorbed, max(0, -remaining) if not hp_floor else 0)


async def grant(
    player_id: str,
    locked_player: dict,
    amount: int,
    *,
    participant: "CombatParticipant | None" = None,
    conn: asyncpg.Connection,
) -> tuple[int, int]:
    """Grant to a locked player row and its transaction's working participant."""
    from db_mutations import update_player_temp_hp

    if participant is not None and (participant.type != "player" or participant.id != player_id):
        raise ValueError("Temporary HP requires the matching player participant")
    before = from_player(locked_player)
    after = max(before, validate(amount))
    if after > before:
        await update_player_temp_hp(player_id, after, conn=conn)
        if participant is not None:
            participant.temp_hp = after
    return before, after
