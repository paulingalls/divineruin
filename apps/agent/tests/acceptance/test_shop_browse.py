import json
from datetime import UTC, datetime
from pathlib import Path

from acceptance.first_episode_harness import episode
from acceptance.merchant_harness import (
    FORGE,
    GRIMJAW,
    SWORD,
    fund_merchant,
    merchant_row,
    merchant_scope,
    merchant_session,
    pool_override,
    rows,
    stock,
)
from livekit.agents import llm

import db
import db_mutations
from creation_rules import build_character_data
from exploration_agent import ExplorationAgent
from merchant_agent import MerchantAgent

BROWSE = "query_merchant_inventory"
POOL = "weapons_armor_basic"
SHELF = {
    "spear_common": 0,
    "handaxe_common": 1,
    "mace_common": 2,
    SWORD: 1,
    "battleaxe_common": 1,
    "longsword_guild": 1,
}


def item(item_id: str, name: str, tier: int, in_stock: bool = True) -> dict:
    return {"item_id": item_id, "name": name, "tier": tier, "in_stock": in_stock}


def result(receipt: llm.FunctionCallOutput) -> dict:
    assert not receipt.is_error, receipt.output
    return json.loads(receipt.output)


async def test_spoken_browse_handoff_reads_persisted_stock(
    livekit_server: dict[str, str], reset_db_pool: str, tmp_path: Path
) -> None:
    async def prepare(pid: str) -> None:
        data = build_character_data("Vale", "human", "warrior", "kaelen", "", created_at=datetime.now(UTC))
        data.update(session_count=7, location_id=FORGE, gold=7)
        await db_mutations.create_player(pid, None, data)
        await db_mutations.set_player_flag(pid, "onboarding_beat", 5)
        await stock(pid, "rope_hemp", 1)

    async with (
        merchant_scope(GRIMJAW),
        episode(livekit_server, tmp_path, prepare=prepare, initial_agent="ExplorationAgent") as run,
    ):
        await fund_merchant(GRIMJAW, 600, current_inventory=SHELF)
        before = await merchant_row(GRIMJAW), await rows(run.player_id)
        utterance = "I want to look at what Grimjaw has."
        run.stt.transcript = utterance
        assert isinstance(run.session.current_agent, ExplorationAgent)
        start = len(run.requests)
        entry = result(await run.turn("enter_mode", mode="trade", encounter_id=""))
        assert entry["status"] == "entered_trade"
        assert isinstance(run.session.current_agent, MerchantAgent)
        npc_id = next(npc["id"] for npc in entry["present_npcs"] if npc["name"] == "Grimjaw")

        assert result(await run.turn(BROWSE, npc_id=npc_id, item_name="")) == {
            "npc_id": GRIMJAW,
            "highlights": [
                item("handaxe_common", "Handaxe", 2),
                item("mace_common", "Mace", 2),
                item(SWORD, "Shortsword", 2),
                item("battleaxe_common", "Battleaxe", 2),
            ],
            "tier_1_summary": None,
        }
        exploration, merchant = [
            next(req for req in run.requests[start:] if verb in {tool.info.name for tool in req["tools"]})
            for verb in ("enter_mode", BROWSE)
        ]
        exploration_tools = {tool.info.name: tool.info for tool in exploration["tools"]}
        assert BROWSE not in exploration_tools
        description = exploration_tools["enter_mode"].description or ""
        assert all(intent in description for intent in ("browse", "buy", "sell"))
        for request in (exploration, merchant):
            assert any(
                message.role == "user" and message.text_content == utterance
                for message in request["chat_ctx"].messages()
            )

        inquiry = "Do you have a Guild Longsword?"
        run.stt.transcript = inquiry
        start = len(run.requests)
        assert result(await run.turn(BROWSE, npc_id=npc_id, item_name="Guild Longsword")) == {
            "npc_id": GRIMJAW,
            **item("longsword_guild", "Guild Longsword", 2),
        }
        assert any(
            message.role == "user" and message.text_content == inquiry
            for request in run.requests[start:]
            for message in request["chat_ctx"].messages()
        )
        assert (await merchant_row(GRIMJAW), await rows(run.player_id)) == before


async def test_browse_tiers_and_spoken_names(reset_db_pool: str) -> None:
    tier_3 = [
        {"item_id": item_id, "settlements": ["town", "city"], "presence_chance": 1, "restock_check": "daily"}
        for item_id in ("plate_armor", "masterwork_spear", "half_plate", "masterwork_light_crossbow")
    ]
    async with (
        pool_override(
            POOL,
            tier_1_items=["rope_hemp", "rations_basic", "enchant_fireproof", "waterskin", "waterskin_full"],
            tier_3_items=tier_3,
        ),
        merchant_session(item="healing_potion_minor", held=1) as sale,
    ):
        await fund_merchant(GRIMJAW, 600, current_inventory={**SHELF, "masterwork_spear": 1, "plate_armor": 1})
        summary = {
            "line": "I carry Hemp Rope, Trail Rations, and other everyday supplies.",
            "items": [
                {"item_id": "rope_hemp", "name": "Hemp Rope"},
                {"item_id": "rations_basic", "name": "Trail Rations"},
            ],
        }
        assert result(await sale.browse(GRIMJAW)) == {
            "npc_id": GRIMJAW,
            "highlights": [
                item("plate_armor", "Plate Armor", 3),
                item("masterwork_spear", "Masterwork Spear", 3),
                item("handaxe_common", "Handaxe", 2),
                item("mace_common", "Mace", 2),
            ],
            "tier_1_summary": summary,
        }
        for query, expected in [
            ("  hEMP   ROPE  ", item("rope_hemp", "Hemp Rope", 1)),
            ("rope", item("rope_hemp", "Hemp Rope", 1)),
            ("iron shields", item("shield_iron", "Iron Shield", 2, False)),
            ("waxes", item("enchant_fireproof", "Fireproofing Wax", 1)),
            ("short sword", item(SWORD, "Shortsword", 2)),
            ("  sPeAr  ", item("spear_common", "Spear", 2, False)),
            ("  liGHT   crossBow  ", item("crossbow_light", "Light Crossbow", 2, False)),
            ("masterwork-spear", item("masterwork_spear", "Masterwork Spear", 3)),
            ("half plate", item("half_plate", "Half Plate", 3, False)),
        ]:
            assert result(await sale.browse(GRIMJAW, query)) == {"npc_id": GRIMJAW, **expected}, query
        for query, refusal in [
            ("sword", ("Shortsword", "Guild Longsword")),
            ("Waterskin", ("Waterskin (waterskin)", "Waterskin (waterskin_full)")),
            ("Healing Potion (Minor)", ("doesn't carry", "Healing Potion (Minor)")),
            ("...?", ("doesn't carry", "...?")),
        ]:
            response = await sale.browse(GRIMJAW, query)
            assert response.is_error, response.output
            assert all(part in response.output for part in refusal), response.output

        pool = await db.get_pool()
        await pool.execute(
            "UPDATE merchant_state SET data=jsonb_set(data, '{current_inventory}', '{}') WHERE npc_id=$1", GRIMJAW
        )
        assert result(await sale.browse(GRIMJAW)) == {
            "npc_id": GRIMJAW,
            "highlights": [],
            "tier_1_summary": summary,
        }
        assert result(await sale.browse(GRIMJAW, "Spear")) == {
            "npc_id": GRIMJAW,
            **item("spear_common", "Spear", 2, False),
        }
