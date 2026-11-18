"""Catalog Hollow troops fight to settlement through CLI combat tools and real dice."""

import json
import random
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from acceptance.mawling_harness import MawlingHarness
from livekit.agents import Agent
from sample_fixtures import CONTENT_ROOT, published_payloads

import check_resolution_attack
import db_queries
import dice
import event_types as E
from combat_spatial import distance
from creation_rules import build_character_data
from encounter_loot import party_reward_multiplier
from hp_scaling import calculate_max_hp
from rules_engine import XP_FOR_LEVEL, attribute_modifier, calculate_max_pools

CASES = [
    ("shadeling_cluster", 1, {"Corrosive Touch"}),
    ("ruins_mawling_pair", 2, {"Claw", "Dissolution Maw"}),
    ("hollowmoth_swarm", 3, {"Distortion Flutter"}),
    ("hollow_weaver_ambush", 5, {"Spatial Lash", "Corrosive Touch"}),
    ("hollow_mawling_pack", 5, {"Claw", "Dissolution Maw", "Lunge"}),
]


@pytest.fixture
def mock_combat_agent_factory():
    return None


class TroopFight(MawlingHarness):
    async def start_catalog(self, encounter_id, level):
        await self.prepare(levels=(level,) * (6 if encounter_id == "hollow_mawling_pack" else 4), companion=None)
        self.encounter_id = encounter_id
        self.hits = set()
        self.packets = []
        for index, pid in enumerate(self.players):
            row = build_character_data(
                f"Fighter {index}", "draethar", "warrior", None, "", created_at=datetime(2026, 11, 17, tzinfo=UTC)
            )
            hp = calculate_max_hp("warrior", level, attribute_modifier(row["attributes"]["constitution"]))
            row.update(player_id=pid, level=level, xp=XP_FOR_LEVEL[level], hp={"current": hp, "max": hp})
            maxima = calculate_max_pools(
                "warrior", level, {key: attribute_modifier(value) for key, value in row["attributes"].items()}
            )
            for key in ("stamina", "focus"):
                maximum = getattr(maxima, key)
                if maximum is not None:
                    row[key] = {"current": maximum, "max": maximum}
            await self.pool.execute("UPDATE players SET data=$2::jsonb WHERE player_id=$1", pid, json.dumps(row))
        self.before = []
        for pid in self.players:
            row = await db_queries.get_player(pid)
            assert row is not None
            self.before.append(row)
        result = await self.command("enter_mode", {"mode": "combat", "encounter_id": encounter_id})
        templates = json.loads((CONTENT_ROOT / "content/encounter_templates.json").read_text())
        self.template = next(t for t in templates if t["id"] == encounter_id)
        self.catalog = {c["id"]: c for c in json.loads((CONTENT_ROOT / "content/creatures.json").read_text())}
        self.roster = result["participants"]
        assert self.roster and all(p["executable_actions"] for p in self.roster)
        self.enemies = [p["id"] for p in self.roster if p["type"] == "enemy"]
        assert self.enemies
        assert self.sd.combat_state is not None
        self.combat_id = self.sd.combat_state.combat_id

    async def command(self, name, arguments, **kwargs):
        count = len(self.model.receipts)
        state = self.sd.combat_state
        before = {p.name: p.hp_current for p in state.participants} if state else {}
        result = await super().command(name, arguments, **kwargs)
        assert len(self.model.receipts) == count + 1
        if name != "resolve_phase":
            return result
        if self.sd.combat_state is None:
            assert result["outcome"] in ("victory", "defeat")
            return result
        packets = result["packets"]
        assert "unsupported" not in json.dumps(packets).lower()
        self.packets.extend(packets)
        for packet in packets:
            if packet.get("hit") and packet.get("damage", 0) > 0:
                target = packet["target"]
                hp = before[target]
                before[target] = max(0, hp - packet["damage"])
                if hp > 0 and packet["actor_id"] in self.enemies:
                    self.hits.add(packet["action"])
                    if packet["action"] == "Distortion Flutter":
                        authored = int(self.catalog["hollow_hollowmoth"]["attacks"][0]["damage"])
                        assert packet["damage"] == authored * (2 if packet["critical"] else 1)
        if self.sd.combat_state is not None:
            state = await self.reload()
            for actor in state.participants:
                if actor.type == "player":
                    row = await db_queries.get_player(actor.id)
                    assert row is not None
                    assert row["hp"]["current"] == actor.hp_current
                    if any(p.get("target") == actor.name and p.get("hit") for p in packets):
                        assert actor.hp_current == before[actor.name]
        return result

    async def fight(self, required):
        for turn in range(40):
            state = await self.reload()
            assert state.spatial is not None
            living = [p for p in state.participants if not p.is_fallen and not p.is_dead]
            allies = [p for p in living if p.type == "player"]
            foes = [p for p in living if p.type == "enemy"]
            assert allies and foes, (turn, self.hits, [(p.name, p.hp_current, p.is_fallen) for p in state.participants])
            positions = state.spatial["positions"]
            manifest = {p["id"]: p["executable_actions"] for p in self.roster}
            declarations = []
            for actor in living:
                target = (
                    min(allies, key=lambda p: (distance(positions[actor.id], positions[p.id]), -p.hp_current))
                    if actor.type == "enemy"
                    else foes[0]
                )
                if distance(positions[actor.id], positions[target.id]) > 5:
                    if actor.type == "enemy" and turn == 0:
                        declarations.append({"kind": "defend", "actor_id": actor.id})
                        continue
                    origin, destination = positions[actor.id], positions[target.id]
                    gap = distance(origin, destination)
                    fraction = min(state.spatial["speeds"][actor.id] - 0.01, gap - 4) / gap
                    destination = {
                        axis: origin[axis] + (destination[axis] - origin[axis]) * fraction for axis in origin
                    }
                    declarations.append({"kind": "move", "actor_id": actor.id, "destination": destination})
                    continue
                actions = [a for a in manifest[actor.id] if a["available"]]
                if actor.type == "player" and not required <= self.hits:
                    declarations.append({"kind": "defend", "actor_id": actor.id})
                    continue
                if actor.type == "enemy":
                    action = next((a for a in actions if a["name"] in required - self.hits), actions[0])
                    if "Lunge" not in required - self.hits:
                        action = next((a for a in actions if a["kind"] == "multiattack"), action)
                else:
                    action = next(a for a in actions if a["kind"] == "attack")
                declaration = {"kind": action["kind"], "actor_id": actor.id, "action": action["id"]}
                if action["kind"] == "multiattack":
                    declaration["strikes"] = [
                        {"action": strike["action"], "target_id": target.id, "held_item_id": ""}
                        for strike in action["strikes"]
                    ]
                else:
                    declaration.update(target_id=target.id, held_item_id="", rider="")
                declarations.append(declaration)
            await self.command("declare_phase", {"declarations": declarations})
            await self.drain()
            if self.sd.combat_state is None:
                break
            self.roster = self.last_result["participants"]
        else:
            pytest.fail(f"{self.encounter_id}: no terminal outcome in 40 rounds; hits={self.hits}")
        assert required <= self.hits
        assert any(p.get("moved_ft", 0) > 0 for p in self.packets)
        assert await self.pool.fetchval("SELECT 1 FROM combat_instances WHERE combat_id=$1", self.combat_id) is None
        assert not self.sd.in_combat
        ended = [p for p in published_payloads(self.sd.room) if p["type"] == E.COMBAT_ENDED]
        assert len(ended) == 1 and ended[0]["outcome"] == "victory"
        after = []
        for pid in self.players:
            row = await db_queries.get_player(pid)
            assert row is not None
            after.append(row)
        assert any(a["hp"]["current"] < b["hp"]["current"] for a, b in zip(after, self.before, strict=True))
        total_xp = sum(
            int(self.catalog[e["creature_id"]]["xp_reward"] * (0.5 if e["role"] == "minion" else 1))
            for e in self.template["enemies"]
        )
        share = int(total_xp * party_reward_multiplier(len(self.players)) / len(self.players))
        assert share > 0
        assert all(a["xp"] - b["xp"] == share for a, b in zip(after, self.before, strict=True))


