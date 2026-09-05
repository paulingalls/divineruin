"""Crafting agent tools (story-004, M5.2).

As of M26 (story-003) these are ``_*_impl`` helpers, no longer registered
``@function_tool``s: ``query_available_workspaces`` / ``rent_workspace`` /
``start_crafting_project`` are reached via ``query_info(kind="workspaces")`` and
``begin_activity(kind="workspace"|"crafting")`` on DispatchAgent.

`query_available_workspaces` (read-only) reports the workspaces a player can use at
their current location plus daily rental quotes. `rent_workspace` (mutating) prices a
rental by the NPC's disposition, debits the player's gold (interim 10sp=1gp until the
economy milestone), and writes a workspace_rentals row. `start_crafting_project` runs
the five-check pre-flight, then allocates+consumes materials and creates the in_progress
crafting activity (the outcome is rolled later at resolution, not here).

Errors raise LiveKit `ToolError` (ADR 0002). The `_*_impl` helpers expose `*_mod=` /
`now_fn=` keyword seams for TEST-ONLY injection; production callers use the
`@function_tool` wrappers. Settlement-by-size availability gates ONLY the
`forge_laboratory` bundle, whose spec cell names the settlement ("city with both, or
Keldaran hold"): `_bundle_refusal` maps the location's `settlement_tier` onto a
SettlementSize, and BOTH the quote and the rental apply it, so the DM never voices a
bundle price the rental would refuse. The single rentals stay settlement-blind —
gating those too is concern c5c5871115dc (Phase 6 settlement templates).
"""

import json
import logging
import random
from datetime import UTC, datetime, timedelta

from livekit.agents.llm import ToolError
from livekit.agents.voice import RunContext

import db
import db_activity_queries
import db_content_queries
import db_mutations
import db_queries
import materials
import preflight_pipeline
import pricing_queries
import recipe_validation
import recipes
import workspace
from disposition import resolve_disposition
from session_data import SessionData
from tool_preconditions import require_npc_present
from tool_support import _validate_id
from workspace import WorkspaceType

logger = logging.getLogger("divineruin.crafting_tools")

# LOCKED 3-independent-slot model (slot_validation.ts): one concurrent crafting project.
_CRAFTING_SLOT_CAP = 1
_SECONDS_PER_CYCLE = 14400  # 4h per async cycle; mirrors recipes.ts craftingDurationSeconds
_FIELD_CRAFT_FLOOR_SECONDS = 900  # 15-min floor for 0-cycle (field) recipes


_PORTABLE_LAB_ITEM_ID = "artificers_portable_lab"


def _default_now() -> datetime:
    return datetime.now(UTC)


async def _owns_portable_lab(queries_mod, player_id: str, *, conn=None) -> bool:
    """Whether the player owns an Artificer's Portable Lab (quantity >= 1).

    Read once per request and fed to BOTH the workspace grant (get_accessible_workspaces)
    and the slot validator (_resolve_crafting_slot) — the single-read contract the TS twin
    uses (activity_create.ts). Quantity-aware to mirror its COALESCE((quantity)::int, 1) >= 1.
    """
    lab = await queries_mod.get_inventory_item(player_id, _PORTABLE_LAB_ITEM_ID, conn=conn)
    return lab is not None and lab.get("quantity", 1) >= 1


def _resolve_crafting_slot(
    slot_counts: dict[str, int], archetype: str | None, has_portable_lab: bool
) -> tuple[str | None, str | None]:
    """The slot a new craft consumes, or (None, refusal-reason).

    Pure mirror of slot_validation.ts validateSlotAvailability's crafting branch (ADR 0005):
    normally a craft takes the crafting slot, but an Artificer who owns a Portable Lab may
    borrow the training slot when crafting is full (and both-full still refuses). The caller
    stamps the returned slot on the activity row so count_active_by_slot buckets it correctly.
    """
    if slot_counts["crafting"] < _CRAFTING_SLOT_CAP:
        return "crafting", None
    if archetype and archetype.lower() == "artificer" and has_portable_lab:
        if slot_counts["training"] >= 1:
            return None, "Both crafting and training slots are full."
        return "training", None  # Portable-Lab exception: borrow the training slot
    return None, "You already have a crafting project underway. Wait for it to finish first."


