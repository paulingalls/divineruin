"""Shadow Veil through registered tools and durable combat rows."""

import json

import pytest
from acceptance.mawling_harness import MawlingHarness

import db_queries
from _gods_content import load_gods

GIFT = "syrath_shadow_veil"


@pytest.fixture
def mock_combat_agent_factory():
    return None


@pytest.fixture
async def veil(reset_db_pool):
    h = MawlingHarness()
    await h.prepare((3, 3), companion="")
    try:
        for pid in h.players:
            await h.pool.execute(
                "UPDATE players SET data=data || $2::jsonb WHERE player_id=$1",
                pid,
                json.dumps(
                    {
                        "divine_favor": {"patron": "syrath", "level": 10, "max": 100},
                        "flags": {"keepsake": True},
                        "patron_gifts": {"other": {"x": 1}},
                    }
                ),
            )
        await h.command("enter_mode", {"mode": "combat", "encounter_id": h.encounter_id})
        yield h
    finally:
        await h.close()


async def row(h, index=0):
    player = await db_queries.get_player(h.players[index])
    assert player is not None
    return player


async def use(h, *, error=False):
    info = await h.command("query_info", {"kind": "patron"})
    gift = info["layer_1_gift"]
    assert gift["id"] == GIFT and gift["status"] == "active"
    return await h.command("activate", {"id": gift["id"]}, error=error)


def test_authored_gift_is_active():
    gift = next(g["layer_1_gift"] for g in load_gods() if g["god_id"] == "syrath")
    assert (gift["id"], gift["status"], gift["recharge"]) == (GIFT, "active", "short_rest")


async def test_produced_activation_spends_durably(veil):
    h = veil
    other = await row(h, 1)
    result = await use(h)
    state = await h.reload()
    player = await row(h)
    assert result["concealment"]["concealed"] is True
    assert player["flags"] == {
        "keepsake": True,
        "concealed": True,
        "shadow_veil_combat_id": state.combat_id,
        "shadow_veil_round": state.round_number,
    }
    assert player["patron_gifts"] == {"other": {"x": 1}, GIFT: {"spent": True}}
    assert await row(h, 1) == other
    assert "spent" in await h.command("activate", {"id": GIFT}, error=True)


@pytest.mark.parametrize("boundary", ["round", "end"])
async def test_expiry_preserves_ordinary_hiding(veil, boundary):
    h = veil
    if boundary == "end":
        h.players.reverse()
    state = await h.reload()
    state.round_number = 3
    await h.persist()
    h.players.reverse()
    try:
        await stealth(h, 20)
    finally:
        h.players.reverse()
    await use(h)
    if boundary == "round":
        await h.command(
            "declare_phase", {"declarations": [{"kind": "defend", "actor_id": p.id} for p in state.participants]}
        )
        first = await h.command("resolve_phase", {})
        assert (await row(h))["flags"]["concealed"] is True, first
        for _ in range(12):
            await h.command("resolve_phase", {})
            current = await h.reload()
            if current.round_number == 4:
                break
            assert (await row(h))["flags"]["concealed"]
        assert current.round_number == 4
    else:
        state = await h.reload()
        guest = state.get_participant(h.players[0])
        guest.hp_current = 0
        guest.is_fallen = True
        await h.persist()
        await h.pool.execute(
            "UPDATE players SET data=jsonb_set(data,'{divine_favor,patron}','\"veythar\"') WHERE player_id=$1",
            h.players[0],
        )
        combat_id = state.combat_id
        await h.command("end_combat", {"outcome": "fled"})
        assert not await h.pool.fetchval("SELECT 1 FROM combat_instances WHERE combat_id=$1", combat_id)
    player = await row(h)
    assert player["flags"] == {"keepsake": True, "concealed": False}
    assert player["patron_gifts"][GIFT] == {"spent": True}
    assert (await row(h, 1))["flags"]["concealed"] is True