@pytest.mark.parametrize("encounter_id,level,required", CASES, ids=[case[0] for case in CASES])
async def test_catalog_troop_terminal_fight(reset_db_pool, encounter_id, level, required):
    mechanics = random.Random(147)
    initiative = random.Random(17)
    expressions = []
    resolved = []
    real_attack = check_resolution_attack.resolve_attack

    def roll(expression, **kwargs):
        expressions.append(expression)
        return dice.roll(expression, rng=mechanics)

    def attack(*args, **kwargs):
        result = real_attack(*args, **kwargs)
        resolved.append((args[1]["name"], result))
        return result

    harness = TroopFight()
    with (
        patch("check_resolution.dice_roll", side_effect=roll),
        patch("check_resolution_attack.dice_roll", side_effect=roll),
        patch("combat_recharge.roll", side_effect=roll),
        patch("combat_resolution.dice_roll", side_effect=lambda expr, **kw: dice.roll(expr, rng=initiative)),
        patch("check_resolution_attack.resolve_attack", side_effect=attack),
        patch("combat_end._build_handoff_agent", side_effect=lambda *_: Agent(instructions="Combat complete.")),
    ):
        try:
            await harness.start_catalog(encounter_id, level)
            await harness.fight(required)
            assert required <= {name for name, result in resolved if result.hit and result.damage > 0}
            assert expressions
            if encounter_id == "hollowmoth_swarm":
                assert "1d1+0" in expressions
            if encounter_id == "hollow_mawling_pack":
                assert any(p.get("composite") == "Multiattack" for p in harness.packets)
        finally:
            if hasattr(harness, "session"):
                await harness.close()
