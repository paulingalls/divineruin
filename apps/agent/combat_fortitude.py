"""Unholy Fortitude resolves before destruction and its one-time death receipt."""

from check_resolution_save import roll_participant_save


def roll_fortitude(target):
    spec = target.unholy_fortitude
    return roll_participant_save(target, spec["save"], spec["dc"], "destruction", bonus_dice_eligible=False)


def try_fortitude(target, outcome=None, result=None):
    """Resolve the save (``result`` when a Zhael hold already settled it) and stand the target at 1 HP."""
    spec = target.unholy_fortitude
    if result is None:
        result = roll_fortitude(target)
    if outcome is not None:
        outcome.update(dc=result.dc, roll=result.roll, total=result.total, success=result.success)
    if not result.success:
        return False
    target.hp_current = 1
    spec["dc"] += spec["increment"]
    if outcome is not None:
        outcome.update(next_dc=spec["dc"], narration_cue=spec["narration_cue"])
    return True
