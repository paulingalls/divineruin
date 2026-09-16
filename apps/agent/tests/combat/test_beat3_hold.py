"""Beat 3 holds the enemy blows behind two real reaction windows (M29, story-016).

decision 46 (game_mechanics_decisions.md:61) and game_mechanics_combat.md:182-187 specify the
loop: the DM narrates each enemy action, PAUSES for a reaction window, and "the engine holds enemy
damage until each reaction window closes". Sprint 45 shipped the opposite — every packet, ally and
enemy alike, resolved in one transaction, so the enemy's blow was written to hp_current before the
DM said a word. These are the guards for the restored model.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from combat._helpers import _resolution_state, _resolve_deps, _resolve_round
from sample_fixtures import make_context

import abilities
import combat_turn
import reaction_spend
from session_data import CombatParticipant


def _resonance_deps(**kwargs):
    """_resolve_deps plus a stubbed resonance module: the WRAP's per-member decay writes through
    it, and the DI bundle's fake conn is not a real connection."""
    deps = _resolve_deps(**kwargs)
    deps["resonance_mutations"] = MagicMock(update_player_resonance=AsyncMock())
    return deps


def _ctx_at_resolution(*, player_hp=25, enemy_hp=7, reactions=True):
    """A phase at the RESOLUTION beat with one ally attack and one enemy attack declared."""
    ctx = make_context()
    state = _resolution_state(player_hp=player_hp, enemy_hp=enemy_hp)
    player = state.get_participant("player_1")
    assert player is not None
    player.has_reaction_ability = True
    state.reactions_available = {"player_1": reaction_spend.unspent()} if reactions else {}
    ctx.userdata.combat_state = state
    return ctx


def _p(ctx, participant_id="player_1"):
    """Re-read a participant AFTER a call: resolve_phase adopts a deep-copied state each time, so
    a reference captured before the call is stale and every assertion on it passes vacuously."""
    return ctx.userdata.combat_state.get_participant(participant_id)


async def _call(ctx, deps) -> dict:
    result = await combat_turn._resolve_phase_impl(ctx, **deps)
    assert not isinstance(result, tuple), "combat ended unexpectedly"
    return json.loads(result)


class TestTheHold:
    """AC1 — the resolution beat resolves the ALLY band only."""

    @pytest.mark.asyncio
    async def test_the_resolution_beat_resolves_allies_and_writes_no_enemy_damage(self):
        ctx = _ctx_at_resolution(player_hp=25, enemy_hp=7)
        deps = _resolve_deps(damage=3)

        await _call(ctx, deps)

        cs = ctx.userdata.combat_state
        assert cs.get_participant("goblin_scout_1").hp_current == 4  # the ally swing landed
        assert cs.get_participant("player_1").hp_current == 25  # the enemy blow did NOT
        assert cs.beat == "narration"
        assert [h["actor_id"] for h in cs.held_actions] == ["goblin_scout_1"]
        # No player HP write of ANY kind reached the DB in the ally commit.
        deps["mutations"].update_player_hp.assert_not_awaited()
        deps["mutations"].save_combat_state.assert_awaited_once()  # commit 1 happened

    @pytest.mark.asyncio
    async def test_the_held_action_carries_its_declaration_unrolled(self):
        """The hold is a QUEUE of pending turns, not a discarded one: the declaration survives
        and no roll has been made yet (AC7's "still pending" is this shape)."""
        ctx = _ctx_at_resolution()
        await _call(ctx, _resolve_deps())

        held = ctx.userdata.combat_state.held_actions[0]
        assert held["roll"] is None
        assert held["declaration"]["action"] == "Scimitar"
        assert held["declaration"]["target_id"] == "player_1"


