"""Public Choir tools driven by authenticated microphone turns on real LiveKit."""

import json
from types import SimpleNamespace
from typing import cast

from acceptance.choir_capstone_voice import ChoirVoiceDiagnostic, TurnModel
from acceptance.multiplayer_voice.test_guest_leaves import ToneTTS
from acceptance.seeds import seed_player_with_pools
from livekit.agents import Agent, AgentSession
from livekit.agents.testing import fake_job_context

import abilities
import db
import db_mutations
import db_queries
import spells
from mode_tools import enter_mode
from participant_lifecycle import _setup_party_join
from session_data import SessionData
from session_startup import GameplayInputOwner, gameplay_room_options


class ChoirEncounterDiagnostic(ChoirVoiceDiagnostic):
    def __init__(self, player_id):
        super().__init__(player_id)
        self.model = TurnModel([])
        self.checkpoints = {}

    async def start(self, room):
        pool = await db.get_pool()
        await reseed_choir_content(pool)
        await seed_player_with_pools(
            pool, player_id=self.player_id, class_="mage", known_spells=("arcane_bolt", "arcane_detect_magic")
        )
        player = await db_queries.get_player(self.player_id)
        assert player is not None
        from rules_engine import XP_FOR_LEVEL

        player.update(
            xp=XP_FOR_LEVEL[16],
            level=16,
            hp={"current": 150, "max": 150},
            attributes={name: 18 for name in player["attributes"]},
        )
        await pool.execute("UPDATE players SET data=$2::jsonb WHERE player_id=$1", self.player_id, json.dumps(player))
        self.sd = SessionData(player_id=self.player_id, location_id="accord_guild_hall")
        self.sd.room = room
        self.lifecycle = _setup_party_join(room, self.sd)
        self.sd.multiplayer_owner = cast(GameplayInputOwner, SimpleNamespace(lifecycle=self.lifecycle))
        self.session = AgentSession(llm=self.model, tts=ToneTTS(), max_tool_steps=5, userdata=self.sd)
        self.tts_patch.start()
        with fake_job_context(room=room):
            await self.session.start(
                room=room,
                agent=Agent(instructions="Execute the player command.", tools=[enter_mode]),
                room_options=gameplay_room_options(self.sd),
            )

    async def command(self, name, arguments, play):
        count = len(self.model.commands) + 1
        self.model.commands.append((name, arguments))
        await play()
        await self.wait_for_receipts(count)
        receipt = list(self.model.receipts.values())[-1]
        assert receipt.name == name and receipt.output.strip(), "missing public tool receipt"
        assert len(self.transcripts) == count, "command requires a separate authenticated turn"
        assert self.transcripts[-1].participant_identity == self.player_id
        assert self.transcripts[-1].generation > 0 and self.transcripts[-1].speech_events
        return receipt

    async def reload(self):
        state = self.sd.combat_state
        assert state is not None
        persisted = await db_mutations.load_combat_state(state.combat_id)
        assert persisted is not None and persisted.to_dict() == state.to_dict(), "checkpoint differs after reload"
        self.sd.combat_state = persisted
        return persisted

    async def aclose(self):
        try:
            await super().aclose()
        finally:
            if hasattr(self, "sd"):
                if self.sd.background is not None:
                    await self.sd.background.stop()
                pool = await db.get_pool()
                if self.sd.combat_state is not None:
                    await db_mutations.delete_combat_state(self.sd.combat_state.combat_id, conn=pool)
                await pool.execute("DELETE FROM players WHERE player_id=$1", self.player_id)


async def reseed_choir_content(pool):
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[4]
    sys.path.insert(0, str(root / "scripts"))
    import seed_content  # type: ignore[import-not-found]

    sources = {}
    for filename, table in (
        ("spells.json", "spells"),
        ("creatures.json", "creatures"),
        ("encounter_templates.json", "encounter_templates"),
    ):
        rows = json.loads((root / "content" / filename).read_text())
        assert rows, f"empty committed {filename}"
        sources[table] = {row["id"]: row for row in rows}
        assert len(sources[table]) == len(rows), f"duplicate committed {filename} ids"
    async with pool.acquire() as conn:
        await seed_content.seed(conn)
        for table, rows in sources.items():
            saved = {row["id"]: json.loads(row["data"]) for row in await conn.fetch(f"SELECT id, data FROM {table}")}
            assert saved and all(saved.get(key) == row for key, row in rows.items()), f"stale committed {table} content"
    await db._cache_set("encounter:hollow_choir", json.dumps(sources["encounter_templates"]["hollow_choir"]))
    await spells.load_spells()
    await abilities.load_abilities()
