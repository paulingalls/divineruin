"""Turn Undead/Hollow exclusions, expiry and creature spell defenses."""

from copy import deepcopy
from unittest.mock import patch

import pytest
from acceptance._capstone_helpers import _d20, _damage_die
from acceptance._enemy_opportunity_helpers import attack
from acceptance.test_still_anchors import mock_combat_agent_factory as mock_combat_agent_factory
from acceptance.test_turn_undead_hollow import frightened
from acceptance.turn_undead_harness import TurnFight, pos
from acceptance.turn_undead_harness import fight as fight
from test_encounter_facts_damage import dice
from weapon_fixtures import DAGGER, LONGSWORD

import check_resolution_save
from combat_spatial import require_spatial
from conditions import apply_condition


async def test_absolute_authority_does_not_raise_sacred_flame_dc(fight: TurnFight) -> None:
    flame = "divine_sacred_flame"
    await fight.enter({"skeleton": ("undead", 4)}, patron="valdris", known_spells=(flame,))
    await fight.declare_turn(
        {"kind": "ability", "actor_id": fight.caster, "action": flame, "targets": ["skeleton"], "argument_type": ""}
    )
    with patch("check_resolution.dice_roll", return_value=_d20(13)), patch("dice.roll", return_value=_damage_die(5)):
        result = await fight.command("resolve_phase", {})
    cast = next(p["cast"] for p in result["packets"] if p.get("action") == flame)
    damage = cast["damage_result"]
    save = damage["save"]
    assert (save["total"], save["dc"], save["success"], damage["damage"], cast.get("turn_undead_dc_bonus")) == (
        13,
        13,
        True,
        0,
        None,
    )


def scripted_saves(rolls: dict[str, int], default: int):
    """Patch each participant's d20 save to its scripted roll."""
    roll_save = check_resolution_save.roll_participant_save

    def scripted(target, attribute, dc, effect, **kwargs):
        with patch("check_resolution.dice_roll", return_value=_d20(rolls.get(target.id, default))):
            return roll_save(target, attribute, dc, effect, **kwargs)

    return patch("check_resolution_save.roll_participant_save", side_effect=scripted)


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
    with scripted_saves({"saved": 18}, 2):
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


def turn_condition(fight: TurnFight, actor_id: str) -> None:
    """Land the caster's Turn where the cast cannot reach, as the cast itself writes it."""
    target = fight.actor(actor_id)
    target.conditions = apply_condition(target.conditions, "frightened", source=fight.caster, duration=10)
    condition = frightened(fight, actor_id)
    assert condition is not None
    condition["turn_undead"] = {}


def move(actor_id: str, x: float) -> dict:
    return {
        "kind": "move",
        "nythera_step": False,
        "actor_id": actor_id,
        "destination": pos(x),
        "movement_mode": "ground",
        "reshape": [],
    }


async def test_hidden_choir_core(fight: TurnFight) -> None:
    await fight.enter({"choir": ("hollow_choir", 20)}, level=5)
    choir = fight.actor("choir")
    choir.hp_current = 24
    state = await fight.persist()
    assert state.choir_encounter is not None and state.choir_encounter["phase"] == "search"
    before = (choir.hp_current, deepcopy(choir.conditions))
    # The caster beats Harmonic Shield, so only the hidden-core refusal keeps the Choir out.
    with scripted_saves({fight.caster: 18}, 2):
        packets = await fight.phase(cast=True)
    (hidden,) = fight.cast(packets)["turn_undead"]
    assert hidden["outcome"] == "unaffected" and "hidden" in hidden["reason"] and "save" not in hidden
    state = await fight.reload()
    assert (fight.actor("choir").hp_current, fight.actor("choir").conditions) == before
    assert state.choir_encounter is not None and state.choir_encounter["phase"] == "search"


async def test_melody_thrall_flees_without_approaching(fight: TurnFight) -> None:
    await fight.enter({"thrall": ("undead", 4), "voice": ("bandit", -20)})
    thrall = fight.actor("thrall")
    thrall.conditions = apply_condition([], "charmed", source="voice", duration=10)
    thrall.conditions[0]["choir_melody"] = True
    start = dict(require_spatial(await fight.persist())["positions"])
    with patch("check_resolution.dice_roll", return_value=_d20(2)):
        packets = await fight.phase(cast=True)
    (fled,) = [p for p in packets if p["actor_id"] == "thrall" and p.get("fled")]
    end = require_spatial(await fight.reload())["positions"]["thrall"]
    assert fled["origin"] == start["thrall"] and fled["destination"] == end
    assert end["x"] > start["thrall"]["x"]


