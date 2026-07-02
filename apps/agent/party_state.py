"""Party state module (PartyMember, PartyState).

Represents a party of one or more player-characters. Each member carries their own
per-player sub-state (resonance, veil_ward, concentration, corruption_level, patron_id).
A solo player is modeled as a 1-member party, so SessionData (single-player) and
future multi-player code share the same PartyState abstraction.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from caster_state import ConcentrationState, ResonanceTrack, VeilWardState


@dataclass
class PartyMember:
    """A single member of a party, carrying their own per-player sub-state."""

    player_id: str
    resonance: ResonanceTrack
    veil_ward: VeilWardState
    concentration: ConcentrationState
    corruption_level: int = 0
    patron_id: str = "none"


@dataclass
class PartyState:
    """A party of player-characters, each with isolated per-player sub-state."""

    members: list[PartyMember] = field(default_factory=list)

    @classmethod
    def solo(
        cls,
        player_id: str,
        *,
        resonance: ResonanceTrack | None = None,
        veil_ward: VeilWardState | None = None,
        concentration: ConcentrationState | None = None,
        corruption_level: int = 0,
        patron_id: str = "none",
    ) -> PartyState:
        """Build a 1-member party with the given player_id and optional sub-state.

        When a sub-state arg is None, use a fresh default instance.
        """
        member = PartyMember(
            player_id=player_id,
            resonance=resonance if resonance is not None else ResonanceTrack(),
            veil_ward=veil_ward if veil_ward is not None else VeilWardState(),
            concentration=concentration if concentration is not None else ConcentrationState(),
            corruption_level=corruption_level,
            patron_id=patron_id,
        )
        return cls(members=[member])

    def member(self, player_id: str) -> PartyMember | None:
        """Look up a member by player_id; return None if not found."""
        for m in self.members:
            if m.player_id == player_id:
                return m
        return None

    @property
    def primary(self) -> PartyMember:
        """Return the first member; raise ValueError if the party is empty."""
        if not self.members:
            raise ValueError("Cannot get primary member of an empty party")
        return self.members[0]

    @property
    def member_ids(self) -> list[str]:
        """Return the list of player_ids in this party (in order)."""
        return [m.player_id for m in self.members]

    def contains(self, player_id: str) -> bool:
        """Return True if player_id is a member of this party."""
        return self.member(player_id) is not None

    def to_dict(self) -> dict:
        """Serialize to a dict via asdict, suitable for JSONB storage."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> PartyState:
        """Deserialize from a dict, reconstructing nested value-type instances.

        Each member dict is reconstructed into a PartyMember with
        ResonanceTrack/VeilWardState/ConcentrationState INSTANCES (not raw dicts),
        matching the from_dict pattern used by CombatState.
        """
        members = []
        for m_data in data.get("members", []):
            member = PartyMember(
                player_id=m_data["player_id"],
                resonance=ResonanceTrack(**m_data["resonance"]),
                veil_ward=VeilWardState(**m_data["veil_ward"]),
                concentration=ConcentrationState(**m_data["concentration"]),
                corruption_level=m_data.get("corruption_level", 0),
                patron_id=m_data.get("patron_id", "none"),
            )
            members.append(member)
        return cls(members=members)
