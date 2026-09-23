"""Session-init state hydration — rehydrate persisted resonance/veil_ward/concentration and
set+persist the gated Thessyn flickering_bonus once per fresh session (M3.5 / story-004).

agent.dm_session builds a fresh SessionData whose resonance/veil_ward/concentration sit at their
defaults — it never reloaded the values a returning player persisted last session. This composer
closes that gap and wires the Thessyn Deep-Adaptation chain end-to-end:

  1. read the three persisted states from players.data onto SessionData,
  2. increment the player session_count once (story-002, hydrate_player_session),
  3. compute the session-gated flickering_bonus (story-003, compute_flickering_bonus) and BOTH
     set it on ResonanceTrack AND persist it (story-001, update_player_flickering_bonus).

Persisting the gated bonus is the crux: it makes the DB-read path (read_player_resonance) and the
in-memory session derive the SAME Resonance band — one source, no drift (concern 90fdda98f16b).

Called once per fresh session by agent.dm_session — reconnects reuse the in-memory SessionData
(_setup_reconnection), mirroring hydrate_companion_state's once-per-session contract. The injected
*_mod params are the test seam (mirrors _cast_spell_impl's DI); production uses the defaults.
"""

import json
from datetime import UTC, datetime

import asyncpg

import db
import db_mutations_concentration
import db_mutations_divine
import db_mutations_resonance
import db_mutations_veil_ward
import event_types as E
import game_events
import player_session
import racial_resonance
from favor_rules import apply_favor_delta, neglect_decay
from session_data import SessionData
from veil_ward import WardScope


async def apply_session_favor_decay(
    session: SessionData,
    player_id: str,
    player: dict,
    *,
    now: datetime | None = None,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> None:
    favor = player.get("divine_favor") or {}
    if (favor.get("patron") or "none") == "none":
        return
    instant = now or datetime.now(UTC)
    source = conn or await db.get_pool()
    if isinstance(source, asyncpg.Pool):
        async with source.acquire() as connection:
            await _decay_locked(session, player_id, connection, instant)
    else:
        await _decay_locked(session, player_id, source, instant)


async def _decay_locked(session: SessionData, player_id: str, connection, now: datetime) -> None:
    payload = None
    async with connection.transaction():
        row = await connection.fetchrow(
            "SELECT data->'divine_favor' AS favor FROM players WHERE player_id=$1 FOR UPDATE",
            player_id,
        )
        if row is None:
            raise ValueError(f"missing player row: {player_id}")
        favor = row["favor"]
        if isinstance(favor, str):
            favor = json.loads(favor)
        if (favor.get("patron") or "none") == "none":
            return
        if "last_served_at" not in favor and "last_decay_at" not in favor:
            await db_mutations_divine.initialize_favor_clock(player_id, now.isoformat(), conn=connection)
            return
        amount = neglect_decay(favor, now)
        if not amount:
            return
        previous = favor["level"]
        new_level = apply_favor_delta(previous, favor["max"], -amount)
        await db_mutations_divine.persist_favor_decay(player_id, new_level, now.isoformat(), conn=connection)
        if new_level != previous:
            payload = {
                "new_level": new_level,
                "previous_level": previous,
                "amount": new_level - previous,
                "max": favor["max"],
                "patron_id": favor["patron"],
                "player_id": player_id,
                "last_whisper_level": favor["last_whisper_level"],
                "reason": "neglect",
            }
    if payload is not None:
        if player_id == session.primary_player_id:
            session.favor_loss = (payload["patron_id"], -payload["amount"])
        await game_events.publish_game_event(session.room, E.DIVINE_FAVOR_CHANGED, payload, session.event_bus)


async def hydrate_session_state(
    session: SessionData,
    player: dict,
    *,
    resonance_mutations_mod=db_mutations_resonance,
    veil_ward_mutations_mod=db_mutations_veil_ward,
    concentration_mutations_mod=db_mutations_concentration,
    player_session_mod=player_session,
    racial_mod=racial_resonance,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
    now: datetime | None = None,
) -> None:
    """Rehydrate a FRESH session's persisted state and set+persist the gated Thessyn bonus.

    Loads resonance/concentration from players.data onto ``session`` and the veil ward from the
    session's LOCATION scope (M24: the ward is scope-owned, so it is not on the player row),
    increments the player session_count once, and computes the session-gated flickering_bonus
    which it BOTH sets on ResonanceTrack AND persists — so the DB-read path and the in-memory
    session derive one band. A None/non-Thessyn race short-circuits the gate to 0 (still
    persisted — a harmless 0).
    """
    player_id = session.primary_player_id
    res = await resonance_mutations_mod.read_player_resonance(player_id, conn=conn)
    # The ward is read from the LOCATION the session starts in, never from the player row (M24).
    # A fresh session is never in combat, so a location scope is the only one that can cover it.
    ward = await veil_ward_mutations_mod.read_active_ward(WardScope.location(session.location_id), conn=conn)
    conc = await concentration_mutations_mod.read_player_concentration(player_id, conn=conn)
    session_count = await player_session_mod.hydrate_player_session(player_id, conn=conn)

    # The gated band-shift is computed from the just-incremented count + race, then persisted so a
    # later read_player_resonance derives the same band the session holds (single source, no drift).
    # Write only on a real transition: res["flickering_bonus"] is the persisted value already in
    # hand, so a steady band (non-Thessyn 0==0, a Thessyn past the gate 1==1) skips the redundant
    # UPDATE and we persist only when the Deep-Adaptation crossing actually shifts the bonus.
    bonus = racial_mod.compute_flickering_bonus(player.get("race"), session_count)
    if bonus != res["flickering_bonus"]:
        await resonance_mutations_mod.update_player_flickering_bonus(player_id, bonus, conn=conn)

    session.resonance.current = res["current"]
    session.resonance.flickering_bonus = bonus
    # The HUD mirror, not an authority: None for an unwarded scope, absence rather than a
    # default-inactive row. The cast path resolves its own ward from the DB (ward_resolution).
    session.location_ward = ward
    session.concentration.spell_id = conc["spell_id"]
    await apply_session_favor_decay(session, player_id, player, now=now, conn=conn)
