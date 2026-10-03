"""Inject after actual phase writes, then compare the rolled-back authoritative state."""

import asyncio
import copy
import json
from unittest.mock import patch

from livekit.agents.llm import ToolError

import db_mutations
import db_queries


class AtomicPhaseProbe:
    def __init__(self, flow, step):
        self.flow = flow
        self.step = step
        self.before = None
        self.injected = False
        self.checked = False
        self.original_save = db_mutations.save_combat_state
        self.original_delete = db_mutations.delete_combat_state

    async def snapshot(self):
        state = self.flow.sd.combat_state
        assert state is not None
        saved = await db_mutations.load_combat_state(state.combat_id)
        assert saved is not None
        return {
            "combat": saved.to_dict(),
            "players": {
                member.player_id: await db_queries.get_player(member.player_id) for member in self.flow.sd.party.members
            },
            "concentration": {member.player_id: member.concentration.spell_id for member in self.flow.sd.party.members},
            "resonance": {
                member.player_id: copy.deepcopy(member.resonance.__dict__) for member in self.flow.sd.party.members
            },
        }

    async def save(self, combat_id, data, **kwargs):
        await self.original_save(combat_id, data, **kwargs)
        phase = data["choir_encounter"]["phase"]
        actors = {actor["id"]: actor for actor in data["participants"]}
        assert self.before is not None
        previous = {actor["id"]: actor for actor in self.before["combat"]["participants"]}
        target = (
            phase == "exposed"
            if self.step == "search"
            else (
                actors[self.flow.diagnostic.player_id]["hp_current"]
                < previous[self.flow.diagnostic.player_id]["hp_current"]
            )
        )
        if not self.injected and target and kwargs.get("conn") is not None:
            self.injected = True
            raise ToolError(f"owned {self.step} failure after write")

    async def delete(self, combat_id, **kwargs):
        await self.original_delete(combat_id, **kwargs)
        if not self.injected:
            assert kwargs.get("conn") is not None
            self.injected = True
            raise ToolError("owned destruction failure after write")

    async def command(self):
        self.before = await self.snapshot()
        await self.drain_events()
        receipts = len(self.flow.diagnostic.model.receipts)
        result = await self.flow.diagnostic.command("resolve_phase", {}, self.flow.play)
        assert len(self.flow.diagnostic.model.receipts) == receipts + 1
        if self.injected and not self.checked:
            assert result.is_error and f"owned {self.step} failure after write" in result.output, (
                "wrong rollback diagnostic"
            )
            assert await self.snapshot() == self.before, "Choir phase rollback changed authoritative state"
            assert self.flow.sd.combat_state.to_dict() == self.before["combat"], "Choir rollback lost session state"
            await self.drain_events(require_transcripts=True)
            self.checked = True
            result = await self.flow.diagnostic.command("resolve_phase", {}, self.flow.play)
        assert not result.is_error, result.output
        return result

    async def drain_events(self, *, require_transcripts=False):
        await asyncio.sleep(0.1)
        while not self.flow.events.empty():
            payload, sender = self.flow.events.get_nowait()
            assert sender == self.flow.sender
            event = json.loads(payload)
            self.flow.received.append(event)
            if require_transcripts:
                assert event["type"] == "transcript_entry", "rolled-back Choir phase leaked gameplay event"

    def writes(self):
        return patch.object(
            db_mutations,
            "delete_combat_state" if self.step == "destruction" else "save_combat_state",
            self.delete if self.step == "destruction" else self.save,
        )
