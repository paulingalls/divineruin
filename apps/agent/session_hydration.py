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

import asyncpg

import db_mutations_concentration
import db_mutations_resonance
import db_mutations_veil_ward
import player_session
import racial_resonance
from session_data import SessionData
from veil_ward import WardScope


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
) -> None:
    """Rehydrate a FRESH session's persisted state and set+persist the gated Thessyn bonus.

    Loads resonance/veil_ward/concentration from players.data onto ``session``, increments the
    player session_count once, and computes the session-gated flickering_bonus which it BOTH sets
    on ResonanceTrack AND persists — so the DB-read path and the in-memory session derive one band.
    A None/non-Thessyn race short-circuits the gate to 0 (still persisted — a harmless 0).
    """
    player_id = session.player_id
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
    # read_active_ward returns None for an unwarded scope — absence, not a default-inactive row.
    session.veil_ward.active = ward is not None
    session.veil_ward.source = ward["source"] if ward else None
    session.concentration.spell_id = conc["spell_id"]