async def reconnect(h, *, close=True):
    from acceptance.voice_condition_harness import ScenarioModel
    from livekit.agents import AgentSession

    from combat_agent import CombatAgent
    from session_data import SessionData

    if close:
        await h.session.aclose()
    state = await h.reload()
    h.sd = SessionData(player_id=h.players[0], location_id=h.sd.location_id, room=h.sd.room)
    h.sd.combat_state = state
    h.model = ScenarioModel([])
    h.session = AgentSession(llm=h.model, userdata=h.sd)
    await h.session.start(CombatAgent())


async def stealth(h, face):
    from unittest.mock import patch

    from acceptance._capstone_helpers import _d20

    with patch("check_resolution.dice_roll", return_value=_d20(face)):
        return await h.command(
            "check",
            {
                "roll": {
                    "kind": "skill",
                    "skill": "stealth",
                    "difficulty": "easy",
                    "context_description": "Hide from the watcher",
                    "hearing_only": False,
                }
            },
        )


@pytest.mark.parametrize("face", [1, 20])
async def test_stealth_takes_ownership_or_reveals(veil, face):
    h = veil
    await use(h)
    result = await stealth(h, face)
    assert result["concealment"]["concealed"] is (face == 20)
    assert (await row(h))["flags"] == {"keepsake": True, "concealed": face == 20}
    await h.command("end_combat", {"outcome": "fled"})
    assert (await row(h))["flags"]["concealed"] is (face == 20)


async def test_already_hidden_and_other_patron_refuse_without_spending(veil):
    h = veil
    await stealth(h, 20)
    before = await row(h)
    assert "already hidden" in (await use(h, error=True)).lower()
    assert await row(h) == before
    await h.pool.execute(
        "UPDATE players SET data=jsonb_set(data,'{divine_favor,patron}','\"veythar\"') WHERE player_id=$1",
        h.players[0],
    )
    before = await row(h)
    assert "Syrath" in await h.command("activate", {"id": GIFT}, error=True)
    assert await row(h) == before


async def test_reconnect_rest_and_combat_only(veil):
    from livekit.agents import Agent, AgentSession

    from exploration_agent import EXPLORATION_TOOLS

    h = veil
    await use(h)
    await reconnect(h)
    assert (await row(h))["flags"]["concealed"]
    assert "spent" in await use(h, error=True)
    await h.command("end_combat", {"outcome": "fled"})
    await h.session.aclose()
    h.sd.location_id = "millhaven_inn"
    await h.pool.execute(
        "UPDATE players SET data=jsonb_set(data,'{location_id}','\"millhaven_inn\"') WHERE player_id=$1",
        h.players[0],
    )
    h.session = AgentSession(llm=h.model, userdata=h.sd)
    await h.session.start(Agent(instructions="Execute the command.", tools=EXPLORATION_TOOLS))
    assert "combat-only" in await h.command("activate", {"id": GIFT}, error=True)
    await h.command("rest", {"rest_type": "long"})
    assert (await row(h))["patron_gifts"][GIFT]["spent"] is True
    await h.command("rest", {"rest_type": "short"})
    assert (await row(h))["patron_gifts"] == {"other": {"x": 1}, GIFT: {"spent": False}}
    assert not (await row(h))["flags"]["concealed"]
    await h.command("enter_mode", {"mode": "combat", "encounter_id": h.encounter_id})
    await use(h)


@pytest.mark.parametrize("face", [1, 20])
async def test_attack_reveals_on_ally_commit(veil, face):
    from unittest.mock import patch

    from acceptance._capstone_helpers import _d20

    h = veil
    await use(h)
    state = await h.reload()
    enemy = next(p for p in state.participants if p.type == "enemy")
    await h.command(
        "declare_phase",
        {
            "declarations": [
                {
                    "kind": "attack",
                    "actor_id": h.players[0],
                    "action": "Longsword",
                    "target_id": enemy.id,
                    "held_item_id": "",
                    "rider": "",
                },
                *[{"kind": "defend", "actor_id": p.id} for p in state.participants if p.id != h.players[0]],
            ]
        },
    )
    with patch("check_resolution.dice_roll", return_value=_d20(face)):
        result = await h.command("resolve_phase", {})
    assert (await row(h))["flags"] == {"keepsake": True, "concealed": False}
    assert (await row(h))["patron_gifts"][GIFT]["spent"]
    packet = next(p for p in result["packets"] if p["actor_id"] == h.players[0])
    assert packet["hit"] is (face == 20)
    assert packet["concealment"]["ended_by"] == "attack"


