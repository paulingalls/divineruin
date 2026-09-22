"""Death, resurrection, and stabilization during combat settlement."""

import resurrection
from combat_phase import is_terminally_down
from session_data import CombatState


async def settle_lives(
    cs: CombatState, outcome: str, primary_id: str, combat_cleared: bool, queries, mutations, conn
) -> dict | None:
    """Return the dead and stabilize the savable, inside the combat-end transaction.

    Returns the primary's death context (its anchor moves the shared session post-commit), or None
    when the primary survived a non-defeat end."""

    # A destroyed Hollowed echo is already dead and must return through Mortaen on ANY outcome;
    # scoping this to victory/defeat would strand an echo on a fled or deescalated end.
    def _is_truly_dead(p) -> bool:
        return (p.type == "player" and is_terminally_down(p)) or p.type == "temporary_hollowed"

    def _fallen_savable(p) -> bool:
        return p.type == "player" and p.is_fallen and not is_terminally_down(p)

    death_context: dict | None = None
    # On defeat and fled nobody is left to drag the merely-fallen clear (M15 decision 498f0df12b14).
    dead_lives = [
        p for p in cs.participants if _is_truly_dead(p) or (outcome in ("defeat", "fled") and _fallen_savable(p))
    ]
    if dead_lives:
        # A missing row is corruption, not a skip: skipping would strand the character (concern 2a646ecf0b4b).
        rows = [(p.id, await queries.get_player(p.id, conn=conn)) for p in dead_lives]
        missing = [pid for pid, row in rows if row is None]
        if missing:
            raise RuntimeError(f"Dead player participant(s) {missing} have no players.data row")
        contexts = await resurrection.resurrect_party_on_defeat(
            [row for _, row in rows], combat_cleared=combat_cleared, conn=conn
        )
        death_context = next((ctx for (pid, _), ctx in zip(rows, contexts, strict=True) if pid == primary_id), None)

    # A declared defeat sends the primary through Mortaen even if it was still standing.
    if outcome == "defeat" and death_context is None:
        primary_row = await queries.get_player(primary_id, conn=conn)
        if primary_row is None:
            raise RuntimeError(f"Primary player {primary_id!r} has no players.data row on defeat")
        death_context = await resurrection.resurrect_on_defeat(primary_row, combat_cleared=combat_cleared, conn=conn)

    # The party holds the field, so a savable ally comes to at 1 HP; combat already wrote their HP to 0.
    if outcome in ("victory", "deescalated"):
        for p in cs.participants:
            if _fallen_savable(p):
                if await queries.get_player(p.id, conn=conn) is None:
                    raise RuntimeError(f"Fallen player {p.id!r} has no players.data row to stabilize")
                await mutations.update_player_hp(p.id, 1, conn=conn)

    return death_context
