"""Session-held d20 choices and durable Zhael spends."""

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, TypeVar
from uuid import uuid4

from livekit.agents.llm import ToolError

import db
import db_queries
from _gods_content import load_gods
from patron_ability_tools import LUCKY, lucky_ready, spend, spent_state

if TYPE_CHECKING:
    from session_data import SessionData

FATE = "zhael_fates_thread"
ROLL_ABILITIES = (FATE, LUCKY)
# LiveKit folds a nullable multi-value Literal into an enum containing null, which strict schemas reject.
Keep = Literal["original"] | Literal["reroll"]


@dataclass(frozen=True)
class Resumed:
    facts: dict
    paused: bool = False
    handoff: tuple | None = None

    def tool_result(self) -> str | tuple:
        return self.handoff if self.handoff is not None else json.dumps(self.facts)


@dataclass(frozen=True)
class Candidates:
    fate: tuple[str, ...] = ()
    lucky: tuple[str, ...] = ()

    def choices(self, roller_id: str, die: int | None = None) -> dict[str, tuple[str, ...]]:
        abilities = {}
        if self.fate:
            abilities[FATE] = self.fate
        if roller_id in self.lucky and (die is None or die in (1, 20)):
            abilities[LUCKY] = (roller_id,)
        return abilities


@dataclass
class FateOffer:
    id: str
    kind: str
    roller_id: str
    die: int
    total: int
    abilities: dict[str, tuple[str, ...]]
    reroll: Callable[[], tuple[int, int, Callable[[], Awaitable[Resumed]]]]
    original: Callable[[], Awaitable[Resumed]]
    flip: Callable[[int], Callable[[], Awaitable[Resumed]]]
    accepted_flip: Callable[[], Awaitable[Resumed]] | None = None
    accepted_by: str | None = None
    rerolled: tuple[int, int, Callable[[], Awaitable[Resumed]]] | None = None

    def response(self) -> dict:
        followers = tuple(dict.fromkeys(actor for actors in self.abilities.values() for actor in actors))
        return {
            "fate_offer": {
                "offer_id": self.id,
                "roll_kind": self.kind,
                "roller_id": self.roller_id,
                "die": self.die,
                "total": self.total,
                "eligible_followers": followers,
                "abilities": [
                    {"id": ability_id, "eligible_followers": actors} for ability_id, actors in self.abilities.items()
                ],
            },
            "dm_cue": (
                "Tell the eligible followers the die and total. Voice the listed choices and wait for their answer. "
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


async def candidates(
    session: SessionData, *, queries=db_queries, conn=None, roller: tuple[str, dict] | None = None
) -> Candidates:
    if not session.fate_lock.locked():
        return Candidates()
    patron = next(god for god in load_gods() if god["god_id"] == "zhael")
    lucky = patron["layer_3_tier_abilities"]["acknowledged"]
    fate_followers = []
    lucky_followers = []
    for player_id in session.present_member_ids:
        if roller is not None and player_id == roller[0]:
            player = roller[1]
        else:
            player = await (queries.get_player(player_id) if conn is None else queries.get_player(player_id, conn=conn))
        if player is not None and (player.get("divine_favor") or {}).get("patron") == "zhael":
            if availability(player, patron["layer_1_gift"])["available"]:
                fate_followers.append(player_id)
            if lucky_ready(player, lucky):
                lucky_followers.append(player_id)
    return Candidates(tuple(fate_followers), tuple(lucky_followers))


T = TypeVar("T")


def make_offer(
    kind: str,
    roller_id: str,
    original: T,
    candidates: Candidates,
    *,
    numbers: Callable[[T], tuple[int, int]],
    reroll: Callable[[], T],
    flip: Callable[[int], T],
    resume: Callable[[T], Awaitable[Resumed]],
) -> FateOffer | None:
    die, total = numbers(original)
    abilities = candidates.choices(roller_id, die)
    if not abilities:
        return None

    def show_reroll():
        rolled = reroll()
        die, total = numbers(rolled)
        return die, total, lambda: resume(rolled)

    def replace_face(face: int):
        result = flip(face)
        return lambda: resume(result)

    return FateOffer(
        uuid4().hex, kind, roller_id, die, total, abilities, show_reroll, lambda: resume(original), replace_face
    )


def effects_committed(session: SessionData) -> None:
    """Retire the executing offer before post-commit publication can fail."""
    session.fate_offer = None


def cancel(session: SessionData, reason: str) -> Resumed:
    effects_committed(session)
    return Resumed({"outcome": "cancelled", "reason": reason})


async def settle(session: SessionData, keep: Keep = "original") -> Resumed:
    offer = session.fate_offer
    assert offer is not None
    apply = offer.accepted_flip or offer.original
    if keep == "reroll":
        if offer.rerolled is None:
            raise ToolError("Fate's Thread has not rolled a second die.")
        apply = offer.rerolled[2]
    result = await apply()
    if session.fate_offer is offer:
        session.fate_offer = None
    return result


async def activate(session: SessionData, ability_id: str, offer_id: str | None, keep: Keep | None) -> str | tuple:
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
    if offer.accepted_by is not None and (
        offer.accepted_flip is not None or ability_id == LUCKY or actor != offer.accepted_by or keep is None
    ):
        raise ToolError(f"This roll offer was taken by {offer.accepted_by}.")
    if actor not in offer.abilities.get(ability_id, ()) or actor not in session.present_member_ids:
        raise ToolError("This player is ineligible for that Fate's Thread offer choice.")
    if ability_id == LUCKY:
        if keep is not None:
            raise ToolError("Lucky resolves immediately and does not take keep.")
        return await _activate_lucky(session, actor, offer)
    if keep is not None:
        if keep not in ("original", "reroll"):
            raise ToolError("Keep must be original or reroll.")
        return (await settle(session, keep)).tool_result()

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


async def _activate_lucky(session: SessionData, actor: str, offer: FateOffer) -> str | tuple:
    from patron_ability_events import publish_patron_abilities

    flipped = offer.flip(21 - offer.die)
    await spend(session, actor, LUCKY)
    offer.accepted_by, offer.accepted_flip = actor, flipped
    await publish_patron_abilities(session.room, actor, session.event_bus)
    return (await settle(session)).tool_result()