class TestTheTwoWindows:
    """AC2/AC4 — pause, roll, pause, and the DM reads the window out of `next`."""

    @pytest.mark.asyncio
    async def test_pause_roll_pause_over_one_enemy_swing(self):
        """The beat is pause -> roll -> pause. The ally band commits FIRST and on its own (AC1),
        so the enemy blow cannot have landed when the DM starts narrating Beat 3; each subsequent
        call steps the held queue by one stage."""
        ctx = _ctx_at_resolution(player_hp=25)
        ctx.userdata.combat_state.pending_declarations["goblin_scout_1"]["action"] = "sCiMiTaR"
        deps = _resolve_deps(damage=3)

        # Call 1: the ally band resolves and commits. Nothing is held open yet.
        r0 = await _call(ctx, deps)
        assert r0["next"] == {"phase": "narration", "verbs": ["resolve_phase"], "waiting_on": None}
        assert _p(ctx).hp_current == 25

        # Call 2: the machine stops on the PRE-ROLL window.
        r1 = await _call(ctx, deps)
        w1 = r1["next"]["waiting_on"]
        assert r1["next"]["phase"] == "narration"
        assert w1 is not None
        assert w1["window_id"] == ctx.userdata.combat_state.open_window["id"]
        assert w1["stage"] == "pre_roll"
        assert w1["actor_id"] == "goblin_scout_1"
        assert w1["target_id"] == "player_1"
        assert w1["action"] == "Scimitar"
        assert set(w1["triggers"]) <= abilities.REACTION_WINDOWS
        assert "on_targeted" in w1["triggers"] and "on_enemy_action" in w1["triggers"]
        assert _p(ctx).hp_current == 25
        assert ctx.userdata.combat_state.held_actions[0]["roll"] is None

        # Call 2: the roll happens; the damage is STILL held (this window is pre-damage).
        r2 = await _call(ctx, deps)
        w2 = r2["next"]["waiting_on"]
        assert w2 is not None
        assert w2["stage"] == "post_roll"
        assert w2["window_id"] != w1["window_id"]
        assert w2["action"] == "Scimitar"
        assert "on_hit" in w2["triggers"]  # the seeded resolver hits
        assert _p(ctx).hp_current == 25
        assert ctx.userdata.combat_state.held_actions[0]["roll"]["attack_result"]["hit"] is True

        # Call 3: the damage lands and the phase wraps.
        r3 = await _call(ctx, deps)
        assert _p(ctx).hp_current == 22
        assert r3["beat"] == "declaration"
        assert r3["round"] == 2
        assert r3["next"] == {"phase": "declaration", "verbs": ["declare_phase"], "waiting_on": None, "cannot_act": []}
        assert ctx.userdata.combat_state.held_actions == []
        assert ctx.userdata.combat_state.open_window is None

    @pytest.mark.asyncio
    async def test_a_missed_swing_opens_the_miss_window_not_the_hit_window(self):
        from combat._helpers import _damage_resolver

        ctx = _ctx_at_resolution()
        deps = _resolve_deps()
        # An ally resolver that hits, then a miss for the held enemy swing.
        miss = _damage_resolver(0)
        miss.resolve_attack.side_effect = None
        from check_resolution_attack import AttackResult

        miss.resolve_attack.return_value = AttackResult(
            hit=False,
            roll=3,
            attack_modifier=3,
            attack_total=6,
            target_ac=14,
            damage=0,
            damage_type="slashing",
            target_hp_remaining=25,
            target_killed=False,
            narrative_hint="Wide.",
        )

        await _call(ctx, deps)  # the ally commit
        await _call(ctx, deps)  # the pre-roll window
        deps["resolver"] = miss
        r2 = await _call(ctx, deps)  # roll (a miss) + post-roll window

        triggers = r2["next"]["waiting_on"]["triggers"]
        assert "on_enemy_miss" in triggers
        assert "on_hit" not in triggers

    @pytest.mark.asyncio
    async def test_the_window_id_is_only_reachable_through_next(self):
        """constraint 6 / AC4's fault-injection, as a positive claim: everything the DM needs to
        close the window — the phase, the legal verbs, the window id — is in `next`, structured.
        A window id the DM has to mine out of prose is not shipped."""
        ctx, deps = _ctx_at_resolution(), _resolve_deps()
        await _call(ctx, deps)  # the ally commit
        r1 = await _call(ctx, deps)  # the pre-roll window

        assert set(r1["next"]) == {"phase", "verbs", "waiting_on"}
        assert set(r1["next"]["waiting_on"]) == {
            "window_id",
            "stage",
            "actor_id",
            "target_id",
            "triggers",
            "action",
            "reactions",
        }
        assert "resolve_phase" in r1["next"]["verbs"]

    @pytest.mark.asyncio
    async def test_non_pool_interact_names_no_held_action(self):
        ctx = _ctx_at_resolution()
        ctx.userdata.combat_state.pending_declarations["goblin_scout_1"] = {
            "type": "interact",
            "action": "Taunt",
            "target_id": "player_1",
        }
        deps = _resolve_deps()

        await _call(ctx, deps)
        result = await _call(ctx, deps)

        assert result["next"]["waiting_on"]["action"] is None


