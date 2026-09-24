import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from combat.test_deescalation_orchestration import _decl, _make_group_state
from sample_fixtures import FixedRng as ToolRng
from sample_fixtures import make_context, make_db_mod

import check_resolution
from _gods_content import load_gods
from check_discovery import _check_discover_impl
from check_tools import _check_skill_impl
from combat_deescalation import _resolve_deescalation_packet
from gathering_tools import _check_gather_impl
from participant_lifecycle import PartyLifecycle
from party_state import PartyMember
from session_data import CompanionState, SessionData
from session_startup import GameplayInputOwner
from social_tools import _check_social_impl
from tools._discover_fixtures import _roll
from travel_tools import _travel_impl


def player(patron):
    return {"attributes": {"strength": 12}, "level": 3, "divine_favor": {"patron": patron}}


def test_bond_uses_content_amount_only_with_an_ally(monkeypatch):
    solo = check_resolution._resolve_skill_check_impl(
        player("aelora"), "athletics", 13, ToolRng(10), ally_present=False
    )
    together = check_resolution._resolve_skill_check_impl(
        player("aelora"), "athletics", 13, ToolRng(10), ally_present=True
    )
    assert together.total - solo.total == 1
    assert together.gift_name == "Hearthkeeper's Bond"
    assert solo.gift_name is None
    for patron in ("veythar", None):
        other = check_resolution._resolve_skill_check_impl(
            player(patron), "athletics", 13, ToolRng(10), ally_present=True
        )
        assert other.total == solo.total
        assert other.gift_name is None

    rows = copy.deepcopy(load_gods())
    next(row for row in rows if row["god_id"] == "aelora")["layer_1_gift"]["mechanics"]["amount"] = 2
    monkeypatch.setattr(check_resolution, "load_gods", lambda: rows)
    stronger = check_resolution._resolve_skill_check_impl(
        player("aelora"), "athletics", 13, ToolRng(10), ally_present=True
    )
    assert stronger.total - solo.total == 2


def test_beyond_tier_check_does_not_name_unapplied_bond():
    result = check_resolution._resolve_skill_check_impl(
        player("aelora"), "athletics", 28, ToolRng(10), ally_present=True
    )
    assert result.gift_name is None


@pytest.mark.parametrize(
    "resolver,args",
    [
        (check_resolution._resolve_skill_check_impl, (player("aelora"), "athletics", 13)),
        (check_resolution.resolve_skill_check, (player("aelora"), "athletics", "moderate")),
        (check_resolution.resolve_skill_check_dc, (player("aelora"), "athletics", 13)),
    ],
)
def test_ally_keyword_is_required(resolver, args):
    with pytest.raises(TypeError, match="ally_present"):
        resolver(*args)


@pytest.mark.asyncio
async def test_ally_presence_tracks_live_roster_and_present_companion():
    session = SessionData(player_id="host", location_id="hall")
    room = MagicMock()
    room.remote_participants = {}
    handlers = {}
    room.on.side_effect = lambda event, handler: handlers.setdefault(event, handler)
    queries = MagicMock(get_player=AsyncMock(return_value={"player_id": "guest"}))
    resonance = MagicMock(
        read_player_resonance=AsyncMock(return_value={"current": 0, "flickering_bonus": 0, "state": "stable"})
    )
    concentration = MagicMock(read_player_concentration=AsyncMock(return_value={"spell_id": None}))
    lifecycle = PartyLifecycle(room, session, queries=queries, resonance_mod=resonance, concentration_mod=concentration)
    session.multiplayer_owner = GameplayInputOwner(lifecycle=lifecycle, transcriber=MagicMock(), input=MagicMock())
    assert not session.ally_present_for("host")
    session.companion = CompanionState(id="companion", name="Companion", is_present=False)
    assert not session.ally_present_for("host")
    session.companion.is_present = True
    assert session.ally_present_for("host")
    session.companion = None
    guest = SimpleNamespace(identity="guest")
    handlers["participant_connected"](guest)
    await lifecycle.authorize("guest")
    assert session.ally_present_for("host")
    assert not session.ally_present_for("guest")
    handlers["participant_disconnected"](guest)
    assert session.party.contains("guest")
    assert not session.ally_present_for("host")
    host = SimpleNamespace(identity="host")
    handlers["participant_connected"](host)
    assert session.ally_present_for("guest")
    await lifecycle.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("producer", ["skill", "discover_empty", "discover_candidate", "gather", "social", "travel"])
