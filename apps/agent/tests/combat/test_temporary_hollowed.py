"""Temporary Hollowed combat ride-along (M4.4 story-008).

Spec (gm_combat §The Hollowed Death): a Stage-2+ Hollowed player who drops to 0 HP does NOT enter
Fallen — their corpse rises as a Temporary Hollowed combatant (HP=50% of max, hits add 1d6
necrotic, immune to Charmed/Frightened/Poisoned) that takes DM turns and blocks combat-end until
destroyed. On its destruction the character enters normal Mortaen death (story-007): Hollowed
cleared, hollow_killed recorded.

Unit coverage here (rise at the death site + _wrap end-condition gating); the real-PG end-to-end
lands in the persistence test class below (AC3).
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from combat._helpers import _make_combat_state
from sample_fixtures import make_context

import combat_phase
import conditions
from check_resolution_attack import AttackResult
from combat_support import _resolve_attack_packet


def _resolver(*, damage: int, hp_remaining: int, overkill: int):
    result = AttackResult(
        hit=True,
        roll=15,
        attack_modifier=3,
        attack_total=18,
        target_ac=14,
        damage=damage,
        damage_type="slashing",
        target_hp_remaining=hp_remaining,
        target_killed=hp_remaining <= 0,
        overkill=overkill,
        narrative_hint="A killing blow.",
    )
    resolver = MagicMock()
    resolver.resolve_attack = MagicMock(return_value=result)
    return resolver


def _mocks():
    mutations = MagicMock()
    mutations.save_combat_state = AsyncMock()
    mutations.update_player_hp = AsyncMock()
    queries = MagicMock()
    queries.get_player_inventory = AsyncMock(return_value=[])
    return mutations, queries


def _hollowed(stage: int) -> list[dict]:
    conds: list[dict] = []
    for _ in range(stage):
        conds = conditions.apply_condition(conds, "hollowed")
    return conds


class TestRiseAtDeathSite:
    @pytest.mark.asyncio
    async def test_stage_2_hollowed_player_rises_instead_of_falling(self):
        ctx = make_context()
        cs = _make_combat_state()
        enemy = cs.get_participant("goblin_scout_1")
        player = cs.get_participant("player_1")
        assert enemy is not None and player is not None
        player.conditions = _hollowed(2)
        mutations, queries = _mocks()

        await _resolve_attack_packet(
            ctx.userdata,
            enemy,
            enemy.action_pool[0],
            player,
            mutations=mutations,
            queries=queries,
            resolver=_resolver(damage=player.hp_current, hp_remaining=0, overkill=0),
        )

        assert player.type == "temporary_hollowed"
        assert player.hp_current == player.hp_max // 2
        assert player.is_fallen is False
        assert player.is_dead is False
        assert any(c["type"] == "temporary_hollowed" for c in player.conditions)
        # The Hollowed condition is untouched on the echo — trigger_character_death reads it later.
        assert conditions.hollowed_stage(player.conditions) == 2
        # The echo's HP is not the player's: no player-HP write on rise.
        mutations.update_player_hp.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_stage_2_hollowed_player_rises_even_under_lethal_overkill(self):
        # Precedence guard: the rise branch is checked BEFORE the instant-death (overkill >= hp_max)
        # gate. A Stage-2+ Hollowed player struck with massive overkill must still rise as an echo,
        # never short-circuit to is_dead — the echo is what later routes through the defeat path.
        ctx = make_context()
        cs = _make_combat_state()
        enemy = cs.get_participant("goblin_scout_1")
        player = cs.get_participant("player_1")
        assert enemy is not None and player is not None
        player.conditions = _hollowed(2)
        mutations, queries = _mocks()

        await _resolve_attack_packet(
            ctx.userdata,
            enemy,
            enemy.action_pool[0],
            player,
            mutations=mutations,
            queries=queries,
            resolver=_resolver(damage=player.hp_max * 3, hp_remaining=0, overkill=player.hp_max * 2),
        )

        assert player.type == "temporary_hollowed"
        assert player.is_dead is False
        assert player.is_fallen is False
        assert player.hp_current == player.hp_max // 2

    @pytest.mark.asyncio
    async def test_stage_1_hollowed_player_falls_normally(self):
        ctx = make_context()
        cs = _make_combat_state()
        enemy = cs.get_participant("goblin_scout_1")
        player = cs.get_participant("player_1")
        assert enemy is not None and player is not None
        player.conditions = _hollowed(1)
        mutations, queries = _mocks()

        await _resolve_attack_packet(
            ctx.userdata,
            enemy,
            enemy.action_pool[0],
            player,
            mutations=mutations,
            queries=queries,
            resolver=_resolver(damage=player.hp_current, hp_remaining=0, overkill=0),
        )

        assert player.type == "player"
        assert player.is_fallen is True
        assert all(c["type"] != "temporary_hollowed" for c in player.conditions)

    @pytest.mark.asyncio
    async def test_non_hollowed_player_falls_normally(self):
        ctx = make_context()
        cs = _make_combat_state()
        enemy = cs.get_participant("goblin_scout_1")
        player = cs.get_participant("player_1")
        assert enemy is not None and player is not None
        mutations, queries = _mocks()

        await _resolve_attack_packet(
            ctx.userdata,
            enemy,
            enemy.action_pool[0],
            player,
            mutations=mutations,
            queries=queries,
            resolver=_resolver(damage=player.hp_current, hp_remaining=0, overkill=0),
        )

        assert player.type == "player"
        assert player.is_fallen is True

    @pytest.mark.asyncio
    async def test_destroyed_echo_falls(self):
        # An already-risen echo at 0 HP is destroyed (Fallen) — it does NOT re-rise.
        ctx = make_context()
        cs = _make_combat_state()
        enemy = cs.get_participant("goblin_scout_1")
        echo = cs.get_participant("player_1")
        assert enemy is not None and echo is not None
        echo.type = "temporary_hollowed"
        echo.conditions = conditions.apply_condition(_hollowed(2), "temporary_hollowed")
        echo.hp_current = echo.hp_max // 2
        mutations, queries = _mocks()

        await _resolve_attack_packet(
            ctx.userdata,
            enemy,
            enemy.action_pool[0],
            echo,
            mutations=mutations,
            queries=queries,
            resolver=_resolver(damage=echo.hp_current, hp_remaining=0, overkill=0),
        )

        assert echo.type == "temporary_hollowed"
        assert echo.is_fallen is True


class TestWrapEchoGating:
    """The pure Beat-4 wrap: a live echo blocks combat-end; a destroyed echo ends it as defeat."""

    def _state_with_echo(self, *, echo_fallen: bool, enemies_fallen: bool):
        cs = _make_combat_state(enemy_fallen=enemies_fallen)
        echo = cs.get_participant("player_1")
        assert echo is not None
        echo.type = "temporary_hollowed"
        echo.is_fallen = echo_fallen
        return cs

    def test_solo_living_echo_all_enemies_fallen_resolves_defeat(self):
        # story-005 finding 5: a solo living echo (no other players) with all enemies fallen is
        # stranded — nobody left to destroy it, no enemy to fight — so combat resolves to defeat
        # (party lost), NOT a hang. A living echo with a living enemy still blocks.
        cs = self._state_with_echo(echo_fallen=False, enemies_fallen=True)
        wrap = combat_phase._wrap(cs)
        assert wrap.combat_ended is True
        assert wrap.outcome == "defeat"

    def test_destroyed_echo_ends_combat_as_defeat(self):
        cs = self._state_with_echo(echo_fallen=True, enemies_fallen=False)
        wrap = combat_phase._wrap(cs)
        assert wrap.combat_ended is True
        assert wrap.outcome == "defeat"

    def test_no_echo_combat_behaves_normally(self):
        # Regression: an ordinary victory (all enemies fallen, no echo) is unaffected.
        cs = _make_combat_state(enemy_fallen=True)
        wrap = combat_phase._wrap(cs)
        assert wrap.combat_ended is True
        assert wrap.outcome == "victory"

    def _add_standing_ally(self, cs, *, dead=False):
        from session_data import CombatParticipant

        ally = CombatParticipant(
            id="player_2",
            name="Ally",
            type="player",
            initiative=10,
            hp_current=0 if dead else 20,
            hp_max=20,
            ac=14,
            is_dead=dead,
        )
        cs.participants.append(ally)
        cs.initiative_order.append("player_2")
        return cs

    def test_destroyed_echo_does_not_defeat_when_ally_still_stands(self):
        # M20 (399dddd57cae): destroying the echo must not end combat while a non-echo
        # ally still stands — that ally can keep fighting or revive the fallen echo.
        cs = self._state_with_echo(echo_fallen=True, enemies_fallen=False)
        self._add_standing_ally(cs)
        wrap = combat_phase._wrap(cs)
        assert wrap.combat_ended is False

    def test_destroyed_echo_ends_combat_as_defeat_when_all_non_echo_players_down(self):
        cs = self._state_with_echo(echo_fallen=True, enemies_fallen=False)
        self._add_standing_ally(cs, dead=True)
        wrap = combat_phase._wrap(cs)
        assert wrap.combat_ended is True
        assert wrap.outcome == "defeat"

    def test_destroyed_echo_with_solo_player_still_defeats(self):
        # Back-compat: no other player participants -> all([]) is True -> defeat, unchanged.
        cs = self._state_with_echo(echo_fallen=True, enemies_fallen=False)
        wrap = combat_phase._wrap(cs)
        assert wrap.combat_ended is True
        assert wrap.outcome == "defeat"

    def test_destroyed_echo_mutual_kill_resolves_defeat(self):
        # story-005 (decision mutual-ko-is-defeat): echoes destroyed + all non-echo players down +
        # all enemies fallen is a party wipe -> DEFEAT (was victory pre-story-005). The dead
        # echo-primary is still resurrected by combat_end's dead-life collector.
        cs = self._state_with_echo(echo_fallen=True, enemies_fallen=True)
        self._add_standing_ally(cs, dead=True)
        wrap = combat_phase._wrap(cs)
        assert wrap.combat_ended is True
        assert wrap.outcome == "defeat"

    def test_multi_pc_wipe_with_living_echo_and_living_enemy_blocks(self):
        # cc6fee7df67d: multi-PC — all real players down, a living echo AND a living enemy. Combat
        # blocks (not auto-defeat): the DM plays out the echo's last stand against the remaining
        # enemy; a later phase resolves it (echo destroyed -> defeat, or all enemies fall -> defeat).
        cs = self._state_with_echo(echo_fallen=False, enemies_fallen=False)  # living echo + living enemy
        self._add_standing_ally(cs, dead=True)  # the only non-echo ally is down
        wrap = combat_phase._wrap(cs)
        assert wrap.combat_ended is False

    def test_living_echo_with_all_enemies_and_allies_down_defeats_no_hang(self):
        # story-004/005 finding 3/5: a living echo blocks combat-end, but when all enemies are fallen
        # AND every non-echo ally is also down, no one is left to destroy the echo -> the party is
        # wiped -> DEFEAT (no WRAP-beat hang). A solo living echo with all enemies fallen likewise
        # resolves defeat — see test_solo_living_echo_all_enemies_fallen_resolves_defeat.
        cs = self._state_with_echo(echo_fallen=False, enemies_fallen=True)
        self._add_standing_ally(cs, dead=True)
        wrap = combat_phase._wrap(cs)
        assert wrap.combat_ended is True
        assert wrap.outcome == "defeat"


async def test_temporary_hollowed_full_path_e2e(dev_db_pool):
    """AC3 (real PostgreSQL): a Stage-2 Hollowed player dies -> the echo rises -> is destroyed ->
    the character enters Mortaen death -> resurrected with Hollowed cleared and hollow_killed
    recorded. Drives the rise/destroy through the combat engine and routes the echo-fall death
    through resurrect_on_defeat (M20 story-004: _end_combat_db reaches the same resurrection via its
    outcome-independent dead-life collector, exercised end-to-end by
    test_echo_primary_resurrected_on_victory_e2e below)."""
    import json

    import db_mutations_resurrection as dmr
    import db_queries
    import resurrection

    pool = dev_db_pool
    player_id = "s008_temp_hollowed_e2e"
    await pool.execute(
        "INSERT INTO players (player_id, data) VALUES ($1, $2::jsonb) "
        "ON CONFLICT (player_id) DO UPDATE SET data = $2::jsonb",
        player_id,
        json.dumps(
            {
                "player_id": player_id,
                "class": "warrior",
                "attributes": {"strength": 14, "charisma": 8, "constitution": 13},
                "level": 5,
                "hp": {"current": 0, "max": 40},
                "maxhp_override": 0,
                "location_id": "off_catalog_wilds",  # off-catalog -> anchor falls to starter zone
                "death_history": {"count": 0, "costs": []},
                "conditions": [{"type": "hollowed", "duration": None, "source": "veil", "stage": 2}],
            }
        ),
    )
    try:
        # --- Engine side: the player drops to 0 HP and rises as a Temporary Hollowed echo. ---
        ctx = make_context()
        cs = _make_combat_state(player_hp=8)
        enemy = cs.get_participant("goblin_scout_1")
        player = cs.get_participant("player_1")
        assert enemy is not None and player is not None
        player.conditions = [{"type": "hollowed", "duration": None, "source": "veil", "stage": 2}]
        mutations, queries = _mocks()

        await _resolve_attack_packet(
            ctx.userdata,
            enemy,
            enemy.action_pool[0],
            player,
            mutations=mutations,
            queries=queries,
            resolver=_resolver(damage=8, hp_remaining=0, overkill=0),
        )
        assert player.type == "temporary_hollowed"
        assert player.is_fallen is False
        # A live echo blocks combat-end.
        assert combat_phase._wrap(cs).combat_ended is False

        # --- Destroy the echo; the wrap now reports defeat. ---
        await _resolve_attack_packet(
            ctx.userdata,
            enemy,
            enemy.action_pool[0],
            player,
            mutations=mutations,
            queries=queries,
            resolver=_resolver(damage=player.hp_current, hp_remaining=0, overkill=0),
        )
        wrap = combat_phase._wrap(cs)
        assert wrap.combat_ended is True and wrap.outcome == "defeat"

        # --- Defeat path (what _end_combat_db runs): Mortaen death keyed on the player row. ---
        combat_cleared = bool([p for p in cs.participants if p.type == "enemy" and p.is_fallen])
        player_row = await db_queries.get_player(player_id, conn=pool)
        assert player_row is not None
        death_ctx = await resurrection.resurrect_on_defeat(player_row, combat_cleared=combat_cleared, conn=pool)

        assert death_ctx["hollow_killed"] is True
        assert death_ctx["hollowed_cleared"] is True

        revived = await db_queries.get_player(player_id, conn=pool)
        assert revived is not None
        # Hollow-killed recorded permanently, Hollowed cleared from the store, revived at the anchor.
        assert await dmr.read_hollow_killed(player_id, conn=pool) is True
        assert all(c["type"] != "hollowed" for c in (revived.get("conditions") or []))
        assert revived["location_id"] == death_ctx["anchor"]
        assert revived["hp"]["current"] == death_ctx["revive_hp"]
    finally:
        await pool.execute("DELETE FROM players WHERE player_id = $1", player_id)


async def test_echo_primary_resurrected_on_victory_e2e(dev_db_pool):
    """M20 story-004 (real PostgreSQL): a destroyed temporary_hollowed echo-primary + a surviving
    ally win the fight -> _end_combat_db resolves outcome='victory' yet still Mortaen-resurrects the
    echo-primary through its outcome-independent dead-life collector (hollow_killed recorded, Hollowed
    cleared, revived at an anchor). The living ally is untouched (no death recorded). Proves the
    character-loss fix end-to-end through the real combat-end path — not the defeat-only branch."""
    import json

    from sample_fixtures import make_context, make_mock_room

    import db_mutations
    import db_mutations_resurrection as dmr
    import db_queries
    from combat_end import _end_combat_db
    from combat_events import EventSink
    from session_data import CombatParticipant, CombatState

    pool = dev_db_pool
    primary_id = "s004_echo_primary_victory"
    ally_id = "s004_ally_survivor"

    async def _seed(pid, *, hp_current, conditions):
        await pool.execute(
            "INSERT INTO players (player_id, data) VALUES ($1, $2::jsonb) "
            "ON CONFLICT (player_id) DO UPDATE SET data = $2::jsonb",
            pid,
            json.dumps(
                {
                    "player_id": pid,
                    "class": "warrior",
                    "attributes": {"strength": 14, "charisma": 8, "constitution": 13},
                    "level": 5,
                    "hp": {"current": hp_current, "max": 40},
                    "maxhp_override": 0,
                    "location_id": "off_catalog_wilds",  # off-catalog -> anchor falls to starter zone
                    "death_history": {"count": 0, "costs": []},
                    "conditions": conditions,
                }
            ),
        )

    await _seed(
        primary_id, hp_current=0, conditions=[{"type": "hollowed", "duration": None, "source": "veil", "stage": 2}]
    )
    await _seed(ally_id, hp_current=20, conditions=[])
    try:
        session = make_context(
            primary_id, location_id="off_catalog_wilds", room=make_mock_room(), party_member_ids=[ally_id]
        ).userdata
        cs = CombatState(
            combat_id="s004_victory_combat",
            participants=[
                # The primary transformed into a Hollowed echo and was then destroyed (a dead player).
                CombatParticipant(
                    id=primary_id,
                    name="Echo",
                    type="temporary_hollowed",
                    initiative=15,
                    hp_current=0,
                    hp_max=40,
                    ac=14,
                    is_fallen=True,
                    conditions=[{"type": "hollowed", "duration": None, "source": "veil", "stage": 2}],
                ),
                # The ally survived and cleared the last enemy -> victory.
                CombatParticipant(
                    id=ally_id, name="Ally", type="player", initiative=12, hp_current=18, hp_max=20, ac=14
                ),
                CombatParticipant(
                    id="g1", name="Goblin", type="enemy", initiative=8, hp_current=0, hp_max=7, ac=13, is_fallen=True
                ),
            ],
            initiative_order=[primary_id, ally_id, "g1"],
            round_number=3,
            current_turn_index=0,
            location_id="off_catalog_wilds",
        )

        end_data = await _end_combat_db(
            session, cs, "victory", mutations=db_mutations, queries=db_queries, conn=pool, sink=EventSink()
        )

        # The echo-primary died and returned via Mortaen despite the VICTORY.
        assert end_data["death_context"] is not None
        revived = await db_queries.get_player(primary_id, conn=pool)
        assert revived is not None
        assert await dmr.read_hollow_killed(primary_id, conn=pool) is True
        assert all(c["type"] != "hollowed" for c in (revived.get("conditions") or []))
        assert revived["death_history"]["count"] == 1
        assert revived["location_id"] != "off_catalog_wilds"  # revived at a resolved anchor
        assert revived["location_id"] == end_data["death_context"]["anchor"]

        # The surviving ally is untouched — no death recorded.
        ally = await db_queries.get_player(ally_id, conn=pool)
        assert ally is not None and ally["death_history"]["count"] == 0
    finally:
        await pool.execute("DELETE FROM players WHERE player_id = ANY($1::text[])", [primary_id, ally_id])
