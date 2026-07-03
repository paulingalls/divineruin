"""Multiplayer combat-END reconcile (M18 story-003): _end_combat_db runs its post-combat paths
PER PARTY MEMBER, not for the primary only. Fast-lane, mock-DI (no real DB): patches the
condition read/save round-trip and asserts each player participant reconciles into its OWN
players.data row. The real phase-loop-to-defeat end-to-end proof is story-007's acceptance capstone.

Solo behavior (a 1-member party) is covered byte-identically by the existing single-player
combat-end suites; this suite adds the >1-member assertions.
"""

from __future__ import annotations

import random
from unittest.mock import AsyncMock, MagicMock

import pytest

import db_mutations_conditions
import event_types as E
from caster_state import ConcentrationState, ResonanceTrack, VeilWardState
from combat_end import _end_combat_db
from combat_events import EventSink
from party_state import PartyMember
from session_data import CombatParticipant, CombatState, SessionData


class FakeRng(random.Random):
    def __init__(self, die: int = 4, chance: float = 1.0):
        super().__init__()
        self._die = die
        self._chance = chance

    def randint(self, a: int, b: int) -> int:
        return self._die

    def random(self) -> float:
        return self._chance


def _member(player_id: str) -> PartyMember:
    return PartyMember(
        player_id=player_id,
        resonance=ResonanceTrack(),
        veil_ward=VeilWardState(),
        concentration=ConcentrationState(),
    )


def _two_pc_session() -> SessionData:
    session = SessionData(player_id="p1", location_id="loc1", room=None)
    session.party.members.append(_member("p2"))
    return session


def _player_participant(pid: str, name: str, conds: list[dict]) -> CombatParticipant:
    return CombatParticipant(
        id=pid, name=name, type="player", initiative=15, hp_current=20, hp_max=20, ac=14, conditions=conds
    )


def _cond(ctype: str, **extra) -> dict:
    return {"type": ctype, "duration": "encounter", "source": "test", "stacks": 1, **extra}


async def _run_end_combat_db(session, cs, outcome, *, save_mock, read_side_effect=None):
    """Drive _end_combat_db with a mock conn, patching the condition read/save round-trip. Returns
    nothing — assertions read the injected save_mock's call list."""
    read_mock = AsyncMock(side_effect=read_side_effect or (lambda pid, conn=None: []))
    db_mutations_conditions.read_player_conditions = read_mock  # type: ignore[assignment]
    db_mutations_conditions.save_player_conditions = save_mock  # type: ignore[assignment]
    mutations = AsyncMock()
    queries = AsyncMock()
    sink = EventSink()
    await _end_combat_db(
        session,
        cs,
        outcome,
        mutations=mutations,
        queries=queries,
        conn=MagicMock(),
        sink=sink,
        content=MagicMock(),
        pricing=MagicMock(),
        rng=FakeRng(),
    )


@pytest.fixture(autouse=True)
def _restore_condition_module():
    orig_read = db_mutations_conditions.read_player_conditions
    orig_save = db_mutations_conditions.save_player_conditions
    yield
    db_mutations_conditions.read_player_conditions = orig_read
    db_mutations_conditions.save_player_conditions = orig_save


async def test_victory_reconciles_persistent_conditions_per_member():
    # p1 acquired Wounded, p2 acquired Exhausted. Each must persist into its OWN players.data row.
    session = _two_pc_session()
    cs = CombatState(
        combat_id="c1",
        participants=[
            _player_participant("p1", "Kael", [_cond("wounded")]),
            _player_participant("p2", "Bren", [_cond("exhausted")]),
            CombatParticipant(id="g1", name="Goblin", type="enemy", initiative=8, hp_current=0, hp_max=7, ac=13),
        ],
        initiative_order=["p1", "p2", "g1"],
        round_number=2,
        current_turn_index=0,
        location_id="loc1",
    )
    save = AsyncMock()
    await _run_end_combat_db(session, cs, "victory", save_mock=save)

    saved = {call.args[0]: call.args[1] for call in save.await_args_list}
    assert set(saved) == {"p1", "p2"}
    assert [c["type"] for c in saved["p1"]] == ["wounded"]
    assert [c["type"] for c in saved["p2"]] == ["exhausted"]