async def _query_available_workspaces_impl(
    context: RunContext[SessionData],
    npc_id: str | None = None,
    *,
    queries_mod=db_queries,
    content_mod=db_content_queries,
    workspace_mod=workspace,
    pricing_mod=pricing_queries,
) -> str:
    player_id = context.userdata.player_id
    location_id = context.userdata.location_id
    if npc_id is not None:
        _validate_id(npc_id, "npc_id")
    # Report the Portable-Lab grant too (read/write parity): the voiced "what can I craft
    # here" answer must match what start_crafting_project actually permits (concern 6a1b99cd6ac7).
    has_portable_lab = await _owns_portable_lab(queries_mod, player_id)
    accessible = await queries_mod.get_accessible_workspaces(player_id, location_id, has_portable_lab=has_portable_lab)
    if npc_id is not None:
        await require_npc_present(location_id, npc_id, queries=queries_mod, suffix=" to quote a workspace rental")
        disposition = await resolve_disposition(npc_id, player_id, queries_mod=queries_mod, content_mod=content_mod)

    multipliers = (await pricing_mod.get_economy_pricing())["disposition_multipliers"]
    offers = await _offers_hosted_here(location_id, content_mod=content_mod, workspace_mod=workspace_mod)
    if npc_id is None:
        rentable = [
            {
                "workspace_type": offer.token,
                "grants": [granted.value for granted in offer.grants],
                "prices_sp_per_day_by_disposition": {
                    tier: workspace_mod.compute_workspace_rental_price(
                        offer.base_price_sp, tier, multipliers=multipliers
                    ).price_sp
                    for tier in workspace_mod.RENTABLE_DISPOSITIONS
                },
            }
            for offer in offers
        ]
        return json.dumps({"accessible": sorted(accessible), "rentable": rentable})

    rentable = []
    try:
        for offer in offers:
            quote = workspace_mod.compute_workspace_rental_price(
                offer.base_price_sp, disposition, multipliers=multipliers
            )
            entry = {"workspace_type": offer.token, "available": quote.available}
            if quote.available:
                entry["price_sp_per_day"] = quote.price_sp
            else:
                entry["reason"] = quote.reason
            rentable.append(entry)
    except ValueError as exc:
        raise ToolError(f"NPC {npc_id} has an invalid disposition for renting: {exc}") from exc
    return json.dumps(
        {
            "accessible": sorted(accessible),
            "rentable": rentable,
            "quoted_for_npc_id": npc_id,
            "disposition": disposition.lower(),
        }
    )


async def _rent_workspace_impl(
    context: RunContext[SessionData],
    workspace_type: str,
    npc_id: str,
    days: int,
    *,
    db_mod=db,
    queries_mod=db_queries,
    mutations_mod=db_mutations,
    content_mod=db_content_queries,
    workspace_mod=workspace,
    pricing_mod=pricing_queries,
    now_fn=None,
) -> str:
    context.disallow_interruptions()
    _validate_id(workspace_type, "workspace_type")
    _validate_id(npc_id, "npc_id")
    if workspace_type == WorkspaceType.FIELD.value:
        raise ToolError(f"{workspace_type} is not rentable (Field is free and always available).")
    try:
        offer = workspace_mod.resolve_rental_offer(workspace_type)
    except ValueError as exc:
        raise ToolError(f"Unknown workspace type: {workspace_type}") from exc
    if days < 1:
        raise ToolError("Rental length must be at least 1 day.")

    player_id = context.userdata.player_id
    location_id = context.userdata.location_id

    # A multi-workspace offer is only sold where the settlement can host every member
    # (spec: Forge + Laboratory is a city-or-Keldaran-hold bundle). Refuse before any
    # read that could charge.
    if len(offer.grants) > 1:
        refusal = await _bundle_refusal(location_id, offer, content_mod=content_mod, workspace_mod=workspace_mod)
        if refusal:
            raise ToolError(refusal)

    # Co-location gate (concern bec87679b223): you can only rent from an NPC who is
    # actually here — disposition alone is not enough.
    await require_npc_present(location_id, npc_id, queries=queries_mod, suffix=" to rent a workspace from")

    # Disposition gates the price; resolve_disposition falls back to the NPC's
    # content default_disposition when the player has no recorded standing.
    disposition = await resolve_disposition(npc_id, player_id, queries_mod=queries_mod, content_mod=content_mod)

    # An off-tier content default_disposition (not a canonical tier) makes
    # compute_rental_price raise ValueError; that's a content bug, so surface it as
    # ToolError to keep the tool's ADR-0002 error shape (mirrors _learn_recipe_impl).
    pricing = await pricing_mod.get_economy_pricing()
    try:
        quote = workspace_mod.compute_workspace_rental_price(
            offer.base_price_sp,
            disposition,
            multipliers=pricing["disposition_multipliers"],
        )
    except ValueError as exc:
        raise ToolError(f"NPC {npc_id} has an invalid disposition for renting: {exc}") from exc
    if not quote.available:
        raise ToolError(quote.reason)
    # An offer's base price is sp per CALENDAR DAY and `days` is what extends expires_at,
    # so the charge scales with the term — a 30-day forge is not a 1-day forge.
    price_sp = quote.price_sp * days
    price_gp = price_sp / pricing["silver_per_gold"]
    expires_at = (now_fn or _default_now)() + timedelta(days=days)

    async with db_mod.transaction() as conn:
        player = await queries_mod.get_player(player_id, conn=conn, for_update=True)
        if not player:
            raise ToolError(f"Unknown player: {player_id}")
        gold = player.get("gold", 0)
        if gold < price_gp:
            raise ToolError(f"Not enough gold: the rental costs {price_gp:.1f}gp and you have {gold}gp.")
        if price_sp:
            await mutations_mod.update_player_gold(player_id, gold - price_gp, conn=conn)
        # One row per granted workspace, inside the debit's transaction: the stored
        # workspace_type must stay inside the four-member vocabulary the TS gate
        # re-parses (apps/server/src/workspace.ts parseWorkspaceType), so the bundle
        # token itself is never persisted.
        rental_ids = [
            await mutations_mod.create_workspace_rental(
                player_id, location_id, granted.value, "rental", expires_at, conn=conn
            )
            for granted in offer.grants
        ]

    logger.info("rent_workspace: player=%s npc=%s offer=%s days=%s", player_id, npc_id, offer.token, days)
    result = {
        "workspace_type": offer.token,
        "price_sp": price_sp,
        "expires_at": expires_at.isoformat(),
    }
    if len(offer.grants) > 1:
        result["workspace_types"] = [granted.value for granted in offer.grants]
        result["rental_ids"] = rental_ids
    else:
        result["rental_id"] = rental_ids[0]
    return json.dumps(result)


