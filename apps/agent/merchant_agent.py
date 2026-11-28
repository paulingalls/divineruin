from livekit.agents.llm import ChatContext

from base_agent import BaseGameAgent
from merchant_tools import collect_consignment, conclude_trade, query_merchant_ledger
from mode_prompts import MERCHANT_SYSTEM_PROMPT
from query_tools import query_info
from sell_item import sell_item

MERCHANT_TOOLS = [sell_item, query_info, query_merchant_ledger, collect_consignment, conclude_trade]


class MerchantAgent(BaseGameAgent):
    """Guide the player through a sale to a present merchant."""

    def __init__(self, chat_ctx: ChatContext | None = None) -> None:
        super().__init__(instructions=MERCHANT_SYSTEM_PROMPT, tools=MERCHANT_TOOLS, chat_ctx=chat_ctx)
