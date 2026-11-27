"""Consignment records and their day-based settlement terms."""

from decimal import Decimal
from typing import Annotated
from uuid import uuid4

from pydantic import Field, TypeAdapter
from typing_extensions import TypedDict

from dice import roll

COLLECTION_DAYS = 7
OFFER_PREFIX = "consignment:"


class Consignment(TypedDict):
    consignment_id: Annotated[str, Field(min_length=1)]
    consignor_id: Annotated[str, Field(min_length=1)]
    item_id: Annotated[str, Field(min_length=1)]
    quantity: Annotated[int, Field(gt=0)]
    sale_day: int
    full_price_sp: Annotated[int, Field(gt=0)]


_ledger = TypeAdapter(list[Consignment])


def read_ledger(raw: object) -> list[Consignment]:
    entries = _ledger.validate_python(raw, strict=True, extra="forbid")
    if len({entry["consignment_id"] for entry in entries}) != len(entries):
        raise ValueError("Duplicate consignment ID in merchant ledger")
    return entries


def place(player_id: str, item_id: str, quantity: int, full_price_sp: int, today: int) -> Consignment:
    return Consignment(
        consignment_id=uuid4().hex,
        consignor_id=player_id,
        item_id=item_id,
        quantity=quantity,
        full_price_sp=full_price_sp,
        sale_day=today + roll("1d4").total,
    )


def expires_on(entry: Consignment) -> int:
    return entry["sale_day"] + COLLECTION_DAYS


def proceeds_sp(entry: Consignment) -> Decimal:
    return Decimal(entry["full_price_sp"]) * Decimal("0.9")
