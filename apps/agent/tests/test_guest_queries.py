import json
from unittest.mock import AsyncMock, MagicMock

from sample_fixtures import make_context

from query_tools import _query_abilities_impl, _query_inventory_impl, _query_npc_impl, _query_patron_impl


def guest_context():
    return make_context(party_member_ids=["player_2"])


async def test_guest_inventory_describes_guest_items():
    ctx = guest_context()
    queries = MagicMock(get_player_inventory=AsyncMock(side_effect=lambda pid: [{"name": f"{pid} sword"}]))
    with ctx.userdata._bind_authenticated_actor("player_2", 4, lambda *_: None):
        result = json.loads(await _query_inventory_impl(ctx, queries=queries))
    assert result["items"][0]["name"] == "player_2 sword"
    queries.get_player_inventory.assert_awaited_once_with("player_2")


async def test_guest_abilities_read_guest_class_ownership_spells_and_variant():
    ctx = guest_context()
    queries = MagicMock(get_player=AsyncMock(return_value={"class": "warrior", "level": 8}))
    persistence = MagicMock(
        get_character_abilities=AsyncMock(return_value=[{"ability_id": "warrior_cleaving_blow"}]),
        get_active_variant=AsyncMock(return_value="warrior_cleaving_blow_drathian"),
    )
    library = MagicMock(get_known=AsyncMock(return_value=[]))
    with ctx.userdata._bind_authenticated_actor("player_2", 4, lambda *_: None):
        result = json.loads(
            await _query_abilities_impl(ctx, queries=queries, persistence=persistence, character_spells_mod=library)
        )
    assert any(row.get("active_variant_id") == "warrior_cleaving_blow_drathian" for row in result["abilities"])
    queries.get_player.assert_awaited_once_with("player_2")
    persistence.get_character_abilities.assert_awaited_once_with("player_2")
    library.get_known.assert_awaited_once_with("player_2")
    assert persistence.get_active_variant.await_args.args[0] == "player_2"


async def test_guest_patron_describes_guest_standing():
    ctx = guest_context()
    activities = MagicMock(
        get_divine_favor=AsyncMock(
            side_effect=lambda pid: {"patron": "sentinel", "level": 24 if pid == "player_2" else 0, "max": 61}
        )
    )

    def catalog():
        return [
            {
                "god_id": "sentinel",
                "short_name": "Sentinel",
                "title": "the Boundary",
                "favor_actions": {},
                "layer_1_gift": {"id": "sentinel_gift"},
            }
        ]

    with ctx.userdata._bind_authenticated_actor("player_2", 4, lambda *_: None):
        result = json.loads(await _query_patron_impl(ctx, activities=activities, gods_loader=catalog))
    assert result["level"] == 24
    activities.get_divine_favor.assert_awaited_once_with("player_2")


async def test_guest_npc_disposition_filters_knowledge_for_guest():
    ctx = guest_context()
    queries = MagicMock(
        get_npc_disposition=AsyncMock(side_effect=lambda npc, pid: "unfriendly" if pid == "player_2" else "trusted")
    )
    content = MagicMock(
        get_npc=AsyncMock(
            return_value={
                "name": "Keeper",
                "default_disposition": "neutral",
                "knowledge": {
                    "free": ["hello"],
                    "disposition >= trusted": ["hidden"],
                },
            }
        )
    )
    with ctx.userdata._bind_authenticated_actor("player_2", 4, lambda *_: None):
        result = json.loads(await _query_npc_impl(ctx, "keeper", queries=queries, content=content))
    assert result["disposition"] == "unfriendly"
    assert result["knowledge"] == ["hello"]
    queries.get_npc_disposition.assert_awaited_once_with("keeper", "player_2")