@pytest.mark.parametrize("patron", ["syrath", "veythar"])
async def test_authenticated_guest_uses_own_patron(veil, patron):
    h = veil
    primary = await row(h)
    await h.pool.execute(
        "UPDATE players SET data=jsonb_set(data,'{divine_favor,patron}',$2::jsonb) WHERE player_id=$1",
        h.players[1],
        json.dumps(patron),
    )
    h.players.reverse()
    try:
        result = await h.command("activate", {"id": GIFT}, error=patron != "syrath")
        if patron == "syrath":
            assert (await row(h))["patron_gifts"][GIFT]["spent"]
        else:
            assert "Syrath" in result
            assert GIFT not in (await row(h))["patron_gifts"]
        assert await row(h, 1) == primary
    finally:
        h.players.reverse()


async def test_cast_reveals_after_hidden_discount_and_refusal_preserves(veil):
    from acceptance.seeds import seed_known_spells

    h = veil
    await h.pool.execute(
        "UPDATE players SET data=data || $2::jsonb WHERE player_id=$1",
        h.players[0],
        json.dumps({"class": "mage", "level": 20, "focus": {"current": 50, "max": 50}}),
    )
    await seed_known_spells(h.pool, h.players[0], ("arcane_magic_missile",))
    state = await h.reload()
    target = next(p.id for p in state.participants if p.type == "enemy")
    state.get_participant(target).hp_current = 100
    state.get_participant(target).hp_max = 100
    await h.persist()
    await use(h)
    before = await row(h)
    await h.command("activate", {"id": "arcane_fireball", "target_id": target}, error=True)
    assert await row(h) == before
    for expected in (0, 1):
        state = await h.reload()
        await h.command(
            "declare_phase",
            {
                "declarations": [
                    {
                        "kind": "ability",
                        "actor_id": h.players[0],
                        "action": "arcane_magic_missile",
                        "targets": [target],
                        "argument_type": "",
                    },
                    *[{"kind": "defend", "actor_id": p.id} for p in state.participants if p.id != h.players[0]],
                ]
            },
        )
        result = await h.command("resolve_phase", {})
        packet = next(p for p in result["packets"] if p["actor_id"] == h.players[0])
        packet = packet["cast"]
        assert packet["resonance_generated"] == expected
        assert (await row(h))["flags"] == {"keepsake": True, "concealed": False}
        if expected == 0:
            assert packet["concealment"]["ended_by"] == "cast"
        await h.drain()


async def test_terminal_wrap_expires_hidden_defender(veil):
    from unittest.mock import patch

    from acceptance._capstone_helpers import _d20

    h = veil
    await use(h)
    state = await h.reload()
    enemies = [p for p in state.participants if p.type == "enemy"]
    for enemy in enemies:
        enemy.hp_current = 0
        enemy.is_fallen = True
    enemies[0].hp_current = 1
    enemies[0].is_fallen = False
    await h.persist()
    await h.command(
        "declare_phase",
        {
            "declarations": [
                {
                    "kind": "attack",
                    "actor_id": h.players[1],
                    "action": "Longsword",
                    "target_id": enemies[0].id,
                    "held_item_id": "",
                    "rider": "",
                },
                {"kind": "defend", "actor_id": h.players[0]},
            ]
        },
    )
    with (
        patch("check_resolution.dice_roll", return_value=_d20(20)),
        patch("check_resolution_attack.dice_roll", return_value=_d20(20)),
    ):
        result = await h.command("resolve_phase", {})
        assert h.sd.combat_state.get_participant(enemies[0].id).hp_current == 0, result["packets"]
        for _ in range(8):
            await h.command("resolve_phase", {})
            if h.sd.combat_state is None:
                break
    assert h.sd.combat_state is None
    assert (await row(h))["flags"] == {"keepsake": True, "concealed": False}
    assert (await row(h))["patron_gifts"][GIFT]["spent"]
