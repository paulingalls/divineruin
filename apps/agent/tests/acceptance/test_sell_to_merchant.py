import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from acceptance.first_episode_harness import episode, until
from acceptance.merchant_harness import FORGE, GRIMJAW, SWORD, merchant_session, rows, stock
from acceptance.seeds import seed_gold
from livekit.agents import llm
from livekit.agents.llm.utils import prepare_function_arguments
from livekit.agents.voice import RunContext

import db
import db_content_queries
import db_mutations
import db_queries
import event_types as E
import pricing_queries
import sale_pricing
from creation_rules import build_character_data
from exploration_agent import ExplorationAgent
from session_data import SessionData


@pytest.mark.parametrize(
    "setup,unit,total",
    [
        pytest.param({}, 50, 100, id="neutral"),
        pytest.param({"disposition": "friendly", "held": 3}, 55, 110, id="friendly"),
        pytest.param({"disposition": "unfriendly", "tainted": 1, "guest": True}, 45, 90, id="unfriendly-guest"),
        pytest.param(
            {"disposition": None, "npc": "innkeeper_maren", "location": "millhaven_inn"},
            45,
            90,
            id="maren-default",
        ),
    ],
)
async def test_sale_commits_receipt_and_snapshots(
    reset_db_pool: str, setup: dict[str, Any], unit: int, total: int
) -> None:
    npc = setup.get("npc", GRIMJAW)
    guest = setup.get("guest", False)
    async with merchant_session(**setup) as sale:
        await stock(sale.player_id, "healing_potion", 1)
        if guest:
            await stock(sale.primary_id, SWORD, 2)
            primary_before = await rows(sale.primary_id)
        before_player, before_inventory = await rows(sale.player_id)

        receipt = await sale.sell(SWORD, npc, 2)

        after_player, after_inventory = await rows(sale.player_id)
        assert after_player["gold"] == before_player["gold"] + total / 10
        if before_inventory[(SWORD, False)]["quantity"] == 2:
            del before_inventory[(SWORD, False)]
        else:
            before_inventory[(SWORD, False)]["quantity"] -= 2
        assert after_inventory == before_inventory
        if guest:
            assert await rows(sale.primary_id) == primary_before
        assert not receipt.is_error, receipt.output
        assert json.loads(receipt.output) == {
            "item_id": SWORD,
            "npc_id": npc,
            "quantity": 2,
            "unit_price_sp": unit,
            "total_price_sp": total,
        }
        snapshot = await db_queries.get_inventory_snapshot(sale.player_id)
        assert snapshot["player_id"] == sale.player_id
        assert isinstance(snapshot["inventory_revision"], str)
        assert int(snapshot["inventory_revision"]) > int(before_player["inventory_revision"])
        assert sale.publications == [
            (
                {
                    "type": E.CURRENCY_GAINED,
                    "player_id": sale.player_id,
                    "amount": total / 10,
                    "currency": "gold",
                    "source": "sale",
                    "new_balance": after_player["gold"],
                },
                (after_player, after_inventory),
            ),
            ({"type": E.INVENTORY_UPDATED, **snapshot}, (after_player, after_inventory)),
        ]


async def test_fractional_sale_preserves_exact_gold(reset_db_pool: str) -> None:
    async with merchant_session(item="club_wooden", held=1) as sale:
        pool = await db.get_pool()
        await seed_gold(pool, sale.player_id, 7.6)

        receipt = await sale.sell("club_wooden", GRIMJAW, 1)

        assert not receipt.is_error, receipt.output
        player, _ = await rows(sale.player_id)
        assert player["gold"] == 7.9
        assert sale.publications[0][0]["new_balance"] == 7.9


@pytest.mark.parametrize(
    "overrides,reason,quantity",
    [
        pytest.param({"disposition": "hostile"}, "hostile", 1, id="hostile"),
        pytest.param({"item": "healing_potion"}, "temple", 1, id="wrong_type"),
        pytest.param(
            {"npc": "innkeeper_maren", "location": "millhaven_inn", "item": "quality_longsword"},
            "blacksmith",
            1,
            id="wrong_rarity",
        ),
        pytest.param({"location": "millhaven_inn"}, "isn't here", 1, id="absent"),
        pytest.param({"npc": "mentor_keldaran_forgemaster"}, "doesn't buy", 1, id="no_pool"),
        pytest.param({}, "at least one", -1, id="negative_quantity"),
        pytest.param({"held": 1}, "only carry 1", 2, id="insufficient"),
        pytest.param({"held": 0}, "aren't carrying", 1, id="missing"),
        pytest.param({"equipped": True}, "equipped", 1, id="equipped"),
        pytest.param({"held": 0, "tainted": 2}, "tainted", 1, id="tainted"),
        pytest.param(
            {"npc": "innkeeper_maren", "location": "millhaven_inn", "item": "guild_contract_greyvale"},
            "quest item",
            1,
            id="quest_type",
        ),
        pytest.param({"item": "thornridges_stand"}, "quest item", 1, id="quest_flag"),
    ],
)
async def test_refusal_preserves_rows(
    reset_db_pool: str, overrides: dict[str, Any], reason: str, quantity: int
) -> None:
    async with merchant_session(**overrides) as sale:
        before = await rows(sale.player_id)
        receipt = await sale.sell(overrides.get("item", SWORD), overrides.get("npc", GRIMJAW), quantity)
        assert await rows(sale.player_id) == before
        assert not sale.publications
        assert receipt.is_error and reason in receipt.output, receipt.output


