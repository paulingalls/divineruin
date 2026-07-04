"""Resource-node respawn resolver — pure engine (M16 / story-001). Zero IO, zero RNG.

Turns a depleted gathering node's `quantity`, its immutable `capacity`, its `respawn_days`
cadence, and a caller-supplied `elapsed_days` into a respawn decision: whether the node is due
to restore and, if so, its restored quantity. The caller supplies `elapsed_days` — this module
never touches the clock, the DB, or world state, mirroring gathering.py and travel.py.

Respawn classes (spec docs/game_mechanics/game_mechanics_combat.md L1048-1055):
- `respawn_days > 0` — restores to capacity once `elapsed_days` reaches the cadence.
- `respawn_days == 0` — one-time (e.g. a salvage site); never respawns.
- `respawn_days == -1` — persistent (e.g. hollow residue); never depletes, so restore is a no-op.

The apply site (M21's world-sim tick) computes `elapsed_days` from the node's `updated_at` delta
and persists the result via db_mutations_gathering.restore_node_quantity.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class NodeRespawn:
    """Respawn decision for one node. `restored=False` means the caller can skip the write."""

    new_quantity: int
    restored: bool


def compute_node_respawn(*, quantity: int, capacity: int, respawn_days: int, elapsed_days: float) -> NodeRespawn:
    """Resolve whether a depleted node is due to respawn.

    `respawn_days == -1` (persistent) and `respawn_days == 0` (one-time) never restore. For
    `respawn_days > 0`, the node restores to `capacity` once `elapsed_days >= respawn_days` and
    `quantity < capacity`; otherwise it's a no-op. Raises ValueError for a negative `elapsed_days`
    or `capacity` — both are caller bugs, mirroring gathering.py's fail-loud off-catalog raises.
    """
    if elapsed_days < 0:
        raise ValueError(f"elapsed_days must be non-negative, got {elapsed_days!r}")
    if capacity < 0:
        raise ValueError(f"capacity must be non-negative, got {capacity!r}")

    if respawn_days <= 0:
        return NodeRespawn(new_quantity=quantity, restored=False)

    if quantity < capacity and elapsed_days >= respawn_days:
        return NodeRespawn(new_quantity=capacity, restored=True)

    return NodeRespawn(new_quantity=quantity, restored=False)