async def test_tool_response_names_bond_only_with_present_ally(producer):
    async def invoke(present):
        ctx = make_context(companion_id="ally" if present else None)
        if present == "absent":
            ctx.userdata.companion.is_present = False
        ctx.userdata.event_bus = MagicMock()
        row = {**player("aelora"), "player_id": "player_1", "flags": {}}
        queries = MagicMock(get_player=AsyncMock(return_value=row))
        mutations = MagicMock(
            update_skill_advancement=AsyncMock(),
            set_player_flag=AsyncMock(),
            set_npc_disposition=AsyncMock(),
            add_inventory_item=AsyncMock(),
            update_player_location=AsyncMock(),
            upsert_map_progress=AsyncMock(),
        )
        db_mod, _ = make_db_mod()
        if producer == "skill":
            queries.get_single_skill_advancement = AsyncMock(
                return_value={"tier": "untrained", "use_counter": 0, "narrative_moment_ready": False}
            )
            with patch("check_resolution.dice_roll", return_value=_roll(10)):
                raw = await _check_skill_impl(
                    ctx, "athletics", "moderate", "climb", queries=queries, mutations=mutations
                )
        elif producer.startswith("discover"):
            hidden = (
                []
                if producer == "discover_empty"
                else [{"id": "secret", "discover_skill": "perception", "dc": 18, "description": "Door"}]
            )
            content = MagicMock(get_location=AsyncMock(return_value={"hidden_elements": hidden}))
            with patch("check_resolution.dice_roll", return_value=_roll(2)):
                raw = await _check_discover_impl(
                    ctx, "perception", "wall", content=content, queries=queries, mutations=mutations
                )
        elif producer == "gather":
            content = MagicMock(
                get_location=AsyncMock(return_value={"region": "greyvale", "resource_table": {"common": ["herb"]}}),
                get_gathering_nodes_at_location=AsyncMock(return_value=[]),
                get_material_definition=AsyncMock(return_value={"name": "Herb"}),
            )
            raw = await _check_gather_impl(
                ctx, "", queries=queries, mutations=mutations, content=content, db_mod=db_mod, rng=ToolRng(10)
            )
        elif producer == "social":
            queries.get_npc_disposition = AsyncMock(return_value="neutral")
            content = MagicMock(get_npc=AsyncMock(return_value={"default_disposition": "neutral"}))
            raw = await _check_social_impl(
                ctx,
                "merchant",
                "persuasion",
                "moderate",
                queries=queries,
                mutations=mutations,
                content=content,
                rng=ToolRng(10),
            )
        else:
            ctx.userdata.location_id = "hall"
            content = MagicMock(get_location=AsyncMock(return_value={"id": "dest", "terrain": "dense_forest"}))
            travel_mutations = MagicMock(update_player_travel_state=AsyncMock())
            raw = await _travel_impl(
                ctx,
                "dest",
                "compressed",
                queries=queries,
                mutations=mutations,
                travel_mutations=travel_mutations,
                content=content,
                db_mod=db_mod,
                rng=ToolRng(2),
            )
        return json.loads(raw)

    with_ally = await invoke(True)
    alone = await invoke(False)
    absent_companion = await invoke("absent")
    assert with_ally["gift_name"] == "Hearthkeeper's Bond"
    assert "gift_name" not in alone
    assert "gift_name" not in absent_companion
    assert with_ally["total"] - alone["total"] == 1
    assert absent_companion["total"] == alone["total"]


@pytest.mark.asyncio
async def test_guest_deescalation_uses_guest_presence_when_host_drops():
    session = SessionData(player_id="host", location_id="hall")
    session.event_bus = MagicMock()
    session.party.members.append(
        PartyMember(
            player_id="guest",
            resonance=session.party.primary.resonance,
            concentration=session.party.primary.concentration,
        )
    )
    room = MagicMock(remote_participants={})
    handlers = {}
    room.on.side_effect = lambda event, handler: handlers.setdefault(event, handler)
    lifecycle = PartyLifecycle(
        room, session, queries=MagicMock(), resonance_mod=MagicMock(), concentration_mod=MagicMock()
    )
    session.multiplayer_owner = GameplayInputOwner(lifecycle=lifecycle, transcriber=MagicMock(), input=MagicMock())
    host = SimpleNamespace(identity="host")
    handlers["participant_connected"](host)
    persistence = MagicMock(update_player_resources=AsyncMock())

    async def invoke():
        state = _make_group_state()
        state.participants[0].id = "guest"
        return await _resolve_deescalation_packet(
            session,
            state.participants[0],
            _decl(),
            state=state,
            conn=None,
            player={**player("aelora"), "focus": {"current": 20}},
            persistence=persistence,
            rng=ToolRng(10),
        )

    assert (await invoke())["gift_name"] == "Hearthkeeper's Bond"
    handlers["participant_disconnected"](host)
    assert "gift_name" not in await invoke()
    await lifecycle.aclose()
