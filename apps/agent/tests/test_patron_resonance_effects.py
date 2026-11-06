"""Patron effects through activate, persisted casts, and select."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sample_fixtures import make_context, make_db_mod

import ability_persistence
import db_mutations_resonance
import hollow_echo
import spell_casting
import spells
import ward_resolution
from activate_tools import _activate_impl
from choice_tools import _select_impl


async def cast(
    patron,
    total=9,
    *,
    ward: bool | None = False,
    race=None,
    rolls=(18, 1),
    spell_id="arcane_bolt",
    ctx=None,
    row=None,
    database=None,
    queries=None,
):
    ctx = ctx or make_context()
    ctx.userdata.resonance.current = total
    ctx.userdata.resonance.flickering_bonus = int(race == "thessyn")
    row = (
        row
        if row is not None
        else {
            "class": {"arcane": "mage", "divine": "cleric", "primal": "druid"}[spells.get_spell(spell_id).source],
            "level": 5,
            "focus": {"current": 50},
            "race": race,
            "divine_favor": {"patron": patron},
        }
    )
    real_database = database is not None
    database, conn = database or make_db_mod()
    if isinstance(conn, MagicMock):
        conn.execute = AsyncMock()
    queries = queries or MagicMock(get_players_for_update=AsyncMock(return_value={ctx.userdata.acting_player_id: row}))
    die = MagicMock(roll=MagicMock(side_effect=[MagicMock(total=r) for r in rolls]))
    echo = MagicMock(publish_hollow_echo=AsyncMock())
    warning = MagicMock()
    resources = ability_persistence if real_database else MagicMock(update_player_resources=AsyncMock())

    async def entry(context, sid, **kw):
        return await spell_casting._cast_spell_impl(
            context,
            sid,
            **kw,
            db_mod=database,
            queries_mod=queries,
            persistence_mod=resources,
            resonance_mutations_mod=db_mutations_resonance
            if real_database
            else MagicMock(update_player_resonance=AsyncMock()),
            resonance_events_mod=MagicMock(publish_resonance_changed=AsyncMock()),
            character_spells_mod=MagicMock(get_known=AsyncMock(return_value=[{"spell_id": sid}])),
            ward_resolution_mod=ward_resolution
            if ward is None
            else MagicMock(resolve_scope_ward=AsyncMock(return_value={} if ward else None)),
            dice_mod=die,
            echo_events_mod=echo,
            vaelti_warning_mod=warning,
        )

    packet = json.loads(await _activate_impl(ctx, spell_id, cast_spell_mod=MagicMock(_cast_spell_impl=entry)))
    return packet, ctx, row, conn, die, echo, warning, resources


@pytest.mark.parametrize("total", [4, 5, 8, 9])
@pytest.mark.parametrize("patron", ["veythar", None, "zhael"])
async def test_flickering_thresholds(patron, total):
    packet, _, _, _, die, echo, _, _ = await cast(patron, total)
    expected = 0 if total == 4 else 2 if total == 9 or patron == "veythar" else 1
    assert packet["resonance_modifiers"] == {"damage_dice": expected, "dc": 2 * int(total == 9)}
    assert packet["state"] == ("stable" if total == 4 else "overreach" if total == 9 else "flickering")
    assert packet["resonance_generated"] == 0
    assert die.roll.call_count == (2 if patron == "zhael" else 1) * int(total == 9)
    assert echo.publish_hollow_echo.await_count == int(total == 9 and patron != "zhael")


@pytest.mark.parametrize(
    "patron,ward,expected", [("aelora", True, (1, 0)), (None, True, (0, -1)), ("aelora", False, (1, 0))]
)
async def test_ward_harmony(patron, ward, expected):
    packet, *_ = await cast(patron, 5, ward=ward)
    assert packet["ward_active"] is ward
    assert packet["resonance_modifiers"] == dict(zip(("damage_dice", "dc"), expected, strict=True))


@pytest.mark.parametrize("rolls,chosen", [((18, 1), "second"), ((1, 18), "first"), ((18, 18), "second")])
@pytest.mark.parametrize(
    "total,ward,race", [(9, False, None), (12, False, None), (15, True, None), (9, False, "vaelti")]
)
async def test_echo_offer_then_spoken_selection(rolls, chosen, total, ward, race):
    packet, ctx, row, conn, die, echo, warning, _ = await cast("zhael", total, rolls=rolls, ward=ward, race=race)
    offer = packet["pending_choice"]
    assert offer["kind"] == "hollow_echo" and offer["resolve_with"] == "select"
    assert "hollow_echo" not in packet
    echo.publish_hollow_echo.assert_not_awaited()
    assert die.roll.call_count == 2
    assert warning.publish_vaelti_echo_warning.call_count == int(race == "vaelti")
    assert [o["id"] for o in offer["options"]] == ["first", "second"]
    expected = [hollow_echo.resolve_hollow_echo(r, total, ward_bonus=4 if ward else 0) for r in rolls]
    assert [o["band"] for o in offer["options"]] == [e.band for e in expected]
    pending = json.loads(conn.execute.call_args.args[2])
    row["pending_hollow_echo_choice"] = pending
    dbmod, select_conn = make_db_mod()
    select_conn.execute = AsyncMock()
    queries = MagicMock(get_players_for_update=AsyncMock(return_value={ctx.userdata.acting_player_id: row}))
    with patch("hollow_echo_events.publish_hollow_echo", new_callable=AsyncMock) as published:
        result = json.loads(await _select_impl(ctx, offer["choice_id"], chosen, db_mod=dbmod, queries_mod=queries))
    assert result["hollow_echo"]["band"] == expected[int(chosen == "second")].band
    published.assert_awaited_once()
    assert die.roll.call_count == 2


async def test_thessyn_trigger():
    packet, _, _, _, die, echo, _, _ = await cast("zhael", 9, race="thessyn")
    assert "pending_choice" not in packet and "hollow_echo" not in packet
    die.roll.assert_not_called()
    echo.publish_hollow_echo.assert_not_awaited()


@pytest.mark.parametrize("patron,bonus", [("veythar", 2), (None, 1)])
async def test_choir_phase_lands_extra_damage_dice(patron, bonus, mock_combat_agent_factory):
    from functools import partial
    from random import Random
    from types import SimpleNamespace

    from combat._helpers import _resolve_deps
    from combat.test_choir_encounter import start_choir

    import check_resolution_attack
    import combat_turn
    import dice

    ctx, _, mutations, queries = await start_choir()
    state = ctx.userdata.combat_state
    state.choir_encounter["phase"] = "exposed"
    caster = state.get_participant("player_1")
    caster.level = 5
    caster.attributes = {"intelligence": 18}
    ctx.userdata.resonance.current = 5
    row = {
        "player_id": "player_1",
        "class": "mage",
        "level": 5,
        "focus": {"current": 50},
        "divine_favor": {"patron": patron},
    }
    queries.get_player = AsyncMock(return_value=row)
    deps: dict = _resolve_deps()
    deps.update(mutations=mutations, queries=queries, resolver=check_resolution_attack)
    deps["character_spells_mod"].get_known.return_value = [{"spell_id": "arcane_bolt"}]
    deps["cast_resolver"] = SimpleNamespace(
        _gate_spell=spell_casting._gate_spell,
        _resolve_cast=partial(spell_casting._resolve_cast, character_spells_mod=deps["character_spells_mod"]),
    )
    await combat_turn._declare_phase_impl(
        ctx,
        {
            "player_1": {"type": "ability", "action": "arcane_bolt", "target_id": "choir_zone"},
            "choir_zone": {"type": "defend"},
        },
        mutations=mutations,
    )
    rolled = []

    def damage(notation, **kw):
        result = dice.roll(notation, rng=Random(7))
        rolled.append((notation, result.total))
        return result

    before = state.get_participant("choir_zone").hp_current
    with (
        patch("check_resolution.dice_roll", return_value=SimpleNamespace(total=19)),
        patch("check_resolution_attack.dice_roll", side_effect=damage),
    ):
        raw = await combat_turn._resolve_phase_impl(ctx, **deps)
        assert isinstance(raw, str)
        result = json.loads(raw)
    landed = next(p["cast"] for p in result["packets"] if "cast" in p)
    assert rolled[0][0] == f"{2 + bonus}d6"
    assert landed["resonance_modifiers"]["damage_dice"] == bonus
    assert (
        before - ctx.userdata.combat_state.get_participant("choir_zone").hp_current == landed["damage_result"]["damage"]
    )
    assert landed["damage_result"]["damage"] >= rolled[0][1]


async def test_shared_encounter_ward_uses_each_casters_locked_patron():
    from acceptance.test_voice_condition_commands import scene

    host, guest = "player_1", "guest"
    ctx = make_context(player_id=host, party_member_ids=[host, guest])
    ctx.userdata.combat_state = scene(host, guest, "outside_cast")
    ctx.userdata.combat_state.veil_ward = {"source": "cleric", "dismissible": True}
    packets = []
    for pid, patron in [(host, "aelora"), (guest, None)]:
        # Each authenticated speaker casts in the same encounter; cached patron state is irrelevant.
        local = ctx if pid == host else make_context(player_id=guest, party_member_ids=[host, guest])
        local.userdata.combat_state = ctx.userdata.combat_state
        local.userdata.party.primary.patron_id = "aelora"
        row = {"class": "mage", "level": 5, "focus": {"current": 50}, "divine_favor": {"patron": patron}}
        packet, _, _, _, _, _, _, resources = await cast(
            patron, 4, ctx=local, row=row, ward=None, spell_id="arcane_fireball"
        )
        packets.append(packet)
        resources.update_player_resources.assert_awaited_once()
        assert resources.update_player_resources.await_args.kwargs["focus"] == 45
    assert [p["resonance_generated"] for p in packets] == [1, 1]
    assert [p["resonance_modifiers"] for p in packets] == [{"damage_dice": 1, "dc": 0}, {"damage_dice": 0, "dc": -1}]
    assert all(p["ward_active"] for p in packets)


async def test_pending_choice_reopens_combat_declaration_without_actor_writes():
    from combat._helpers import _ctx_at_resolution, _resolve_deps
    from livekit.agents.llm import ToolError

    import combat_turn
    import patron_echo_choice

    ctx = _ctx_at_resolution()
    pending = {
        "choice_id": "hollow_echo_pending",
        "player_id": "player_1",
        "options": [
            {"id": oid, "band": "nothing", "name": "Nothing stirs", "effect": "No side effect."}
            for oid in ("first", "second")
        ],
    }
    state = ctx.userdata.combat_state
    state.pending_declarations["player_1"] = {"type": "ability", "action": "arcane_bolt"}
    deps = _resolve_deps()
    deps["queries"].get_player.return_value[patron_echo_choice.KEY] = pending
    deps["character_spells_mod"].get_known.return_value = [{"spell_id": "arcane_bolt"}]
    with pytest.raises(ToolError, match="hollow_echo_pending"):
        await combat_turn._resolve_phase_impl(ctx, **deps)
    assert ctx.userdata.combat_state.beat == "declaration"
    deps["mutations"].update_player_hp.assert_not_awaited()


async def test_veythar_does_not_amplify_divine_flickering():
    packet, *_ = await cast("veythar", 5, spell_id="divine_sacred_flame")
    assert packet["resonance_modifiers"] == {"damage_dice": 1, "dc": 0}


async def test_aelora_overreach_retains_positive_modifiers_and_ward_echo_bonus():
    packet, _, _, _, _, echo, _, _ = await cast("aelora", 9, ward=True, rolls=(1,))
    assert packet["resonance_modifiers"] == {"damage_dice": 2, "dc": 2}
    assert packet["hollow_echo"]["band"] == "hollow_attention"
    echo.publish_hollow_echo.assert_awaited_once()