async def _bundle_refusal(location_id: str, offer: workspace.RentalOffer, *, content_mod, workspace_mod) -> str | None:
    """Why `location_id` cannot host a multi-workspace `offer`, or None if it can.

    One rule, two callers — the rental raises it and the quote drops the offer — because
    a price the DM can voice but no call can charge is the exact debt this path pays.
    Scoped to multi-grant offers: single rentals stay settlement-blind (whole-quote
    availability gating is concern c5c5871115dc, Phase 6)."""
    location = await content_mod.get_location(location_id)
    tier = (location or {}).get("settlement_tier")
    if not tier:
        return f"{location_id} is not a settlement — the {offer.token} bundle needs a city or Keldaran hold."
    try:
        size = workspace_mod.SettlementSize(tier)
    except ValueError:
        return f"{location_id} has an unknown settlement tier {tier!r}."
    missing = workspace_mod.bundle_missing_workspaces(size)
    if missing:
        names = " and ".join(w.value for w in missing)
        return f"{location_id} has no {names} to rent — the {offer.token} bundle needs both."
    return None


async def _offers_hosted_here(location_id: str, *, content_mod, workspace_mod) -> list[workspace.RentalOffer]:
    """The rental offers `location_id` can actually host, in RENTAL_OFFERS order."""
    hosted = []
    for offer in workspace_mod.RENTAL_OFFERS:
        if len(offer.grants) > 1 and await _bundle_refusal(
            location_id, offer, content_mod=content_mod, workspace_mod=workspace_mod
        ):
            continue
        hosted.append(offer)
    return hosted


