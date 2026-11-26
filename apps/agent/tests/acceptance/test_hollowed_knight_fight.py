"""The Knight's rise and armed blade survive real tool holds and Postgres reloads."""

import json
import random
from datetime import UTC, datetime
from typing import cast
from unittest.mock import patch

import asyncpg
import pytest
from acceptance._catalog_cutover_helpers import assert_strength
from acceptance.mawling_harness import MawlingHarness
from livekit.agents import Agent
from sample_fixtures import CONTENT_ROOT, published_payloads

import check_resolution_attack
import check_resolution_save
import combat_hollow_death
import conditions
import db_queries
import dice
import event_types as E
from combat_spatial import distance
from creation_rules import build_character_data
from progression_tools import _award_xp_core
from rules_engine import XP_FOR_LEVEL
from weapon_proficiency import PROFILE_FIELDS


async def player_row(pid, *, conn=None):
    row = await db_queries.get_player(pid, conn=conn)
    assert row is not None
    return row


@pytest.fixture
def mock_combat_agent_factory():
    return None


class KnightFight(MawlingHarness):
    async def start_knight(self):
        self.template = next(
            r
            for r in json.loads((CONTENT_ROOT / "content/encounter_templates.json").read_text())
            if r["id"] == "hollow_knight_boss"
        )
        level = self.template["recommended_party_level"]
        assert (level, self.template["difficulty"], self.template["recommended_party_size"]) == (14, "hard", 2)
        catalog = {r["id"]: r for r in json.loads((CONTENT_ROOT / "content/creatures.json").read_text())}
        assert_strength(self.template, catalog)
        await self.prepare((level,) * 4, companion=None)
        self.location = "knight_fight_location"
        await self.pool.execute(
            "INSERT INTO locations(id,data) VALUES($1,$2::jsonb)",
            self.location,
            json.dumps({"region": "ashmark", "terrain": "village"}),
        )
        self.sd.location_id = self.location
        for index, pid in enumerate(self.players):
            cls = "cleric" if index == 3 else "rogue" if index == 0 else "warrior"
            row = build_character_data(
                f"Knight challenger {index}", "human", cls, None, "", created_at=datetime(2026, 11, 18, tzinfo=UTC)
            )
            item_id = {"rogue": "hollow_edge_blade", "cleric": "warhammer_common"}.get(cls, "blade_of_the_ashmark")
            item = json.loads(await self.pool.fetchval("SELECT data FROM items WHERE id=$1", item_id))
            effect = next(e for e in item["effects"] if e["type"] == "weapon")
            row["equipment"]["main_hand"] = {
                "id": item_id,
                "name": item["name"],
                **{field: item[field] for field in PROFILE_FIELDS},
                "damage": item["damage_dice"],
                "damage_type": effect["damage_type"],
                "properties": effect["properties"],
                "magical": True,
            }
            row.update(player_id=pid, location_id=self.location)
            await self.pool.execute("UPDATE players SET data=$2::jsonb WHERE player_id=$1", pid, json.dumps(row))
            async with self.pool.acquire() as conn, conn.transaction():
                await _award_xp_core(
                    player_id=pid,
                    player=row,
                    amount=XP_FOR_LEVEL[level],
                    reason="Knight fight",
                    conn=cast(asyncpg.Connection, conn),
                    pending_events=[],
                )
            row = await player_row(pid)
            for key in ("hp", "stamina", "focus"):
                if key in row:
                    row[key]["current"] = row[key]["max"]
            await self.pool.execute("UPDATE players SET data=$2::jsonb WHERE player_id=$1", pid, json.dumps(row))
        discovery = await self.command("query_info", {"kind": "creature"})
        summary = next(r for r in discovery["encounter_templates"] if r["id"] == self.template["id"])
        assert summary["recommended_party_size"] == 2
        result = await self.command("enter_mode", {"mode": "combat", "encounter_id": self.template["id"]})
        self.roster = result["participants"]
        assert self.sd.combat_state is not None
        self.combat_id = self.sd.combat_state.combat_id
        self.packets = []
        self.holds_after_rise = 0
        self.armed_reloads = 0
        self.rises = []
        self.failures = []
        self.command_hits = 0
        self.hollowed_received = set()
        self.post_roll_reloads = 0
        self.knight_death_awards = []
        self.destructions = 0
        self.rounds = 0

    async def command(self, name, arguments, **kwargs):
        count = len(self.model.receipts)
        prior = self.sd.combat_state
        previous_conditions = (
            {p.name: conditions.hollowed_stage(p.conditions) for p in prior.participants} if prior else {}
        )
        round_number = prior.round_number if prior else 0
        result = await super().command(name, arguments, **kwargs)
        assert len(self.model.receipts) == count + 1
        if name != "resolve_phase":
            return result
        packets = [{"_round": round_number, **p, **s} for p in result.get("packets", []) for s in p.get("attacks", [p])]
        self.packets.extend(packets)
        for packet in packets:
            if (
                packet.get("actor_id", "").startswith("mawling_")
                and "attack_total" in packet
                and packet["attack_total"] - packet["roll"] == 7
            ):
                self.command_hits += 1
            if packet.get("critical_save", {}).get("success") is False:
                assert packet["critical_save"]["dc"] == 16
                assert packet["condition_inflicted"] == "hollowed"
                self.hollowed_received.add(packet["target"])
            fortitude = packet.get("unholy_fortitude")
            if fortitude:
                if fortitude["success"]:
                    assert fortitude["narration_cue"] == "The armor crashes down. Then it scrapes upright again."
                    assert not packet["target_fallen"] and packet["context"] != "killing_blow"
                    assert self.destructions == 0
                    self.rises.append(fortitude)
                else:
                    assert packet["target_fallen"]
                    self.failures.append(fortitude)
        if self.sd.combat_state is not None:
            state = await self.reload()
            knight = state.get_participant("hollowed_knight")
            assert knight is not None and knight.unholy_fortitude is not None
            if knight.pending_preparation:
                self.armed_reloads += 1
            if state.held_actions and state.held_actions[0].get("roll"):
                held = state.held_actions[0]["roll"]["attack_result"]
                if held.get("rider_damage", 0) > 0:
                    self.post_roll_reloads += 1
            for packet in packets:
                if packet.get("critical_save", {}).get("success") is False:
                    target = next(p for p in state.participants if p.name == packet["target"])
                    if previous_conditions[target.name] == 0:
                        assert conditions.hollowed_stage(target.conditions) == 1
            assert "hollowed_knight" not in result.get("death_saves_due", [])
            if self.rises and state.held_actions:
                self.holds_after_rise += 1
                assert knight.unholy_fortitude["dc"] == 10 + 5 * len(self.rises)
            if fortitudes := [p["unholy_fortitude"] for p in packets if "unholy_fortitude" in p]:
                assert knight.unholy_fortitude["dc"] == 10 + 5 * len(self.rises)
                if fortitudes[-1]["success"]:
                    assert knight.hp_current == 1 and not knight.hollow_death_resolved and not knight.is_dead, (
                        knight.hp_current,
                        packets,
                    )
                else:
                    assert knight.is_dead and knight.hollow_death_resolved
                    assert any(
                        p.type == "enemy" and not p.is_fallen for p in state.participants if p.id.startswith("mawling_")
                    )
        return result

    async def fight(self):
        for _turn in range(100):
            state = await self.reload()
            self.rounds = state.round_number
            living = [p for p in state.participants if not p.is_fallen and not p.is_dead]
            allies = [p for p in living if p.type == "player"]
            foes = [p for p in living if p.type == "enemy"]
            if not allies:
                for actor in state.participants:
                    if actor.type == "player" and actor.is_fallen and not actor.is_dead:
                        await self.command("request_death_save", {"player_id": actor.id})
                if self.sd.combat_state is None:
                    return
                self.roster = self.last_result["participants"]
                continue
            assert foes
            manifest = {p["id"]: p["executable_actions"] for p in self.roster}
            declarations = []
            for actor in living:
                target = max(allies, key=lambda p: p.hp_current) if actor.type == "enemy" else foes[0]
                assert state.spatial is not None
                positions = state.spatial["positions"]
                origin, destination = positions[actor.id], positions[target.id]
                gap = distance(origin, destination)
                if gap > 5:
                    fraction = min(state.spatial["speeds"][actor.id] - 0.01, gap - 4) / gap
                    declarations.append(
                        {
                            "reshape": [],
                            "movement_mode": "ground",
                            "kind": "move",
                            "nythera_step": False,
                            "actor_id": actor.id,
                            "destination": {k: origin[k] + (destination[k] - origin[k]) * fraction for k in origin},
                        }
                    )
                    continue
                actions = [a for a in manifest[actor.id] if a["available"]]
                if actor.id == "hollowed_knight":
                    if not any(p.get("prepared_attack") for p in self.packets):
                        action = next(a for a in actions if a["name"] == "Dissolution Strike")
                    elif not any(p.get("mark_applied") or p.get("action") == "Command Lesser" for p in self.packets):
                        action = next(a for a in actions if a["name"] == "Command Lesser")
                    else:
                        action = next(a for a in actions if a["kind"] == "multiattack")
                elif actor.type == "player":
                    blades = [p for p in self.packets if p.get("action") == "Corrupted Blade" and p.get("hit")]
                    if len(blades) < 1 or (
                        target.id == "hollowed_knight" and target.hp_current < 25 and actor.id != self.players[0]
                    ):
                        declarations.append({"reshape": [], "kind": "defend", "actor_id": actor.id})
                        continue
                    action = next(a for a in actions if a["kind"] == "attack")
                else:
                    if any(p.get("action") == "Command Lesser" for p in self.packets) or not any(
                        p.get("prepared_attack") for p in self.packets
                    ):
                        declarations.append({"reshape": [], "kind": "defend", "actor_id": actor.id})
                        continue
                    action = next(a for a in actions if a["kind"] == "attack")
                if action["declaration_type"] == "ability":
                    declaration = {
                        "kind": "ability",
                        "actor_id": actor.id,
                        "action": action["id"],
                        "targets": [target.id] if action["kind"] == "command" else [],
                        "argument_type": "",
                    }
                elif action["kind"] == "multiattack":
                    declaration = {
                        "kind": "multiattack",
                        "actor_id": actor.id,
                        "action": action["id"],
                        "strikes": [
                            {"action": s["action"], "target_id": target.id, "held_item_id": ""}
                            for s in action["strikes"]
                        ],
                    }
                else:
                    declaration = {
                        "reshape": [],
                        "quick_fingers_mode": "",
                        "quick_fingers_item": "",
                        "kind": "attack",
                        "actor_id": actor.id,
                        "action": action["id"],
                        "target_id": target.id,
                        "held_item_id": "",
                        "rider": "",
                    }
                declarations.append(declaration)
            await self.command("declare_phase", {"declarations": declarations})
            await self.drain()
            if self.sd.combat_state is None:
                return
            self.roster = self.last_result["participants"]
        pytest.fail("Knight fight did not terminate")