class TestTheReactionBudgetGate:
    """Missing, spent, and fallen-player budgets cannot hold the beat open."""

    @pytest.mark.asyncio
    async def test_no_window_opens_when_no_reaction_is_available(self):
        ctx = _ctx_at_resolution(player_hp=25, reactions=False)
        deps = _resolve_deps(damage=3)

        r1 = await _call(ctx, deps)
        assert r1["next"]["waiting_on"] is None
        assert ctx.userdata.combat_state.open_window is None
        assert ctx.userdata.combat_state.get_participant("player_1").hp_current == 25

        # No window opens, so the held pass resolves the blow straight through — no pause.
        r2 = await _call(ctx, deps)
        assert r2["next"]["waiting_on"] is None
        assert ctx.userdata.combat_state.get_participant("player_1").hp_current == 22
        assert r2["beat"] == "declaration"

    @pytest.mark.asyncio
    async def test_a_spend_record_reopens_no_window(self):
        """THE TRUTHINESS TRAP. The gate used to read `reactions_available.get(pid, False)` as a
        boolean, and a spend RECORD is a truthy object — so the naive reshape leaves a spent
        reaction still holding the beat, opening a window the party cannot consume for the rest of
        the round. The gate has to read the record's spent-ness.

        Fault-inject by reverting pause_allowed to `.get(p.id, False)` truthiness."""
        ctx = _ctx_at_resolution()
        cs = ctx.userdata.combat_state
        cs.reactions_available = {
            "player_1": reaction_spend.spend(
                "rogue_uncanny_dodge", {"id": "r1-0-pre_roll", "stage": "pre_roll"}, held_seq=0
            )
        }
        assert cs.reactions_available["player_1"], "the record must be truthy for this to bite"
        deps = _resolve_deps()
        await _call(ctx, deps)  # the ally commit

        r1 = await _call(ctx, deps)

        assert r1["next"]["waiting_on"] is None

    @pytest.mark.asyncio
    async def test_a_fallen_players_stale_availability_does_not_hold_the_beat(self):
        """A downed player cannot react, so their leftover True must not pause a whole round.

        The blow lands on a SECOND, standing player: felling the one the enemy swings at makes the
        held action wasted, which suppresses the window for a different reason entirely and leaves
        `pause_allowed`'s is_fallen clause certified by nothing (constraint 1)."""
        ctx = _ctx_at_resolution()
        cs = ctx.userdata.combat_state
        cs.participants.append(
            CombatParticipant(
                id="player_2",
                name="Bren",
                type="player",
                initiative=8,
                hp_current=20,
                hp_max=20,
                ac=14,
                has_reaction_ability=True,
            )
        )
        cs.initiative_order.append("player_2")
        cs.get_participant("player_1").is_fallen = True
        # player_1 is down carrying a stale unspent record; player_2 stands but has already spent.
        cs.reactions_available = {
            "player_1": reaction_spend.unspent(),
            "player_2": reaction_spend.spend(
                "rogue_uncanny_dodge", {"id": "r1-0-pre_roll", "stage": "pre_roll"}, held_seq=0
            ),
        }
        cs.pending_declarations["goblin_scout_1"]["target_id"] = "player_2"
        deps = _resolve_deps()
        await _call(ctx, deps)  # the ally commit

        r1 = await _call(ctx, deps)

        assert r1["next"]["waiting_on"] is None
        # The blow still landed — the beat ran on, it did not stall on a no-op.
        assert _p(ctx, "player_2").hp_current == 17


