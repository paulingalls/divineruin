"""Tests for TranscriptLogger."""

import os
import re
import tempfile

from dialogue_parser import DEFAULT_CHARACTER
from transcript import TranscriptLogger

TIMESTAMP_RE = re.compile(r"^\[\d{2}:\d{2}:\d{2}\] ")


class TestTranscriptLogger:
    def _make_logger(self, tmp_path: str) -> TranscriptLogger:
        log_path = os.path.join(tmp_path, "test_transcript.log")
        return TranscriptLogger(room=None, event_bus=None, log_path=log_path), log_path

    def _read_lines(self, log_path: str) -> list[str]:
        with open(log_path) as f:
            return [line.rstrip("\n") for line in f.readlines()]

    async def test_log_player(self):
        with tempfile.TemporaryDirectory() as tmp:
            logger, path = self._make_logger(tmp)
            await logger.log_player("I want to explore the cave")
            lines = self._read_lines(path)
            assert len(lines) == 1
            assert "PLAYER: I want to explore the cave" in lines[0]
            assert TIMESTAMP_RE.match(lines[0])

    async def test_log_dm_narrator(self):
        with tempfile.TemporaryDirectory() as tmp:
            logger, path = self._make_logger(tmp)
            await logger.log_dm(DEFAULT_CHARACTER, "neutral", "The cave entrance looms before you.")
            lines = self._read_lines(path)
            assert len(lines) == 1
            assert "DM: The cave entrance looms before you." in lines[0]
            assert TIMESTAMP_RE.match(lines[0])

    async def test_log_dm_npc(self):
        with tempfile.TemporaryDirectory() as tmp:
            logger, path = self._make_logger(tmp)
            await logger.log_dm("GUILDMASTER_TORIN", "stern", "You're the new one, then.")
            lines = self._read_lines(path)
            assert len(lines) == 1
            assert "[GUILDMASTER_TORIN, stern]: You're the new one, then." in lines[0]
            assert TIMESTAMP_RE.match(lines[0])

    async def test_log_tool(self):
        with tempfile.TemporaryDirectory() as tmp:
            logger, path = self._make_logger(tmp)
            await logger.log_tool("roll_dice", "d20", "rolled 17")
            lines = self._read_lines(path)
            assert len(lines) == 1
            assert "TOOL(roll_dice): d20 -> rolled 17" in lines[0]
            assert TIMESTAMP_RE.match(lines[0])

    async def test_multiple_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            logger, path = self._make_logger(tmp)
            await logger.log_player("Hello")
            await logger.log_dm(DEFAULT_CHARACTER, "neutral", "Welcome, traveler.")
            await logger.log_dm("BARKEEP", "friendly", "What'll it be?")
            await logger.log_tool("query_location", "tavern", "The Rusty Mug")
            lines = self._read_lines(path)
            assert len(lines) == 4
            assert "PLAYER:" in lines[0]
            assert "DM:" in lines[1]
            assert "[BARKEEP, friendly]:" in lines[2]
            assert "TOOL(query_location):" in lines[3]

    async def test_no_room_does_not_crash(self):
        """Publishing with room=None should not raise."""
        with tempfile.TemporaryDirectory() as tmp:
            logger, path = self._make_logger(tmp)
            await logger.log_player("test")
            await logger.log_dm(DEFAULT_CHARACTER, "neutral", "test")
            await logger.log_tool("test", "a", "b")
            lines = self._read_lines(path)
            assert len(lines) == 3

    async def test_close_removes_handlers(self):
        with tempfile.TemporaryDirectory() as tmp:
            logger, _path = self._make_logger(tmp)
            await logger.log_player("before close")
            assert len(logger._logger.handlers) == 1
            logger.close()
            assert len(logger._logger.handlers) == 0