async def test_flight_ignores_concealed_target(fight: TurnFight) -> None:
    await fight.enter({"skeleton": ("undead", 4)})
    with patch("check_resolution.dice_roll", return_value=_d20(2)):
        await fight.phase(cast=True)
    start = dict(require_spatial(await fight.reload())["positions"])
    await fight.declare_turn(fight.attack("skeleton"))
    # The caster vanishes after declarations, as a mid-round concealment would leave it.
    await fight.pool.execute(
        """UPDATE players SET data=data || jsonb_build_object('flags',
        COALESCE(data->'flags','{}'::jsonb) || '{"concealed": true}'::jsonb) WHERE player_id=$1""",
        fight.caster,
    )
    with patch("check_resolution.dice_roll", return_value=_d20(2)):
        packets = await fight.drain()
    receipts = [p for p in packets if p["actor_id"] == "skeleton"]
    (fled,) = [p for p in receipts if p.get("fled")]
    end = require_spatial(await fight.reload())["positions"]["skeleton"]
    assert fled["origin"] == start["skeleton"] and fled["destination"] == end
    assert end["x"] > start["skeleton"]["x"]
    assert not any("concealed" in str(p.get("reason", "")) for p in receipts)


async def test_turned_creature_keeps_opportunity_attack(fight: TurnFight) -> None:
    await fight.enter({"skeleton": ("undead", 4)})
    turn_condition(fight, "skeleton")
    await fight.persist()
    before = (await fight.player())["hp"]["current"]
    with (
        patch("check_resolution.dice_roll", return_value=_d20(18)),
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
    ):
        packets = await fight.phase(move(fight.caster, -25))
    receipts = [p for p in packets if p["actor_id"] == "skeleton"]
    (strike,) = [p for p in receipts if p.get("opportunity_attack")]
    assert strike.get("hit") and strike["damage"] > 0 and not strike.get("fled")
    assert (await fight.player())["hp"]["current"] == before - strike["damage"]
    assert [p["resolved"] for p in receipts if p.get("fled")] == [True]


async def test_turned_architect_keeps_legendary_strike(fight: TurnFight) -> None:
    await fight.enter({"boss": ("hollow_architect", 20)}, level=5)
    turn_condition(fight, "boss")
    await fight.persist()
    before = (await fight.player())["hp"]["current"]
    await fight.declare_turn()
    await fight.command("resolve_phase", {})
    with (
        patch("check_resolution.dice_roll", return_value=_d20(18)),
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
    ):
        await fight.command(
            "consume_legendary_action",
            {"boss_id": "boss", "action_id": "Geometry Strike", "target_id": fight.caster, "reshape": []},
        )
        packets = await fight.drain()
    receipts = [p for p in packets if p["actor_id"] == "boss"]
    (strike,) = [p for p in receipts if p.get("action") == "Geometry Strike"]
    assert strike.get("hit") and strike["damage"] > 0 and not strike.get("fled")
    assert (await fight.player())["hp"]["current"] == before - strike["damage"]
    assert [p["resolved"] for p in receipts if p.get("fled")] == [True]


async def test_turned_defender_loses_defend_bonus(fight: TurnFight) -> None:
    await fight.enter({"skeleton": ("undead", 4)}, weapon=DAGGER)
    turn_condition(fight, "skeleton")
    await fight.persist()
    target = fight.actor("skeleton")
    hp = target.hp_current
    blade = {**fight.attack("skeleton"), "actor_id": fight.caster, "action": DAGGER["name"], "target_id": "skeleton"}
    with (
        patch("check_resolution.dice_roll", return_value=_d20(11)),
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
    ):
        packets = await fight.phase(blade)
    (strike,) = [p for p in packets if p["actor_id"] == fight.caster]
    assert (strike["attack_total"], strike["target_ac"]) == (target.ac, target.ac)
    assert strike["hit"] and strike["damage"] > 0
    await fight.reload()
    assert fight.actor("skeleton").hp_current == hp - strike["damage"]


async def test_turn_removes_defend_bonus_mid_round(fight: TurnFight) -> None:
    await fight.enter({"skeleton": ("undead", 4)}, ally=True)
    striker = fight.players[1]
    skeleton = fight.actor("skeleton")
    await fight.declare_turn(attack(striker, skeleton.id, LONGSWORD["name"]), cast=True)
    with dice(2, 11):
        packets = (await fight.command("resolve_phase", {}))["packets"]
    (turned,) = [row for row in fight.cast(packets)["turn_undead"] if row["target_id"] == skeleton.id]
    assert turned["outcome"] == "frightened"
    (strike,) = [packet for packet in packets if packet["actor_id"] == striker]
    assert (strike["attack_total"], strike["target_ac"], strike["hit"]) == (skeleton.ac, skeleton.ac, True)


async def test_ordinary_fear_replaces_turn(fight: TurnFight) -> None:
    await fight.enter({"skeleton": ("undead", 4)})
    with patch("check_resolution.dice_roll", return_value=_d20(2)):
        await fight.phase(cast=True)
    target = fight.actor("skeleton")
    target.conditions = apply_condition(target.conditions, "frightened", source=fight.caster, duration=10)
    await fight.persist()
    with (
        patch("check_resolution.dice_roll", return_value=_d20(18)),
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
    ):
        packets = await fight.phase(fight.attack("skeleton", ranged=True))
    receipts = [p for p in packets if p["actor_id"] == "skeleton"]
    assert not any(p.get("fled") for p in receipts)
    assert any(p.get("hit") and p["damage"] > 0 for p in receipts)
