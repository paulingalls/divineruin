"""Turn Undead/Hollow exclusions, expiry and creature spell defenses."""

from unittest.mock import patch

import pytest
from acceptance._capstone_helpers import _d20
from acceptance.test_still_anchors import mock_combat_agent_factory as mock_combat_agent_factory
from acceptance.test_turn_undead_hollow import frightened
from acceptance.turn_undead_harness import TurnFight
from acceptance.turn_undead_harness import fight as fight

import check_resolution_save
from conditions import apply_condition


async def test_save_radius_category_immunity_and_threshold(fight: TurnFight) -> None:
    await fight.enter(
        {
            "saved": ("undead", 4),
            "distant": ("undead", 31),
            "bandit": ("bandit", 6),
            "immune": ("undead", 8),
            "threshold": ("undead", 10),
            "echo": ("undead", 12),
        },
        level=5,
    )
    fight.actor("saved").hp_current = 24
    for name in ("immune", "threshold"):
        fight.actor(name).hp_current = 25
    echo = fight.actor("echo")
    echo.type = "temporary_hollowed"
    echo.hp_current = 1
    for name in ("immune", "echo"):
        target = fight.actor(name)
        target.conditions = apply_condition([], "temporary_hollowed")
    state = await fight.persist()
    before = {p.id: (p.hp_current, p.conditions) for p in state.participants}
    roll_save = check_resolution_save.roll_participant_save

    def scripted_save(target, attribute, dc, effect, **kwargs):
        with patch("check_resolution.dice_roll", return_value=_d20(18 if target.id == "saved" else 2)):
            return roll_save(target, attribute, dc, effect, **kwargs)

    with patch("check_resolution_save.roll_participant_save", side_effect=scripted_save):
        packets = await fight.phase(cast=True)
    outcomes = {p["target_id"]: p for p in fight.cast(packets)["turn_undead"]}
    for actor_id, reason in {
        "saved": "save",
        "distant": "30 feet",
        "bandit": "category",
        "immune": "immune",
        "echo": "category",
    }.items():
        row = outcomes[actor_id]
        assert row["outcome"] == "unaffected" and reason in row["reason"].lower()
        assert ("save" in row) is (actor_id in ("saved", "immune"))
        target = fight.actor(actor_id)
        assert (target.hp_current, target.conditions) == before[actor_id]
    assert outcomes["saved"]["save"]["success"]
    assert outcomes["threshold"]["outcome"] == "frightened"
    assert frightened(fight, "threshold") is not None
    assert fight.actor("threshold").hp_current == 25


async def test_ordinary_fear_and_turn_expiry(fight: TurnFight) -> None:
    await fight.enter({"turned": ("undead", 4), "ordinary": ("bandit", -4)})
    target = fight.actor("turned")
    target.hp_current = 19
    ordinary = fight.actor("ordinary")
    ordinary.conditions = apply_condition([], "frightened", source=fight.caster, duration=10)
    await fight.persist()
    with patch("check_resolution.dice_roll", return_value=_d20(2)):
        packets = await fight.phase(fight.attack("ordinary"), cast=True)
        assert (
            next(p for p in fight.cast(packets)["turn_undead"] if p["target_id"] == "turned")["outcome"] == "frightened"
        )
        assert any(p["actor_id"] == "ordinary" and "hit" in p and not p.get("fled") for p in packets)
        for _ in range(9):
            await fight.phase()
    assert frightened(fight, "turned") is None
    with patch("check_resolution.dice_roll", return_value=_d20(18)):
        packets = await fight.phase(fight.attack("turned", ranged=True))
    assert any(p["actor_id"] == "turned" and "hit" in p and not p.get("fled") for p in packets)


@pytest.mark.parametrize(
    ("creature", "defense"),
    [
        ("hollow_choir", "Harmonic Shield"),
        ("hollow_veilrender", "Absorb Magic"),
        ("hollow_architect", "Reactive Architecture"),
        ("hollow_architect", "Legendary Resistance"),
    ],
)
async def test_creature_spell_defenses(fight: TurnFight, creature: str, defense: str) -> None:
    await fight.enter({"boss": (creature, 20)}, level=5)
    boss = fight.actor("boss")
    boss.hp_current -= 10
    state = fight.sd.combat_state
    assert state is not None
    if defense == "Legendary Resistance":
        assert state.architect_encounter is not None
        state.architect_encounter["reaction_round"] = state.round_number
    if creature == "hollow_choir":
        assert state.choir_encounter is not None
        state.choir_encounter["phase"] = "exposed"
    await fight.persist()
    old_hp = boss.hp_current
    with patch("check_resolution.dice_roll", return_value=_d20(2)):
        packets = await fight.phase(cast=True)
    outcome = next(row for row in fight.cast(packets)["turn_undead"] if row["target_id"] == "boss")
    assert outcome["outcome"] == "unaffected" and frightened(fight, "boss") is None
    if defense == "Legendary Resistance":
        assert outcome["save"]["success"] and outcome["save"]["success_override"] == defense
        assert fight.actor("boss").action_ledger["legendary resistance"]["remaining"] == 2
    else:
        assert defense in outcome["reason"] and "save" not in outcome
    if defense == "Absorb Magic":
        receipt = fight.cast(packets)["absorbed"][0]
        assert receipt["healed"] == 9 and receipt["hp_current"] == old_hp + 9