async def test_knight_terminal_tool_fight(reset_db_pool):
    seed = 153
    h = KnightFight()
    rng = random.Random(seed)
    knight_rng = random.Random(5)
    original_attack = check_resolution_attack.resolve_attack
    original_save = check_resolution_save.roll_participant_save
    original_death = combat_hollow_death.accrue_death
    critical_rng, fortitude_rng, initiative_rng = random.Random(1), random.Random(0), random.Random(17)

    def save(*args, **kwargs):
        if args[3] == "hollowed":
            kwargs["rng"] = critical_rng
        elif args[3] == "destruction":
            kwargs["rng"] = fortitude_rng
        return original_save(*args, **kwargs)

    async def death(session, state, target, **kwargs):
        if target.id != "hollowed_knight":
            return await original_death(session, state, target, **kwargs)
        h.destructions += 1
        caster = next(p for p in state.participants if p.id == h.players[3])
        assert not caster.is_fallen and not caster.is_dead
        before = await player_row(caster.id, conn=kwargs["conn"])
        await original_death(session, state, target, **kwargs)
        after = await player_row(caster.id, conn=kwargs["conn"])
        h.knight_death_awards.append(after["resonance"]["current"] - before.get("resonance", {}).get("current", 0))

    def attack(*args, **kwargs):
        if args[1]["name"] == "Corrupted Blade":
            kwargs["rng"] = knight_rng
        return original_attack(*args, **kwargs)

    with (
        patch("dice.random.SystemRandom", return_value=rng),
        patch("check_resolution_attack.resolve_attack", side_effect=attack),
        patch("check_resolution_save.roll_participant_save", side_effect=save),
        patch("combat_fortitude.roll_participant_save", side_effect=save),
        patch("combat_hollow_death.accrue_death", side_effect=death),
        patch("combat_resolution.dice_roll", side_effect=lambda expr, **kw: dice.roll(expr, rng=initiative_rng)),
        patch("combat_end._build_handoff_agent", side_effect=lambda *_: Agent(instructions="Combat complete.")),
    ):
        try:
            await h.start_knight()
            await h.fight()
            persisted = [await player_row(pid) for pid in h.players]
            survivors = sum(row["hp"]["current"] > 0 for row in persisted)
            print(
                f"Knight seed={seed} (blade=5, critical-save=1, fortitude=0, initiative=17) level=14 outcome={h.last_result['outcome']} rounds={h.rounds} "
                f"survivors={survivors} Command Lesser={sum(p.get('action') == 'Command Lesser' for p in h.packets)} "
                f"Dissolution hits={sum(p.get('rider_damage', 0) > 0 for p in h.packets)} "
                f"Fortitude successes={len(h.rises)} failures={len(h.failures)}"
            )
            assert h.rises and h.rises[0]["dc"] == 10
            assert h.failures and h.failures[-1]["dc"] == 10 + 5 * len(h.rises)
            assert h.holds_after_rise and h.armed_reloads and h.post_roll_reloads
            assert h.command_hits > 0
            assert h.destructions == 1 and h.knight_death_awards == [2]
            assert h.hollowed_received
            for pid in h.players:
                row = await player_row(pid)
                if row["name"] in h.hollowed_received:
                    assert conditions.hollowed_stage(row["conditions"]) >= 1
            blades = [p for p in h.packets if p.get("composite") == "Multiattack" and "hit" in p]
            paired = [p for p in blades if p["_round"] == blades[0]["_round"]]
            assert [p["strike_index"] for p in paired] == [0, 1]
            assert len({p["execution_id"] for p in paired}) == 2
            assert all(p["bonus_damage"] > 0 for p in blades if p["hit"])
            assert any(p.get("rider_damage", 0) > 0 for p in h.packets)
            assert any(p.get("critical_save", {}).get("dc") == 16 for p in h.packets)
            assert await h.pool.fetchval("SELECT 1 FROM combat_instances WHERE combat_id=$1", h.combat_id) is None
            assert not h.sd.in_combat
            ended = [p for p in published_payloads(h.sd.room) if p["type"] == E.COMBAT_ENDED]
            assert len(ended) == 1
        finally:
            if hasattr(h, "session"):
                await h.close()
            if hasattr(h, "location"):
                await h.pool.execute("DELETE FROM locations WHERE id=$1", h.location)