def registered_sale() -> llm.FunctionTool:
    from merchant_agent import MerchantAgent

    tool = next(t for t in MerchantAgent().tools if isinstance(t, llm.FunctionTool) and t.info.name == "sell_item")
    return tool


def test_sale_schema_has_only_ids_and_quantity() -> None:
    (schema,) = llm.ToolContext([registered_sale()]).parse_function_tools("openai", strict=True)
    params = schema["function"]["parameters"]
    assert set(params["properties"]) == set(params["required"]) == {"item_id", "npc_id", "quantity"}
    assert params["properties"]["quantity"]["type"] == "integer"
    assert params["additionalProperties"] is False


@pytest.mark.parametrize("quantity", [0, -1, True, 1.0, 1.5, "2", None])
async def test_invalid_quantity_reads_nothing(monkeypatch: pytest.MonkeyPatch, quantity: object) -> None:
    def unexpected_io(*_args: object, **_kwargs: object) -> None:
        pytest.fail("invalid quantity reached a sale read or transaction")

    for mod, name in (
        (db, "transaction"),
        (db, "get_pool"),
        (db_queries, "get_npcs_at_location"),
        (db_queries, "get_player"),
        (db_queries, "get_inventory_item"),
        (db_content_queries, "get_npc"),
        (db_content_queries, "get_item"),
        (sale_pricing, "get_inventory_pools"),
        (pricing_queries, "get_economy_pricing"),
    ):
        monkeypatch.setattr(mod, name, unexpected_io)
    tool = registered_sale()
    context = MagicMock(spec=RunContext)
    context.userdata = SessionData(player_id="seller", location_id=FORGE)
    with pytest.raises(llm.ToolError):
        args, kwargs = prepare_function_arguments(
            fnc=tool,
            json_arguments=json.dumps({"item_id": SWORD, "npc_id": GRIMJAW, "quantity": quantity}),
            call_ctx=context,
        )
        await tool(*args, **kwargs)


async def test_spoken_sell_handoff_and_return(
    livekit_server: dict[str, str], reset_db_pool: str, tmp_path: Path
) -> None:
    from merchant_agent import MerchantAgent

    async def prepare(pid: str) -> None:
        data = build_character_data("Vale", "human", "warrior", "kaelen", "", created_at=datetime.now(UTC))
        data.update(session_count=7, location_id=FORGE, gold=7)
        await db_mutations.create_player(pid, None, data)
        await db_mutations.set_player_flag(pid, "onboarding_beat", 5)
        await db_mutations.set_npc_disposition(GRIMJAW, pid, "neutral", "fixture")
        await stock(pid, SWORD, 2)

    async with episode(livekit_server, tmp_path, prepare=prepare, initial_agent="ExplorationAgent") as run:
        utterance = "I want to sell my two shortswords to Grimjaw."
        run.stt.transcript = utterance
        caller = run.session.current_agent
        assert isinstance(caller, ExplorationAgent)
        region = caller._agent_type
        start = len(run.requests)
        entry = await run.turn("enter_mode", mode="trade", encounter_id="")
        assert not entry.is_error, entry.output
        assert json.loads(entry.output)["status"] == "entered_trade"
        assert isinstance(run.session.current_agent, MerchantAgent)
        assert run.session.userdata.pre_trade_agent_type == region
        run.stt.transcript = "What am I carrying?"
        inventory = await run.turn("query_info", kind="inventory")
        exploration, merchant = [
            next(req for req in run.requests[start:] if verb in {tool.info.name for tool in req["tools"]})
            for verb in ("enter_mode", "sell_item")
        ]
        for request in (exploration, merchant):
            assert any(
                message.text_content == utterance
                for message in request["chat_ctx"].messages()
                if message.role == "user"
            )
        present = next(
            message.text_content
            for message in merchant["chat_ctx"].messages()
            if (message.text_content or "").startswith("Present NPCs at ")
        )
        npc_id = next(npc["id"] for npc in json.loads(present.split("\n", 1)[1]) if npc["name"] == "Grimjaw")
        assert npc_id == GRIMJAW

        item_id = next(item["id"] for item in json.loads(inventory.output)["items"] if item["id"] == SWORD)
        run.stt.transcript = "Yes, sell them."
        sold = await run.turn("sell_item", item_id=item_id, npc_id=npc_id, quantity=2)
        assert not sold.is_error and json.loads(sold.output)["total_price_sp"] == 100, sold.output
        player, inventory = await rows(run.player_id)
        assert (SWORD, False) not in inventory and player["gold"] == 17
        await until(lambda: run.packets(E.CURRENCY_GAINED) and run.packets(E.INVENTORY_UPDATED))
        assert run.packets(E.CURRENCY_GAINED)[-1]["new_balance"] == 17
        assert not any(item["id"] == SWORD for item in run.packets(E.INVENTORY_UPDATED)[-1]["inventory"])
        assert [
            p["sound_name"]
            for p in run.packets(E.PLAY_SOUND)
            if p["sound_name"] in {"action_enter_mode_trade", "action_sell_item"}
        ] == ["action_enter_mode_trade", "action_sell_item"]

        run.stt.transcript = "I'm done trading."
        exit_ = await run.turn("conclude_trade")
        assert not exit_.is_error and json.loads(exit_.output)["status"] == "concluded_trade", exit_.output
        agent = run.session.current_agent
        assert isinstance(agent, ExplorationAgent)
        assert (agent._agent_type, agent._initial_location) == (region, FORGE)
        assert run.session.userdata.pre_trade_agent_type is None
        run.stt.transcript = "Where are we?"
        assert not (await run.turn("query_info", kind="location", target_id=FORGE)).is_error
