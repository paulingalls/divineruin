"""Ordered public gameplay commands and authoritative Choir checkpoints."""

import asyncio
import json
from collections.abc import Awaitable, Callable
from unittest.mock import patch

from acceptance._capstone_helpers import _d20
from acceptance.choir_capstone_atomicity import AtomicPhaseProbe

import check_resolution_save
import db_mutations
import db_queries
import spells
from spell_voice_rules import is_silenced

REAL_PARTICIPANT_SAVE = check_resolution_save.roll_participant_save

STEPS = (
    "entry",
    "cast-aura",
    "aura-break",
    "search",
    "redirect",
    "silence",
    "refusal",
    "silenced-command",
    "deafened",
    "deafened-command",
    "expiry",
    "destruction",
    "replay",
)


def assert_complete(checkpoints):
    assert set(checkpoints) == set(STEPS), "missing named Choir encounter checkpoint"
    assert all(checkpoints.values()), "empty Choir encounter checkpoint"


class ChoirCapstoneFlow:
    def __init__(self, diagnostic, play, events, sender):
        self.diagnostic = diagnostic
        self.play = play
        self.events = events
        self.sender = sender
        self.checkpoints = {}
        self.received = []
        self.owner = None
        self.observe_checkpoint: Callable[[str, dict], Awaitable[None]] | None = None

    @property
    def sd(self):
        return self.diagnostic.sd

    async def call(self, name, arguments, *, refusal=False):
        result = await self.diagnostic.command(name, arguments, self.play)
        assert result.is_error is refusal, result.output
        return result if refusal else json.loads(result.output)

    async def delivery(self, kind, predicate=lambda event: True, timeout=5):
        try:
            async with asyncio.timeout(timeout):
                while True:
                    payload, sender = await self.events.get()
                    assert sender == self.sender, "gameplay delivery from wrong participant"
                    event = json.loads(payload)
                    self.received.append(event)
                    if event["type"] == kind and predicate(event):
                        return event
        except TimeoutError as exc:
            raise AssertionError(f"missing Choir gameplay delivery: {kind}") from exc

    async def declare(self, action=None, enemy_action=None):
        declarations = [action or {"kind": "defend", "actor_id": self.diagnostic.player_id}]
        declarations += [enemy_action or {"kind": "defend", "actor_id": self.owner}]
        for actor in self.sd.combat_state.participants:
            if actor.type == "player" and actor.id != self.diagnostic.player_id:
                declarations.append({"kind": "defend", "actor_id": actor.id})
        await self.call("declare_phase", {"declarations": declarations})

    def ability(self, actor, name, target=None):
        return {
            "kind": "ability",
            "actor_id": actor,
            "action": name,
            "targets": [target] if target else [],
            "argument_type": "",
        }

    async def resolve(self, face=20, probe=None):
        from contextlib import nullcontext

        packets = []
        with (
            probe.writes() if probe is not None else nullcontext(),
            patch("check_resolution.dice_roll", return_value=_d20(face)),
        ):
            for _ in range(16):
                result = (
                    json.loads((await probe.command()).output)
                    if probe is not None
                    else await self.call("resolve_phase", {})
                )
                packets.extend(result.get("packets", []))
                if self.sd.combat_state is None or result.get("beat") == "declaration":
                    return {**result, "packets": packets}
        raise AssertionError("public Choir phase did not terminate")

    async def remember(self, step):
        state = await self.diagnostic.reload()
        player = await db_queries.get_player(self.diagnostic.player_id)
        assert player is not None
        assert state.choir_encounter["owner_id"] == self.owner
        self.checkpoints[step] = {
            "phase": state.choir_encounter["phase"],
            "core_hp": state.get_participant(self.owner).hp_current,
            "player_hp": state.get_participant(self.diagnostic.player_id).hp_current,
            "resonance": player.get("resonance"),
            "owner": self.owner,
            "location": state.location_id,
        }
        if self.observe_checkpoint is not None:
            await self.observe_checkpoint(step, self.checkpoints[step])
        return state

    async def run(self):
        pid = self.diagnostic.player_id
        entry = await self.call(
            "enter_mode",
            {
                "mode": "combat",
                "encounter_id": "hollow_choir",
                "encounter_description": "Familiar voices hum, each a little wrong.",
            },
        )
        self.owner = next(actor["id"] for actor in entry["participants"] if actor["type"] == "enemy")
        assert entry["choir"]["phase"] == "search" and "voice" in entry["choir"]["cue"]
        await self.delivery("combat_started")
        await self.remember("entry")
        before = await db_queries.get_player(pid)
        assert before is not None
        await self.declare(self.ability(pid, "arcane_detect_magic"))
        cast = await self.resolve()
        packet = next(packet for packet in cast["packets"] if packet.get("cast"))["cast"]
        spell = spells.get_spell("arcane_detect_magic")
        assert spell is not None
        assert packet["resonance_generated"] == spell.resonance_by_source["arcane"] + 1
        assert self.sd.member_state(pid).concentration.spell_id == "arcane_detect_magic"
        player = await db_queries.get_player(pid)
        assert player is not None
        spell = spells.get_spell("arcane_detect_magic")
        assert spell is not None
        assert player["focus"]["current"] == before["focus"]["current"] - spell.focus_cost
        await self.delivery("resonance_changed", lambda event: event["caster_id"] == pid)
        await self.remember("cast-aura")
        await self.declare()
        await self.resolve(1)
        assert self.sd.member_state(pid).concentration.spell_id is None
        await self.remember("aura-break")
        facts = (await self.call("query_info", {"kind": "combat"}))["choir"]
        action = next(action for action in facts["search_actions"] if action["skill"] == "arcana")
        assert action["dc"] == 18 and facts["search_target_id"]
        await self.declare({"kind": "interact", "actor_id": pid, "action": action["action"]})
        probe = AtomicPhaseProbe(self, "search")
        await self.resolve(probe=probe)
        assert probe.checked, "search rollback was not exercised"
        state = await self.remember("search")
        assert state.choir_encounter["phase"] == "exposed"
        facts = (await self.call("query_info", {"kind": "combat"}))["choir"]
        assert facts["core_id"] == self.owner and facts["cue"]
        await self.redirect()
        await self.declare(enemy_action=self.ability(self.owner, "Silence Void", pid))
        await self.resolve()
        state = await self.remember("silence")
        assert is_silenced(state, pid) and state.choir_silences
        before = (state.to_dict(), await db_queries.get_player(pid))
        await self.call("declare_phase", {"declarations": [self.ability(pid, "arcane_detect_magic")]}, refusal=True)
        state = await self.remember("refusal")
        assert (state.to_dict(), await db_queries.get_player(pid)) == before
        await self.legal_command("silenced-command")
        for _ in range(3):
            if not self.sd.combat_state.get_participant(self.owner).choir_suppression["active"] and not is_silenced(
                self.sd.combat_state, self.owner
            ):
                break
            await self.declare()
            await self.resolve()
        await self.declare(
            enemy_action={
                "kind": "attack",
                "actor_id": self.owner,
                "action": "Dissonant Chord",
                "target_id": pid,
                "rider": "",
            }
        )
        with patch("check_resolution_save.roll_participant_save", side_effect=self.failed_save):
            await self.resolve()
        state = await self.remember("deafened")
        actor = state.get_participant(pid)
        assert any(condition["type"] == "deafened" for condition in actor.conditions)
        assert not any(condition["type"] in ("stunned", "incapacitated") for condition in actor.conditions)
        await self.legal_command("deafened-command")
        for _ in range(4):
            if not is_silenced(self.sd.combat_state, pid):
                break
            await self.declare()
            await self.resolve()
        state = await self.remember("expiry")
        assert not is_silenced(state, pid) and not state.choir_silences
        await self.destroy()
        assert_complete(self.checkpoints)
        return self.checkpoints

    @staticmethod
    def failed_save(*args, **kwargs):
        with patch("check_resolution.dice_roll", return_value=_d20(1)):
            return REAL_PARTICIPANT_SAVE(*args, **kwargs)

    async def redirect(self):
        pid = self.diagnostic.player_id
        state = self.sd.combat_state
        core_hp, caster_hp = state.get_participant(self.owner).hp_current, state.get_participant(pid).hp_current
        await self.declare(self.ability(pid, "arcane_bolt", self.owner))
        with patch("check_resolution_save.roll_participant_save", side_effect=self.failed_save):
            probe = AtomicPhaseProbe(self, "redirect")
            result = await self.resolve(probe=probe)
            assert probe.checked, "redirect rollback was not exercised"
        cast = next(packet["cast"] for packet in result["packets"] if packet.get("cast"))
        assert cast["target_id"] == pid and cast["damage_result"]["damage"] > 0
        state = await self.remember("redirect")
        assert state.get_participant(self.owner).hp_current == core_hp
        assert state.get_participant(pid).hp_current == caster_hp - cast["damage_result"]["damage"]

    async def legal_command(self, step):
        receipt = await self.call(
            "check", {"roll": {"kind": "save", "save_type": "dexterity", "dc": 8, "effect_on_fail": "stumble"}}
        )
        await self.delivery(
            "dice_roll",
            lambda event: (
                event.get("roll_type") == "saving_throw"
                and all(event.get(key) == receipt[key] for key in ("save_type", "roll", "total"))
                and event.get("success") is (receipt["outcome"] == "success")
            ),
        )
        await self.remember(step)

    async def destroy(self):
        pid = self.diagnostic.player_id
        combat_id = self.sd.combat_state.combat_id
        before = await db_queries.get_player(pid)
        assert before is not None
        probe = AtomicPhaseProbe(self, "destruction")
        for _ in range(30):
            await self.declare(self.ability(pid, "arcane_bolt", self.owner))
            result = await self.resolve(probe=probe)
            if self.sd.combat_state is None:
                break
        else:
            raise AssertionError("Choir core survived bounded legal casts")
        assert probe.checked, "destruction rollback was not exercised"
        assert result["outcome"] == "victory" and result["choir"]["phase"] == "destroyed"
        assert await db_mutations.load_combat_state(combat_id) is None
        after = await db_queries.get_player(pid)
        assert after is not None
        assert result["xp_total"] == 3000
        assert after["xp"] - before["xp"] == result["xp_granted"] > 0
        assert after["resonance"]["current"] - before["resonance"]["current"] == 5
        await self.delivery("combat_ended")
        self.checkpoints["destruction"] = {
            "phase": "destroyed",
            "owner": self.owner,
            "xp": after["xp"],
            "resonance": after["resonance"],
        }
        if self.observe_checkpoint is not None:
            await self.observe_checkpoint("destruction", self.checkpoints["destruction"])
        refusal = await self.call(
            "enter_mode",
            {"mode": "combat", "encounter_id": "hollow_choir", "encounter_description": "Replay"},
            refusal=True,
        )
        assert "destroyed" in refusal.output and await db_queries.get_player(pid) == after
        self.checkpoints["replay"] = {"refused": True}
        if self.observe_checkpoint is not None:
            await self.observe_checkpoint("replay", self.checkpoints["replay"])