class TestTrunkIdentityAndOneWrap:
    """AC6 — an enemy action nobody reacts to resolves exactly as on trunk, and the phase wraps
    ONCE. Scoped honestly: identity holds WITHIN a band. The ally-first reorder (see
    TestBandOrdering) moves `first_attack_resolved` and `enemies_remaining` between bands, so a
    cross-band dramatic promotion can legitimately land on the other side of the round."""

    @pytest.mark.asyncio
    async def test_an_unreacted_enemy_action_resolves_and_wraps_exactly_once(self):
        ctx = _ctx_at_resolution(player_hp=25, enemy_hp=20, reactions=False)
        deps = _resonance_deps(damage=3)
        member = ctx.userdata.party.members[0]
        member.resonance.current = 5

        result = await _resolve_round(ctx, **deps)

        assert ctx.userdata.combat_state.get_participant("player_1").hp_current == 22
        assert ctx.userdata.combat_state.get_participant("goblin_scout_1").hp_current == 17
        assert result["round"] == 2
        assert {p["actor_id"] for p in result["packets"]} == {"player_1", "goblin_scout_1"}
        enemy_packet = next(p for p in result["packets"] if p["actor_id"] == "goblin_scout_1")
        assert enemy_packet["hit"] is True
        assert enemy_packet["damage"] == 3
        assert enemy_packet["target"] == "Kael"
        # ONE wrap: Resonance decayed a single step, not once per commit.
        assert member.resonance.current == 4

    @pytest.mark.asyncio
    async def test_the_wrap_commits_once_even_when_the_round_pauses_twice(self):
        ctx = _ctx_at_resolution(player_hp=25, enemy_hp=20)
        deps = _resonance_deps(damage=3)
        member = ctx.userdata.party.members[0]
        member.resonance.current = 5

        result = await _resolve_round(ctx, **deps)

        assert result["round"] == 2
        assert member.resonance.current == 4  # decayed once across THREE resolve_phase calls


class TestUntargetedHeldActions:
    """An enemy declaration that names NO target opens no window.

    declare_phase accepts defend/interact/maneuver/retreat for any actor, enemies included, and
    the DM is told to cover "every enemy that acts this round". Every trigger the pre-roll window
    emits claims someone was targeted, so pausing on a braced enemy would ship a descriptor that
    contradicts itself — triggers announcing a blow beside a null target_id — and story-018 would
    spend the round's one reaction on it (constraint 6)."""

    @pytest.mark.asyncio
    async def test_a_held_enemy_defend_never_pauses_and_still_resolves(self):
        ctx = _ctx_at_resolution(player_hp=25, enemy_hp=20)
        cs = ctx.userdata.combat_state
        cs.pending_declarations["goblin_scout_1"] = {"type": "defend"}
        deps = _resonance_deps(damage=3)

        await _call(ctx, deps)  # the ally commit
        assert [h["actor_id"] for h in ctx.userdata.combat_state.held_actions] == ["goblin_scout_1"]

        # The very NEXT call must drain and wrap. Asserting on the end of the round instead would
        # be vacuous — the round always ends with no window open, however many it paused on.
        result = await _call(ctx, deps)

        assert result["next"]["waiting_on"] is None
        assert result["beat"] == "declaration"
        # It still POPPED through the ordinary resolver — no window, but no dropped turn either.
        goblin_packet = next(p for p in result["packets"] if p["actor_id"] == "goblin_scout_1")
        assert goblin_packet["declaration_type"] == "defend"
        assert _p(ctx).hp_current == 25  # a braced enemy struck nobody
        assert ctx.userdata.combat_state.held_actions == []


