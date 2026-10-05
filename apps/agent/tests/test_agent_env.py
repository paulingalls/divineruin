import os
import runpy
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import async_worker
from agent import REQUIRED_ENV_VARS, validate_env


def _base_env() -> dict[str, str]:
    return {var: "test_value" for var in REQUIRED_ENV_VARS}


class TestEnvironmentValidation:
    def test_validate_env_passes_with_all_vars_set(self):
        env = {**_base_env(), "OPENAI_API_KEY": "test_openai"}
        with patch.dict(os.environ, env, clear=True):
            with patch("agent.VOICES", {"narrator": "voice_id", "torin": "voice_id2"}):
                with patch("agent.ROLE_VOICE_KEYS", ()):
                    validate_env()  # Should not raise

    def test_validate_env_raises_on_missing_vars(self):
        env = {var: "test_value" for var in REQUIRED_ENV_VARS[1:]}
        env["OPENAI_API_KEY"] = "test_openai"
        with patch.dict(os.environ, env, clear=True):
            with patch("agent.VOICES", {"narrator": "voice_id"}):
                with patch("agent.ROLE_VOICE_KEYS", ()):
                    with pytest.raises(EnvironmentError) as exc_info:
                        validate_env()

                    assert REQUIRED_ENV_VARS[0] in str(exc_info.value)

    def test_default_requires_openai_for_gameplay(self):
        with patch.dict(os.environ, _base_env(), clear=True):
            with patch("agent.VOICES", {"narrator": "voice_id"}):
                with patch("agent.ROLE_VOICE_KEYS", ()):
                    with pytest.raises(EnvironmentError, match="OPENAI_API_KEY"):
                        validate_env()

    def test_default_also_requires_anthropic_for_background_writers(self):
        env = {**_base_env(), "OPENAI_API_KEY": "test_openai"}
        env.pop("ANTHROPIC_API_KEY", None)
        with patch.dict(os.environ, env, clear=True):
            with patch("agent.VOICES", {"narrator": "voice_id"}):
                with patch("agent.ROLE_VOICE_KEYS", ()):
                    with pytest.raises(EnvironmentError, match="ANTHROPIC_API_KEY"):
                        validate_env()

    def test_anthropic_override_does_not_require_openai(self):
        env = {**_base_env(), "GAMEPLAY_LLM": "anthropic", "ANTHROPIC_API_KEY": "test_anthropic"}
        with patch.dict(os.environ, env, clear=True):
            with patch("agent.VOICES", {"narrator": "voice_id"}):
                with patch("agent.ROLE_VOICE_KEYS", ()):
                    validate_env()

    def test_validate_env_warns_but_serves_on_an_empty_non_role_voice(self):
        """Sable is intentionally nonverbal, so an empty voice is legitimate."""
        env = {**_base_env(), "OPENAI_API_KEY": "test_openai"}
        with patch.dict(os.environ, env, clear=True):
            with patch("agent.VOICES", {"DM_NARRATOR": "Clive", "COMPANION_SABLE": ""}):
                with patch("agent.ROLE_VOICE_KEYS", ()):
                    with patch("agent.logger") as mock_logger:
                        validate_env()  # Should not raise

                        mock_logger.warning.assert_called_once()
                        assert "COMPANION_SABLE" in mock_logger.warning.call_args[0][1]

    def test_validate_env_raises_naming_the_role_on_an_empty_role_voice(self):
        """Required role voices cannot use the nonverbal-companion exception."""
        env = {**_base_env(), "OPENAI_API_KEY": "test_openai"}
        with patch.dict(os.environ, env, clear=True):
            with patch("agent.VOICES", {"DM_NARRATOR": "Clive", "ROLE_GUARD": ""}):
                with patch("agent.ROLE_VOICE_KEYS", ("ROLE_GUARD",)):
                    with patch("agent.logger") as mock_logger:
                        with pytest.raises(EnvironmentError) as exc_info:
                            validate_env()

                    assert "ROLE_GUARD" in str(exc_info.value)
                    mock_logger.warning.assert_not_called()

    def test_validate_env_raises_when_a_role_voice_key_is_absent_entirely(self):
        env = {**_base_env(), "OPENAI_API_KEY": "test_openai"}
        with patch.dict(os.environ, env, clear=True):
            with patch("agent.VOICES", {"DM_NARRATOR": "Clive"}):
                with patch("agent.ROLE_VOICE_KEYS", ("ROLE_GUARD",)):
                    with pytest.raises(EnvironmentError) as exc_info:
                        validate_env()

                    assert "ROLE_GUARD" in str(exc_info.value)

    def test_validate_env_raises_naming_both_keys_when_two_voices_collide(self):
        """Two configured characters must not become indistinguishable by voice."""
        env = {**_base_env(), "OPENAI_API_KEY": "test_openai"}
        with patch.dict(os.environ, env, clear=True):
            with patch(
                "agent.VOICES",
                {
                    "DM_NARRATOR": "Clive",
                    "SCHOLAR_EMRIS": "Olivia",
                    "COMPANION_LIRA": "Olivia",
                },
            ):
                with patch("agent.ROLE_VOICE_KEYS", ()):
                    with pytest.raises(EnvironmentError) as exc_info:
                        validate_env()

        msg = str(exc_info.value)
        assert "SCHOLAR_EMRIS" in msg
        assert "COMPANION_LIRA" in msg
        assert "Olivia" in msg

    def test_empty_voices_do_not_count_as_a_collision(self):
        """Unconfigured voices legitimately share the empty value."""
        env = {**_base_env(), "OPENAI_API_KEY": "test_openai"}
        with patch.dict(os.environ, env, clear=True):
            with patch("agent.VOICES", {"DM_NARRATOR": "Clive", "COMPANION_SABLE": "", "TAVERN_BRYN": ""}):
                with patch("agent.ROLE_VOICE_KEYS", ()):
                    with patch("agent.logger"):
                        validate_env()  # must not raise


def test_async_worker_requires_anthropic_for_background_writers():
    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(EnvironmentError, match="ANTHROPIC_API_KEY"):
            async_worker.validate_worker_env()
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test"}, clear=True):
        async_worker.validate_worker_env()


@pytest.mark.asyncio
async def test_async_worker_main_rejects_a_missing_key_before_startup():
    with (
        patch.dict(os.environ, {}, clear=True),
        patch(
            "async_worker.db.get_pool", new_callable=AsyncMock, side_effect=AssertionError("worker started")
        ) as get_pool,
    ):
        with pytest.raises(EnvironmentError, match="ANTHROPIC_API_KEY"):
            await async_worker.main()

    get_pool.assert_not_awaited()


def test_agent_entrypoint_rejects_a_missing_key_before_starting_livekit(monkeypatch):
    """Invoke the actual CLI entry point rather than recreating its validation."""
    import livekit.agents.__main__ as livekit_entry

    livekit_start = MagicMock(side_effect=AssertionError("agent started"))
    monkeypatch.setattr(livekit_entry, "main", livekit_start)
    monkeypatch.setattr(sys, "argv", ["agent.py", "dev"])

    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(EnvironmentError, match="ANTHROPIC_API_KEY"):
            runpy.run_path(str(Path(__file__).resolve().parents[1] / "agent.py"), run_name="__main__")

    livekit_start.assert_not_called()
