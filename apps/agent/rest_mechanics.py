"""Rest recovery — short and long rest resource restoration. Zero IO, zero async."""

from typing import Literal

RestType = Literal["short", "long"]


def apply_short_rest(
    current_stamina: int,
    max_stamina: int,
    current_focus: int,
    max_focus: int,
) -> tuple[int, int]:
    """Short rest (~1 hour): stamina fully restored, focus recovers to half pool minimum."""
    new_stamina = max_stamina
    new_focus = max(current_focus, max_focus // 2)
    return new_stamina, new_focus


def apply_long_rest(
    current_stamina: int,
    max_stamina: int,
    current_focus: int,
    max_focus: int,
    current_hp: int,
    max_hp: int,
) -> tuple[int, int, int]:
    """Long rest (~8 hours): all resource pools fully restored."""
    return max_stamina, max_focus, max_hp


def apply_rest(
    rest_type: RestType,
    current_stamina: int,
    max_stamina: int,
    current_focus: int,
    max_focus: int,
    current_hp: int,
    max_hp: int,
) -> tuple[int, int, int]:
    """Dispatcher: apply short or long rest, returning (stamina, focus, hp)."""
    if rest_type == "short":
        stamina, focus = apply_short_rest(current_stamina, max_stamina, current_focus, max_focus)
        return stamina, focus, current_hp
    elif rest_type == "long":
        return apply_long_rest(
            current_stamina,
            max_stamina,
            current_focus,
            max_focus,
            current_hp,
            max_hp,
        )
    else:
        msg = f"Unknown rest type: {rest_type!r}"
        raise ValueError(msg)