async def _start_crafting_project_impl(
    context: RunContext[SessionData],
    recipe_id: str,
    *,
    db_mod=db,
    queries_mod=db_queries,
    mutations_mod=db_mutations,
    activity_mod=db_activity_queries,
    recipes_mod=recipes,
    materials_mod=materials,
    preflight_mod=preflight_pipeline,
    validation_mod=recipe_validation,
    now_fn=None,
    rng=None,
) -> str:
    context.disallow_interruptions()
    _validate_id(recipe_id, "recipe_id")
    player_id = context.userdata.player_id
    location_id = context.userdata.location_id

    # Cached reference reads BEFORE the txn (pool-exhaustion guard, like _learn_recipe_impl).
    recipe = await recipes_mod.get_recipe(recipe_id)
    if recipe is None:
        raise ToolError(f"Unknown recipe: {recipe_id}")
    catalog = await materials_mod.get_materials_catalog()

    async with db_mod.transaction() as conn:
        player = await queries_mod.get_player(player_id, conn=conn, for_update=True)
        if not player:
            raise ToolError(f"Unknown player: {player_id}")

        # Portable-Lab ownership read ONCE, fed to BOTH the slot exception and the
        # workspace grant below — the single-read contract the TS twin uses.
        has_portable_lab = await _owns_portable_lab(queries_mod, player_id, conn=conn)

        # Artificer Portable-Lab slot exception (ADR 0005): converge with REST so voice
        # and REST refuse/allow identically. The consumed slot is stamped on the row.
        # Lock the slot rows before counting (TS lockPlayerSlotRows parity) so a
        # concurrent create can't pass the slot check during a worker status flip.
        await activity_mod.lock_player_slot_rows(player_id, conn=conn)
        slot_counts = await activity_mod.count_active_by_slot(player_id, conn=conn)
        consumed_slot, slot_refusal = _resolve_crafting_slot(slot_counts, player.get("class"), has_portable_lab)
        if slot_refusal is not None:
            raise ToolError(slot_refusal)

        # Gather the five-check pre-flight inputs (materials locked FOR UPDATE so the
        # allocate→consume below can't race a concurrent craft on the same stacks).
        known = await queries_mod.get_player_known_recipe_ids(player_id, conn=conn)
        crafting_tier = (await queries_mod.get_single_skill_advancement(player_id, "crafting", conn=conn))["tier"]
        accessible = await queries_mod.get_accessible_workspaces(
            player_id, location_id, conn=conn, has_portable_lab=has_portable_lab
        )
        available = await queries_mod.get_player_materials(player_id, conn=conn, for_update=True)

        # A non-canonical crafting/recipe tier makes run_preflight Check 2 raise a raw
        # ValueError (DB-validated at write boundaries, so a content/migration bug, not
        # user input); surface it as ToolError to keep the tool's ADR-0002 error shape
        # (mirrors _learn_recipe_impl's validate_recipe_slot_capacity wrap + rent_workspace).
        try:
            result = preflight_mod.run_preflight(recipe, known, crafting_tier, accessible, available, catalog)
        except ValueError as exc:
            raise ToolError(f"Cannot craft {recipe['name']}: invalid tier configuration ({exc})") from exc
        if not result.passed:
            raise ToolError(f"Cannot craft {recipe['name']}: {result.reason}")

        # Authoritative disjoint allocation (allocate-then-deduct). The greedy pre-flight
        # Check 4 can pass where a real allocation can't (overlapping substitutable pools);
        # surface that as a clear error rather than over-consuming.
        alloc = validation_mod.allocate_materials(recipe["materials"], available, catalog)
        if not alloc.satisfied:
            raise ToolError(f"Cannot craft {recipe['name']}: {alloc.reason}")
        await mutations_mod.consume_player_materials(player_id, alloc.by_id, conn=conn)

        cycles = recipe["async_cycles"]
        min_seconds = cycles * _SECONDS_PER_CYCLE if cycles > 0 else _FIELD_CRAFT_FLOOR_SECONDS
        max_seconds = min_seconds * 2
        now = (now_fn or _default_now)()
        resolve_at = now + timedelta(seconds=(rng or random.Random()).randint(min_seconds, max_seconds))

        # Shared parameters shape so async_worker / resolve_crafting reads it the same
        # regardless of entry point. The first five keys match the TS create path
        # (activities.ts). workspace_required/workspace_access/crafting_tier/
        # tainted_materials are the story-005 resolution gate inputs: resolve_crafting
        # re-checks workspace access + tainted-Expert at completion. The TS path does
        # NOT capture these yet — Slice 2 adds them in activities.ts to re-converge the
        # two entry points. resolve_crafting reads them via .get(), so the lag is
        # additive-safe. workspace_access is sorted so the stored JSONB is deterministic.
        data = {
            "status": "in_progress",
            "activity_type": "crafting",
            # The slot actually consumed (TS activity_create.ts parity): "crafting"
            # normally, "training" when the Artificer Portable-Lab exception borrows it.
            # count_active_by_slot COALESCEs this over activity_type.
            "slot": consumed_slot,
            "start_time": now.isoformat(),
            "duration_min_seconds": min_seconds,
            "duration_max_seconds": max_seconds,
            "resolve_at": resolve_at.isoformat(),
            "parameters": {
                "recipe_id": recipe_id,
                "result_item_id": recipe["output_item"],
                "result_item_name": recipe["name"],
                "required_materials": alloc.flat,
                "dc": recipe["crafting_dc"],
                "workspace_required": recipe["workspace_required"],
                "workspace_access": sorted(accessible),
                "crafting_tier": crafting_tier,
                "tainted_materials": recipe["tainted_materials"],
            },
            "outcome": None,
            "narration_text": None,
            "narration_audio_url": None,
            "decision_options": None,
        }
        activity_id = await mutations_mod.create_async_activity(player_id, data, conn=conn)

    logger.info("start_crafting_project: player=%s recipe=%s activity=%s", player_id, recipe_id, activity_id)
    return json.dumps(
        {
            "activity_id": activity_id,
            "recipe_id": recipe_id,
            "result_item_name": recipe["name"],
            "resolve_at_estimate": resolve_at.isoformat(),
        }
    )