class TestBandOrdering:
    """D4, pinned rather than discovered in a capstone diff. Beats 2/3 (gm_combat:154-187) resolve
    the ally band fully before any enemy acts; initiative still orders WITHIN each band. Trunk
    interleaved the two and let a higher-initiative enemy drop the player before their declared
    swing landed — that cross-band pre-emption is what the hold abolishes."""

    @pytest.mark.asyncio
    async def test_a_higher_initiative_enemy_no_longer_preempts_the_player(self):
        ctx = _ctx_at_resolution(player_hp=3, enemy_hp=7, reactions=False)
        cs = ctx.userdata.combat_state
        cs.get_participant("goblin_scout_1").initiative = 20  # outrolls the player's 15
        cs.get_participant("player_1").initiative = 15

        r1 = await _call(ctx, _resolve_deps(damage=3))

        # On trunk the goblin's blow landed first and the player fell at 0 before swinging.
        # (This is the ally commit; the goblin's held turn has not run.)
        assert _p(ctx, "goblin_scout_1").hp_current == 4  # the ally swing landed
        assert _p(ctx).hp_current == 3  # untouched, still standing
        assert [p["actor_id"] for p in r1["packets"]] == ["player_1"]

    @pytest.mark.asyncio
    async def test_the_first_attack_dramatic_promotion_now_falls_to_the_ally_band(self):
        """The measurable consequence of the reorder (combat_packet.py:280-281 reads
        `first_attack_resolved` fresh per packet, and :329 consumes the one-shot). Ally-first
        means the opening strike of round 1 is an ALLY's, even when an enemy outrolled them."""
        ctx = _ctx_at_resolution(enemy_hp=20, reactions=False)
        cs = ctx.userdata.combat_state
        cs.get_participant("goblin_scout_1").initiative = 20
        cs.first_attack_resolved = False

        result = await _resolve_round(ctx, **_resolve_deps(damage=3))

        by_actor = {p["actor_id"]: p for p in result["packets"]}
        assert by_actor["player_1"]["context"] == "first_attack"
        assert by_actor["goblin_scout_1"]["context"] != "first_attack"


class TestWastedHeldActions:
    """A held action whose actor or target is gone never opens a window — pausing on a no-op is
    the same noise AC9 exists to prevent."""

    @pytest.mark.asyncio
    async def test_a_held_action_whose_actor_fell_to_the_ally_band_never_pauses(self):
        ctx = _ctx_at_resolution(player_hp=25, enemy_hp=3)  # the ally swing kills the goblin
        deps = _resonance_deps(damage=3)

        r0 = await _call(ctx, deps)  # the ally swing kills it; its turn is held but wasted
        assert _p(ctx, "goblin_scout_1").is_fallen is True
        assert r0["next"]["waiting_on"] is None
        assert [h["actor_id"] for h in ctx.userdata.combat_state.held_actions] == ["goblin_scout_1"]

        # The held pass pops the wasted action WITHOUT pausing on it, and the wrap ends the fight
        # in that same commit — an enemy blow (or its absence) is what ends the fight.
        result = await combat_turn._resolve_phase_impl(ctx, **deps)

        assert isinstance(result, tuple), "the wrap should have ended combat on the held pass"
        assert json.loads(result[1])["outcome"] == "victory"


class TestBeatGuards:
    @pytest.mark.asyncio
    async def test_resolve_phase_names_both_legal_beats_when_called_at_the_wrong_one(self):
        ctx = make_context()
        state = _resolution_state()
        state.beat = "declaration"
        ctx.userdata.combat_state = state

        # Both beats are now legal entry points, so the refusal must name both — a message
        # that still says "call declare_phase first" sends the DM backwards mid-round.
        with pytest.raises(Exception, match="narration"):
            await combat_turn._resolve_phase_impl(ctx, **_resolve_deps())


class TestMidWindowPersistence:
    @pytest.mark.asyncio
    async def test_every_pause_commits_so_a_reload_finds_the_window_open(self):
        """Each pause is its own commit — the window is not a bubble in memory. A crash during a
        pause reloads to the same paused state, not to a lost enemy turn (AC7's premise)."""
        ctx = _ctx_at_resolution()
        deps = _resolve_deps()
        saves: list[dict] = []
        deps["mutations"].save_combat_state = AsyncMock(side_effect=lambda cid, data, conn=None: saves.append(data))

        await _call(ctx, deps)  # the ally commit
        await _call(ctx, deps)  # pre-roll pause
        await _call(ctx, deps)  # roll + post-roll pause

        assert len(saves) == 3
        assert saves[0]["open_window"] is None  # commit 1: allies durable, enemies pending
        assert [h["actor_id"] for h in saves[0]["held_actions"]] == ["goblin_scout_1"]
        assert saves[1]["open_window"]["stage"] == "pre_roll"
        assert saves[1]["held_actions"][0]["roll"] is None
        assert saves[2]["open_window"]["stage"] == "post_roll"
        assert saves[2]["held_actions"][0]["roll"] is not None
