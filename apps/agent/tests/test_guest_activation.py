"""A bound turn pays its own activation costs."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from livekit.agents.llm import ToolError
from sample_fixtures import make_context, make_db_mod

from combat_participant import CombatParticipant
from combat_state import CombatState
from draethar_inner_fire import _inner_fire_impl
from spell_casting import _cast_spell_impl
from veil_anchor_tools import _deploy_veil_anchor_impl
from veil_ward_tools import _activate_veil_ward_impl


@pytest.mark.parametrize("speaker,other", [("player_1", "player_2"), ("player_2", "player_1")])
async def test_spell_explicit_other_caster_refused_before_read_or_debit(speaker, other):
    ctx = make_context(party_member_ids=["player_2"])
    db_mod, _ = make_db_mod()
    queries = MagicMock(get_players_for_update=AsyncMock(return_value={}))
    with ctx.userdata._bind_authenticated_actor(speaker, 4, lambda *_: None):
        with pytest.raises(ToolError, match=r"caster|speaker|turn"):
            await _cast_spell_impl(ctx, "firebolt", caster_id=other, db_mod=db_mod, queries_mod=queries)
    queries.get_players_for_update.assert_not_awaited()


@pytest.mark.parametrize("speaker,other", [("player_1", "player_2"), ("player_2", "player_1")])
async def test_ward_explicit_other_caster_refused_before_read_or_debit(speaker, other):
    ctx = make_context(party_member_ids=["player_2"])
    db_mod, _ = make_db_mod()
    queries = MagicMock(get_player=AsyncMock())
    with ctx.userdata._bind_authenticated_actor(speaker, 4, lambda *_: None):
        with pytest.raises(ToolError, match=r"caster|speaker|turn"):
            await _activate_veil_ward_impl(ctx, caster_id=other, db_mod=db_mod, queries_mod=queries)
    queries.get_player.assert_not_awaited()


async def test_guest_anchor_consumes_guest_stack_and_writes_ward():
    ctx = make_context(party_member_ids=["player_2"])
    db_mod, conn = make_db_mod()
    queries = MagicMock(get_inventory_item=AsyncMock(return_value={"quantity": 1}))
    inventory = MagicMock(transact_inventory=AsyncMock())
    wards = MagicMock(write_ward=AsyncMock())
    resolution = MagicMock(resolve_scope_ward=AsyncMock(return_value=None))
    with patch("veil_anchor_tools.veil_ward_events.publish_veil_ward_changed", AsyncMock()):
        with ctx.userdata._bind_authenticated_actor("player_2", 4, lambda *_: None):
            await _deploy_veil_anchor_impl(
                ctx,
                "veil_ward_anchor_small",
                db_mod=db_mod,
                queries_mod=queries,
                inventory_mutations_mod=inventory,
                ward_mutations_mod=wards,
                resolution_mod=resolution,
            )
    queries.get_inventory_item.assert_awaited_once_with(
        "player_2", "veil_ward_anchor_small", conn=conn, for_update=True
    )
    inventory.transact_inventory.assert_awaited_once_with("player_2", "veil_ward_anchor_small", -1, conn=conn)
    wards.write_ward.assert_awaited_once()


async def test_guest_spell_debits_only_guest_and_syncs_guest_state():
    import json

    from _spell_casting_helpers import _known, _spell

    ctx = make_context(party_member_ids=["player_2"])
    host, guest = ctx.userdata.party.members
    host.resonance.current = 11
    host.concentration.spell_id = "host_spell"
    guest.resonance.current = 2
    db_mod, conn = make_db_mod()
    row = {"player_id": "player_2", "class": "mage", "level": 5, "focus": {"current": 10, "max": 10}}
    queries = MagicMock(get_players_for_update=AsyncMock(return_value={"player_2": row}))
    persistence = MagicMock(update_player_resources=AsyncMock())
    resonance = MagicMock(update_player_resonance=AsyncMock())
    concentration = MagicMock(update_player_concentration=AsyncMock())
    events = MagicMock(publish_resonance_changed=AsyncMock())
    ward = MagicMock(resolve_scope_ward=AsyncMock(return_value=None))
    spell = _spell(spell_id="hold_flame", focus_cost=3, resonance=2, concentration=True)
    spells = MagicMock(get_spell=MagicMock(return_value=spell))
    with ctx.userdata._bind_authenticated_actor("player_2", 4, lambda *_: None):
        packet = json.loads(
            await _cast_spell_impl(
                ctx,
                spell.id,
                db_mod=db_mod,
                queries_mod=queries,
                persistence_mod=persistence,
                resonance_mutations_mod=resonance,
                concentration_mutations_mod=concentration,
                resonance_events_mod=events,
                ward_resolution_mod=ward,
                spells_mod=spells,
                character_spells_mod=_known(spell.id),
            )
        )
    queries.get_players_for_update.assert_awaited_once()
    assert queries.get_players_for_update.call_args.args[0] == ["player_2"]
    persistence.update_player_resources.assert_awaited_once_with("player_2", focus=7, conn=conn)
    assert resonance.update_player_resonance.call_args.args[0] == "player_2"
    concentration.update_player_concentration.assert_awaited_once_with("player_2", spell.id, conn=conn)
    assert guest.resonance.current != 2 and guest.concentration.spell_id == spell.id
    assert host.resonance.current == 11 and host.concentration.spell_id == "host_spell"
    assert packet["effect"] == spell.mechanics


async def test_guest_ward_charges_guest_and_raises_scope_ward():
    ctx = make_context(party_member_ids=["player_2"])
    ctx.userdata.party.primary.resonance.current = 8
    db_mod, conn = make_db_mod()
    row = {"player_id": "player_2", "class": "cleric", "level": 7, "focus": {"current": 10}, "stamina": {"current": 10}}
    queries = MagicMock(get_player=AsyncMock(return_value=row))
    persistence = MagicMock(update_player_resources=AsyncMock())
    wards = MagicMock(write_ward=AsyncMock())
    resolution = MagicMock(resolve_scope_ward=AsyncMock(return_value=None))
    with patch("veil_ward_tools.veil_ward_events.publish_veil_ward_changed", AsyncMock()):
        with ctx.userdata._bind_authenticated_actor("player_2", 4, lambda *_: None):
            await _activate_veil_ward_impl(
                ctx,
                db_mod=db_mod,
                queries_mod=queries,
                persistence_mod=persistence,
                ward_mutations_mod=wards,
                resolution_mod=resolution,
            )
    queries.get_player.assert_awaited_once_with("player_2", conn=conn, for_update=True)
    assert persistence.update_player_resources.call_args.args[0] == "player_2"
    wards.write_ward.assert_awaited_once()
    assert ctx.userdata.location_ward["source"] == "cleric"
    assert ctx.userdata.party.primary.resonance.current == 8


async def test_party_member_inner_fire_round_trip():
    from party_state import PartyState

    party = make_context(party_member_ids=["player_2"]).userdata.party
    party.members[1].draethar_inner_fire_used = True
    saved = party.to_dict()
    assert PartyState.from_dict(saved).members[1].draethar_inner_fire_used
    for member in saved["members"]:
        member.pop("draethar_inner_fire_used")
    assert all(not m.draethar_inner_fire_used for m in PartyState.from_dict(saved).members)


def _fire_fixture():
    ctx = make_context(party_member_ids=["player_2"])
    host, guest = ctx.userdata.party.members
    host.resonance.current = 12
    host.concentration.spell_id = "host_spell"
    guest.resonance.current = 9
    guest.concentration.spell_id = "guest_spell"
    ctx.userdata.combat_state = CombatState(
        combat_id="c1",
        participants=[
            CombatParticipant(id=pid, name=pid, type="player", initiative=10, hp_current=20, hp_max=20, ac=14)
            for pid in ("player_1", "player_2")
        ],
        initiative_order=["player_1", "player_2"],
    )
    db_mod, conn = make_db_mod()
    queries = MagicMock(get_player=AsyncMock(return_value={"player_id": "player_2", "race": "draethar"}))
    hp = MagicMock(update_player_hp=AsyncMock(), save_combat_state=AsyncMock())
    resonance = MagicMock(update_player_resonance=AsyncMock())
    events = MagicMock(publish_resonance_changed=AsyncMock())
    dice = MagicMock(roll=MagicMock(return_value=MagicMock(total=4)))
    concentration = MagicMock(break_concentration_on_damage=AsyncMock(return_value=None))
    return ctx, db_mod, conn, queries, hp, resonance, events, dice, concentration


async def _fire(ctx, db_mod, queries, hp, resonance, events, dice, concentration):
    return await _inner_fire_impl(
        ctx,
        db_mod=db_mod,
        queries_mod=queries,
        hp_mutations_mod=hp,
        resonance_mutations_mod=resonance,
        resonance_events_mod=events,
        dice_mod=dice,
        concentration_break_mod=concentration,
    )


async def test_guest_inner_fire_burns_guest_only_and_host_can_use():
    ctx, db_mod, conn, queries, hp, resonance, events, dice, concentration = _fire_fixture()
    session = ctx.userdata
    with session._bind_authenticated_actor("player_2", 4, lambda *_: None):
        await _fire(ctx, db_mod, queries, hp, resonance, events, dice, concentration)
    host, guest = session.party.members
    resonance.update_player_resonance.assert_awaited_once_with("player_2", 6, conn=conn)
    hp.update_player_hp.assert_awaited_once_with("player_2", 16, conn=conn)
    events.publish_resonance_changed.assert_awaited_once_with(
        session, resonance_track=guest.resonance, caster_id="player_2"
    )
    assert guest.resonance.current == 6 and guest.draethar_inner_fire_used
    assert host.resonance.current == 12 and not host.draethar_inner_fire_used
    assert host.concentration.spell_id == "host_spell"
    assert session.combat_state.get_participant("player_1").hp_current == 20
    assert session.combat_state.get_participant("player_2").hp_current == 16
    concentration.break_concentration_on_damage.assert_awaited_once()
    assert concentration.break_concentration_on_damage.call_args.kwargs["damaged_player_id"] == "player_2"
    with session._bind_authenticated_actor("player_2", 4, lambda *_: None):
        with pytest.raises(ToolError, match="already spent"):
            await _fire(ctx, db_mod, queries, hp, resonance, events, dice, concentration)
    queries.get_player = AsyncMock(return_value={"player_id": "player_1", "race": "draethar"})
    with session._bind_authenticated_actor("player_1", 4, lambda *_: None):
        await _fire(ctx, db_mod, queries, hp, resonance, events, dice, concentration)
    assert host.draethar_inner_fire_used


async def test_inner_fire_revoked_during_resonance_write_leaves_participant_intact():
    ctx, db_mod, _conn, queries, hp, resonance, events, dice, concentration = _fire_fixture()
    live = True

    def validate(*_):
        if not live:
            raise RuntimeError("stale authenticated actor")

    async def revoke(*_args, **_kwargs):
        nonlocal live
        live = False

    resonance.update_player_resonance.side_effect = revoke
    with ctx.userdata._bind_authenticated_actor("player_2", 4, validate):
        with pytest.raises(RuntimeError, match="stale"):
            await _fire(ctx, db_mod, queries, hp, resonance, events, dice, concentration)
    assert ctx.userdata.combat_state.get_participant("player_2").hp_current == 20
    assert ctx.userdata.party.members[1].resonance.current == 9
    assert not ctx.userdata.party.members[1].draethar_inner_fire_used
    hp.update_player_hp.assert_not_awaited()


async def test_combat_start_resets_every_member_after_use():
    from combat_init import _start_combat_impl
    from tests.combat.test_start_combat import SAMPLE_PLAYER, _make_start_combat_mocks

    ctx = make_context(party_member_ids=["player_2"])
    for member in ctx.userdata.party.members:
        member.draethar_inner_fire_used = True
    mutations, queries, content = _make_start_combat_mocks()
    queries.get_players_for_update = AsyncMock(return_value={"player_2": {**SAMPLE_PLAYER, "player_id": "player_2"}})
    await _start_combat_impl(ctx, "goblin_patrol", "Ambush!", mutations=mutations, queries=queries, content=content)
    assert all(not m.draethar_inner_fire_used for m in ctx.userdata.party.members)


def test_combat_end_resets_every_member_after_use():
    from combat_end import _end_combat_finish

    ctx = make_context(party_member_ids=["player_2"])
    session = ctx.userdata
    for member in session.party.members:
        member.draethar_inner_fire_used = True
    cs = CombatState(combat_id="c1", participants=[], initiative_order=[], location_id=session.location_id)
    session.combat_state = cs
    end_data = {
        "xp_total": 0,
        "xp_granted": 0,
        "defeated_enemies": [],
        "milestone_grants": [],
        "specialization_fork": None,
        "weapon_durability": [],
    }
    with patch("combat_end._build_handoff_agent", return_value=object()):
        _end_combat_finish(session, cs, "victory", end_data)
    assert all(not m.draethar_inner_fire_used for m in session.party.members)


@pytest.mark.parametrize("revocation", ["lock", "ward", "focus", "resonance"])
async def test_spell_revocation_at_each_write_refuses_and_rolls_back(revocation):
    from _spell_casting_helpers import _known, _spell

    ctx = make_context(party_member_ids=["player_2"])
    db_mod, _ = make_db_mod()
    live = True

    def validate(*_):
        if not live:
            raise RuntimeError("stale authenticated actor")

    async def revoke(*_args, **_kwargs):
        nonlocal live
        live = False

    row = {"player_id": "player_2", "class": "mage", "level": 5, "focus": {"current": 10}}

    async def lock(*_args, **_kwargs):
        if revocation == "lock":
            await revoke()
        return {"player_2": row}

    queries = MagicMock(get_players_for_update=AsyncMock(side_effect=lock))
    persistence = MagicMock(update_player_resources=AsyncMock(side_effect=revoke if revocation == "focus" else None))
    resonance = MagicMock(update_player_resonance=AsyncMock(side_effect=revoke if revocation == "resonance" else None))
    concentration = MagicMock(update_player_concentration=AsyncMock())

    async def resolve(*_args, **_kwargs):
        if revocation == "ward":
            await revoke()
        return None

    ward = MagicMock(resolve_scope_ward=AsyncMock(side_effect=resolve))
    spell = _spell(spell_id="hold_flame", focus_cost=3, resonance=2, concentration=True)
    spells = MagicMock(get_spell=MagicMock(return_value=spell))
    with ctx.userdata._bind_authenticated_actor("player_2", 4, validate):
        with pytest.raises(RuntimeError, match="stale"):
            await _cast_spell_impl(
                ctx,
                spell.id,
                db_mod=db_mod,
                queries_mod=queries,
                persistence_mod=persistence,
                resonance_mutations_mod=resonance,
                concentration_mutations_mod=concentration,
                ward_resolution_mod=ward,
                spells_mod=spells,
                character_spells_mod=_known(spell.id),
            )
    if revocation in ("lock", "ward"):
        persistence.update_player_resources.assert_not_awaited()
    if revocation in ("lock", "ward", "focus"):
        resonance.update_player_resonance.assert_not_awaited()
    concentration.update_player_concentration.assert_not_awaited()
    assert ctx.userdata.party.members[1].concentration.spell_id is None


@pytest.mark.parametrize("revocation", ["lock", "scope", "resources"])
async def test_ward_revoked_after_await_refuses_before_its_next_write(revocation):
    ctx = make_context(party_member_ids=["player_2"])
    db_mod, _ = make_db_mod()
    live = True

    def validate(*_):
        if not live:
            raise RuntimeError("stale authenticated actor")

    async def revoke(*_args, **_kwargs):
        nonlocal live
        live = False

    row = {"class": "cleric", "level": 7, "focus": {"current": 10}, "stamina": {"current": 10}}

    async def lock(*_args, **_kwargs):
        if revocation == "lock":
            await revoke()
        return row

    async def scope(*_args, **_kwargs):
        if revocation == "scope":
            await revoke()
        return None

    queries = MagicMock(get_player=AsyncMock(side_effect=lock))
    persistence = MagicMock(
        update_player_resources=AsyncMock(side_effect=revoke if revocation == "resources" else None)
    )
    wards = MagicMock(write_ward=AsyncMock())
    resolution = MagicMock(resolve_scope_ward=AsyncMock(side_effect=scope))
    with ctx.userdata._bind_authenticated_actor("player_2", 4, validate):
        with pytest.raises(RuntimeError, match="stale"):
            await _activate_veil_ward_impl(
                ctx,
                db_mod=db_mod,
                queries_mod=queries,
                persistence_mod=persistence,
                ward_mutations_mod=wards,
                resolution_mod=resolution,
            )
    if revocation != "resources":
        persistence.update_player_resources.assert_not_awaited()
    wards.write_ward.assert_not_awaited()
    assert ctx.userdata.location_ward is None


@pytest.mark.parametrize("revocation", ["lock", "scope", "ward_write"])
async def test_anchor_revoked_after_lock_refuses_before_ward_or_inventory_write(revocation):
    ctx = make_context(party_member_ids=["player_2"])
    db_mod, _ = make_db_mod()
    live = True

    def validate(*_):
        if not live:
            raise RuntimeError("stale authenticated actor")

    async def revoke(*_args, **_kwargs):
        nonlocal live
        live = False

    async def lock(*_args, **_kwargs):
        if revocation == "lock":
            await revoke()
        return {"quantity": 1}

    async def scope(*_args, **_kwargs):
        if revocation == "scope":
            await revoke()
        return None

    queries = MagicMock(get_inventory_item=AsyncMock(side_effect=lock))
    wards = MagicMock(write_ward=AsyncMock(side_effect=revoke if revocation == "ward_write" else None))
    inventory = MagicMock(transact_inventory=AsyncMock())
    resolution = MagicMock(resolve_scope_ward=AsyncMock(side_effect=scope))
    with ctx.userdata._bind_authenticated_actor("player_2", 4, validate):
        with pytest.raises(RuntimeError, match="stale"):
            await _deploy_veil_anchor_impl(
                ctx,
                "veil_ward_anchor_small",
                db_mod=db_mod,
                queries_mod=queries,
                ward_mutations_mod=wards,
                inventory_mutations_mod=inventory,
                resolution_mod=resolution,
            )
    if revocation != "ward_write":
        wards.write_ward.assert_not_awaited()
    inventory.transact_inventory.assert_not_awaited()
    assert ctx.userdata.location_ward is None


async def test_inner_fire_revoked_after_player_lock_refuses_before_mutation():
    ctx, db_mod, _conn, queries, hp, resonance, events, dice, concentration = _fire_fixture()
    live = True

    def validate(*_):
        if not live:
            raise RuntimeError("stale authenticated actor")

    async def lock(*_args, **_kwargs):
        nonlocal live
        live = False
        return {"race": "draethar"}

    queries.get_player.side_effect = lock
    with ctx.userdata._bind_authenticated_actor("player_2", 4, validate):
        with pytest.raises(RuntimeError, match="stale"):
            await _fire(ctx, db_mod, queries, hp, resonance, events, dice, concentration)
    resonance.update_player_resonance.assert_not_awaited()
    hp.update_player_hp.assert_not_awaited()
    assert ctx.userdata.combat_state.get_participant("player_2").hp_current == 20
    assert not ctx.userdata.party.members[1].draethar_inner_fire_used


async def test_in_combat_cast_for_host_on_guest_turn_is_not_speaker_gated():
    from _spell_casting_helpers import _known, _spell

    from spell_casting import _resolve_cast

    ctx = make_context(party_member_ids=["player_2"])
    session = ctx.userdata
    _db_mod, conn = make_db_mod()
    spell = _spell(spell_id="hold_flame", focus_cost=3, resonance=2, concentration=True)
    spells = MagicMock(get_spell=MagicMock(return_value=spell))
    row = {"player_id": "player_1", "class": "mage", "level": 5, "focus": {"current": 10}}
    persistence = MagicMock(update_player_resources=AsyncMock())
    resonance = MagicMock(update_player_resonance=AsyncMock())
    concentration = MagicMock(update_player_concentration=AsyncMock())
    ward = MagicMock(resolve_scope_ward=AsyncMock(return_value=None))
    with session._bind_authenticated_actor("player_2", 4, lambda *_: None):
        result = await _resolve_cast(
            session,
            spell.id,
            conn=conn,
            caster=session.party.primary,
            player=row,
            persistence_mod=persistence,
            resonance_mutations_mod=resonance,
            concentration_mutations_mod=concentration,
            spells_mod=spells,
            ward_resolution_mod=ward,
            character_spells_mod=_known(spell.id),
        )
    persistence.update_player_resources.assert_awaited_once_with("player_1", focus=7, conn=conn)
    assert resonance.update_player_resonance.call_args.args[0] == "player_1"
    concentration.update_player_concentration.assert_awaited_once_with("player_1", spell.id, conn=conn)
    assert result.packet["effect"] == spell.mechanics