async def test_victory_reconciles_beneficial_dice_per_member():
    # p1 keeps a surviving Blessed die, p2 an Inspired die — each lands on its own row.
    session = _two_pc_session()
    cs = CombatState(
        combat_id="c1",
        participants=[
            _player_participant("p1", "Kael", [_cond("blessed")]),
            _player_participant("p2", "Bren", [_cond("inspired")]),
            CombatParticipant(id="g1", name="Goblin", type="enemy", initiative=8, hp_current=0, hp_max=7, ac=13),
        ],
        initiative_order=["p1", "p2", "g1"],
        round_number=2,
        current_turn_index=0,
        location_id="loc1",
    )
    save = AsyncMock()
    await _run_end_combat_db(session, cs, "victory", save_mock=save)

    saved = {call.args[0]: call.args[1] for call in save.await_args_list}
    assert [c["type"] for c in saved["p1"]] == ["blessed"]
    assert [c["type"] for c in saved["p2"]] == ["inspired"]


async def test_non_primary_reconcile_reads_its_own_store():
    # The existing-store read is keyed on the member id, so a non-primary member's prior Wounded
    # merges with its own combat-gained Exhausted — not the primary's store.
    session = _two_pc_session()
    cs = CombatState(
        combat_id="c1",
        participants=[
            _player_participant("p1", "Kael", []),
            _player_participant("p2", "Bren", [_cond("exhausted", stacks=2)]),
            CombatParticipant(id="g1", name="Goblin", type="enemy", initiative=8, hp_current=0, hp_max=7, ac=13),
        ],
        initiative_order=["p1", "p2", "g1"],
        round_number=2,
        current_turn_index=0,
        location_id="loc1",
    )

    def _read(pid, conn=None):
        return [_cond("wounded")] if pid == "p2" else []

    save = AsyncMock()
    await _run_end_combat_db(session, cs, "victory", save_mock=save, read_side_effect=_read)

    saved = {call.args[0]: call.args[1] for call in save.await_args_list}
    # p1's store was empty and it gained nothing -> unchanged -> no write.
    assert "p1" not in saved
    # p2 merges its own prior Wounded with the combat-gained Exhausted.
    assert {c["type"] for c in saved["p2"]} == {"wounded", "exhausted"}


# --- loot + currency distribution (M18 story-003) ---

_LOOT_TABLE_ID = "s003_mp_loot_table"
_ITEM_ID = "s003_mp_item"
_SILVER_PER_GOLD = 10

# Pinned deterministic output of the SOLO victory path at seed 1234 (2 humanoid enemies, a 0.6
# drop-chance loot table). Captured from the pre-refactor roll order; the roll/distribute refactor
# must leave the RNG consumption sequence — and therefore these values — byte-identical.
_SEEDED_SOLO_GOLD = 1.1
_SEEDED_SOLO_ITEMS = ["s003_mp_item"]


def _loot_enemy(pid: str, *, category: str = "humanoid", role: str = "standard", level: int = 5) -> CombatParticipant:
    return CombatParticipant(
        id=pid,
        name=pid,
        type="enemy",
        initiative=8,
        hp_current=0,
        hp_max=7,
        ac=13,
        is_fallen=True,
        category=category,
        role=role,
        level=level,
        loot_table_id=_LOOT_TABLE_ID,
    )


def _content_stub(drops: list[dict]) -> MagicMock:
    async def _get(loot_table_id: str) -> dict | None:
        return {"id": _LOOT_TABLE_ID, "drops": drops} if loot_table_id == _LOOT_TABLE_ID else None

    content = MagicMock()
    content.get_loot_table = AsyncMock(side_effect=_get)
    return content


def _pricing_stub() -> MagicMock:
    pricing = MagicMock()
    pricing.get_economy_pricing = AsyncMock(return_value={"silver_per_gold": _SILVER_PER_GOLD})
    return pricing


async def _run_victory(session, cs, *, rng, drops, gold_by_id=None):
    """Drive the victory path with mock DI. Returns (end_data, mutations, queries, sink)."""
    db_mutations_conditions.read_player_conditions = AsyncMock(return_value=[])  # type: ignore[assignment]
    db_mutations_conditions.save_player_conditions = AsyncMock()  # type: ignore[assignment]
    mutations = AsyncMock()
    queries = AsyncMock()
    gold_by_id = gold_by_id or {}
    queries.get_player = AsyncMock(
        side_effect=lambda pid, conn=None, for_update=False: {"gold": gold_by_id.get(pid, 0)}
    )
    queries.get_player_inventory = AsyncMock(return_value=[])
    sink = EventSink()
    end_data = await _end_combat_db(
        session,
        cs,
        "victory",
        mutations=mutations,
        queries=queries,
        conn=MagicMock(),
        sink=sink,
        content=_content_stub(drops),
        pricing=_pricing_stub(),
        rng=rng,
    )
    return end_data, mutations, queries, sink


def _victory_cs(enemies: list[CombatParticipant], players: list[str]) -> CombatState:
    parts = [
        CombatParticipant(id=pid, name=pid, type="player", initiative=15, hp_current=20, hp_max=20, ac=14)
        for pid in players
    ] + enemies
    return CombatState(
        combat_id="c1",
        participants=parts,
        initiative_order=[p.id for p in parts],
        round_number=2,
        current_turn_index=0,
        location_id="loc1",
    )


