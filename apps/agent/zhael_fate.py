"""Session-held d20 choice and durable Fate's Thread spend."""

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, TypeVar
from uuid import uuid4

from livekit.agents.llm import ToolError

import db
import db_queries
from _gods_content import load_gods
from patron_ability_tools import spent_state

if TYPE_CHECKING:
    from session_data import SessionData

FATE = "zhael_fates_thread"
# LiveKit folds a nullable multi-value Literal into an enum containing null, which strict schemas reject.
Keep = Literal["original"] | Literal["reroll"]


@dataclass(frozen=True)
class Resumed:
    facts: dict
    paused: bool = False


@dataclass
class FateOffer:
    id: str
    kind: str
    roller_id: str
    die: int
    total: int
    followers: tuple[str, ...]
    reroll: Callable[[], tuple[int, int, Callable[[], Awaitable[Resumed]]]]
    original: Callable[[], Awaitable[Resumed]]
    accepted_by: str | None = None
    rerolled: tuple[int, int, Callable[[], Awaitable[Resumed]]] | None = None

    def response(self) -> dict:
        return {
            "fate_offer": {
                "offer_id": self.id,
                "roll_kind": self.kind,
                "roller_id": self.roller_id,
                "die": self.die,
                "total": self.total,
                "eligible_followers": self.followers,
            },
            "dm_cue": (
                "Tell the eligible followers the die and total. Voice the Fate's Thread offer and wait for their answer. "
                "Any other tool call, including query_info, lets the original stand."
            ),
        }


def availability(player: dict, gift: dict) -> dict:
    spent = spent_state(player, FATE)["spent"]
    active = gift["status"] == "active" and gift.get("resolution") == "engine"
    return {"available": active and not spent, "spent": spent}


def _eligible(player: dict) -> bool:
    if (player.get("divine_favor") or {}).get("patron") != "zhael":
        return False
    gift = next(god["layer_1_gift"] for god in load_gods() if god["god_id"] == "zhael")
    return availability(player, gift)["available"]


async def eligible_followers(
    session: SessionData, *, queries=db_queries, conn=None, roller: tuple[str, dict] | None = None
) -> tuple[str, ...]:
    if not session.fate_lock.locked():
        return ()
    followers = []
    for player_id in session.present_member_ids:
        if roller is not None and player_id == roller[0]:
            player = roller[1]
        else:
            player = await (queries.get_player(player_id) if conn is None else queries.get_player(player_id, conn=conn))
        if player is not None and _eligible(player):
            followers.append(player_id)
    return tuple(followers)


T = TypeVar("T")


def make_offer(
    kind: str,
    roller_id: str,
    original: T,
    followers: tuple[str, ...],
    *,
    numbers: Callable[[T], tuple[int, int]],
    reroll: Callable[[], T],
    resume: Callable[[T], Awaitable[Resumed]],
) -> FateOffer:
    die, total = numbers(original)

    def show_reroll():
        rolled = reroll()
        die, total = numbers(rolled)
        return die, total, lambda: resume(rolled)

    return FateOffer(uuid4().hex, kind, roller_id, die, total, followers, show_reroll, lambda: resume(original))


def effects_committed(session: SessionData) -> None:
    """Retire the executing offer before post-commit publication can fail."""
    session.fate_offer = None


def cancel(session: SessionData, reason: str) -> Resumed:
    effects_committed(session)
    return Resumed({"outcome": "cancelled", "reason": reason})


async def settle(session: SessionData, keep: Keep = "original") -> Resumed:
    offer = session.fate_offer
    assert offer is not None
    apply = offer.original
    if keep == "reroll":
        if offer.rerolled is None:
            raise ToolError("Fate's Thread has not rolled a second die.")
        apply = offer.rerolled[2]
    result = await apply()
    if session.fate_offer is offer:
        session.fate_offer = None
    return result


async def activate(session: SessionData, offer_id: str | None, keep: Keep | None) -> str:
    offer = session.fate_offer
    if not offer_id or offer is None or offer_id != offer.id:
        raise ToolError("Supply the current Fate's Thread offer_id.")
    try:
        actor = (
            session.acting_player_id
            if session.multiplayer_owner is None
            else session.require_reaction_actor().player_id
        )
    except (RuntimeError, ValueError) as exc:
        raise ToolError(str(exc)) from exc
    if offer.accepted_by is not None and (actor != offer.accepted_by or keep is None):
        raise ToolError(f"Fate's Thread was taken by {offer.accepted_by}.")
    if actor not in offer.followers or actor not in session.present_member_ids:
        raise ToolError("This player is ineligible for the Fate's Thread offer.")
    if keep is not None:
        if keep not in ("original", "reroll"):
            raise ToolError("Keep must be original or reroll.")
        return json.dumps((await settle(session, keep)).facts)

    from patron_gift_tools import write_state

    async with db.transaction() as conn:
        player = await db_queries.get_player(actor, conn=conn, for_update=True)
        if player is None or not _eligible(player):
            raise ToolError("Fate's Thread is unavailable or spent.")
        try:
            session.validate_acting_player(actor)
        except (RuntimeError, ValueError) as exc:
            raise ToolError(str(exc)) from exc
        candidate = offer.reroll()
        await write_state(actor, {"spent": True}, gift_id=FATE, conn=conn)
    offer.accepted_by, offer.rerolled = actor, candidate
    return json.dumps(
        {
            "offer_id": offer.id,
            "original": {"die": offer.die, "total": offer.total},
            "reroll": {"die": candidate[0], "total": candidate[1]},
            "dm_cue": "Voice both Fate's Thread results and wait for the follower to keep one. "
            "Any other tool call lets the original stand. The gift stays spent.",
        }
    )
