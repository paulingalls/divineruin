"""Death, resurrection, and stabilization during combat settlement."""

import resurrection
from combat_phase import is_terminally_down


async def settle_lives(cs, outcome, primary_id, combat_cleared, queries, mutations, conn):
    # A destroyed Hollowed echo is already dead and must return through Mortaen on any outcome.
    def _is_truly_dead(p) -> bool:
        return (p.type == "player" and is_terminally_down(p)) or p.type == "temporary_hollowed"

    def _fallen_savable(p) -> bool:
        return p.type == "player" and p.is_fallen and not is_terminally_down(p)

    death_context: dict | None = None
    dead_lives = [
        p for p in cs.participants if _is_truly_dead(p) or (outcome in ("defeat", "fled") and _fallen_savable(p))
    ]
    if dead_lives:
        rows = [(p.id, await queries.get_player(p.id, conn=conn)) for p in dead_lives]
        missing = [pid for pid, row in rows if row is None]
        if missing:
            raise RuntimeError(f"Dead player participant(s) {missing} have no players.data row")
        contexts = await resurrection.resurrect_party_on_defeat(
            [row for _, row in rows], combat_cleared=combat_cleared, conn=conn
        )
        # Only the primary's anchor moves the shared session after the transaction commits.
        death_context = next((ctx for (pid, _), ctx in zip(rows, contexts, strict=True) if pid == primary_id), None)

    # A declared defeat sends the primary through Mortaen even if it was still standing.
    if outcome == "defeat" and death_context is None:
        primary_row = await queries.get_player(primary_id, conn=conn)
        if primary_row is None:
            raise RuntimeError(f"Primary player {primary_id!r} has no players.data row on defeat")
        death_context = await resurrection.resurrect_on_defeat(primary_row, combat_cleared=combat_cleared, conn=conn)

    if outcome in ("victory", "deescalated"):
        for p in cs.participants:
            if _fallen_savable(p):
                if await queries.get_player(p.id, conn=conn) is None:
                    raise RuntimeError(f"Fallen player {p.id!r} has no players.data row to stabilize")
                await mutations.update_player_hp(p.id, 1, conn=conn)

    return death_context
