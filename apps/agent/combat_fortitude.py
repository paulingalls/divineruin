"""Unholy Fortitude resolves before destruction and its one-time death receipt."""

from check_resolution_save import roll_participant_save


def try_fortitude(target, outcome=None):
    spec = target.unholy_fortitude
    result = roll_participant_save(target, spec["save"], spec["dc"], "destruction", bonus_dice_eligible=False)
    if outcome is not None:
        outcome.update(dc=result.dc, roll=result.roll, total=result.total, success=result.success)
    if not result.success:
        return False
    target.hp_current = 1
    spec["dc"] += spec["increment"]
    if outcome is not None:
        outcome.update(next_dc=spec["dc"], narration_cue=spec["narration_cue"])
    return True