async def test_solo_victory_loot_currency_unchanged_seeded_regression():
    # RNG-sequence guard (the FakeRng constants can't catch a reordering): a SOLO victory with a
    # real seeded Random must produce a byte-identical haul before and after the roll/distribute
    # refactor. The pinned values below were captured from the pre-refactor path with seed 1234.
    session = SessionData(player_id="p1", location_id="loc1", room=None)
    cs = _victory_cs(
        [_loot_enemy("g1"), _loot_enemy("g2", role="elite")],
        ["p1"],
    )
    drops = [{"item_id": _ITEM_ID, "chance": 0.6, "quantity": 2}]
    end_data, _m, _q, sink = await _run_victory(session, cs, rng=random.Random(1234), drops=drops)

    # Pinned deterministic output (seed 1234) — reordering the currency/loot rolls changes these.
    assert end_data["currency_gold"] == pytest.approx(_SEEDED_SOLO_GOLD)
    assert [d["item_id"] for d in end_data["loot"]] == _SEEDED_SOLO_ITEMS
    # Solo: exactly one CURRENCY_GAINED for the primary.
    currency_events = [e for e in sink.captured if e.event_type == E.CURRENCY_GAINED]
    assert len(currency_events) == 1
    assert currency_events[0].payload["player_id"] == "p1"


async def test_two_pc_victory_rounds_robin_loot_ascending_seat():
    # Shared pool, round-robin across members in ascending player_id seat order: item 0 -> p1,
    # item 1 -> p2, item 2 -> p1 ...
    session = _two_pc_session()
    cs = _victory_cs([_loot_enemy("g1")], ["p1", "p2"])
    # Force 3 drops from the single enemy so distribution wraps.
    drops = [
        {"item_id": "sword", "chance": 1.0, "quantity": 1},
        {"item_id": "shield", "chance": 1.0, "quantity": 1},
        {"item_id": "potion", "chance": 1.0, "quantity": 1},
    ]
    _end, mutations, _q, _sink = await _run_victory(session, cs, rng=_AllHitRng(), drops=drops)

    grants = [(c.args[0], c.args[1]) for c in mutations.add_inventory_item.await_args_list]
    assert grants == [("p1", "sword"), ("p2", "shield"), ("p1", "potion")]


async def test_two_pc_victory_currency_party_multiplier_split_and_lock_order():
    # Currency: total silver * multiplier(2)=1.5, split evenly; each member gets its own
    # CURRENCY_GAINED; the FOR UPDATE gold locks are acquired in ascending player_id order.
    session = _two_pc_session()
    cs = _victory_cs([_loot_enemy("g1", category="humanoid", role="standard", level=5)], ["p1", "p2"])
    drops: list[dict] = []  # no items; isolate currency
    end_data, mutations, queries, sink = await _run_victory(
        session, cs, rng=_FixedCurrencyRng(silver=20), drops=drops, gold_by_id={"p1": 0, "p2": 0}
    )

    # base 20 silver * 1.5 = 30 silver total; /2 = 15 silver each; /10 spg = 1.5 gold each.
    gold_calls = {c.args[0]: c.args[1] for c in mutations.update_player_gold.await_args_list}
    assert gold_calls == {"p1": pytest.approx(1.5), "p2": pytest.approx(1.5)}
    # aggregate reported to the DM is the summed party haul (3.0 gold).
    assert end_data["currency_gold"] == pytest.approx(3.0)
    # one CURRENCY_GAINED per member.
    currency_ids = [e.payload["player_id"] for e in sink.captured if e.event_type == E.CURRENCY_GAINED]
    assert currency_ids == ["p1", "p2"]
    # FOR UPDATE gold locks acquired in ascending player_id order (deadlock-free SSOT).
    lock_order = [c.args[0] for c in queries.get_player.await_args_list if c.kwargs.get("for_update")]
    assert lock_order == ["p1", "p2"]


class _AllHitRng(random.Random):
    """Every drop-chance gate passes; dice read 1 (quantity math untouched here)."""

    def random(self) -> float:
        return 0.0

    def randint(self, a: int, b: int) -> int:
        return 1


class _FixedCurrencyRng(random.Random):
    """Pins the humanoid base currency roll to a fixed silver value (tier*1d6); die chosen so
    tier(level5)=2 * die = silver."""

    def __init__(self, silver: int):
        super().__init__()
        self._die = silver // 2  # tier 2 -> 2 * die = silver

    def random(self) -> float:
        return 0.0

    def randint(self, a: int, b: int) -> int:
        return self._die
