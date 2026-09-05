"""validate_env — the startup gate on required env vars and voice configuration."""

import os
from unittest.mock import patch

import pytest

from agent import REQUIRED_ENV_VARS, validate_env


class TestEnvironmentValidation:
    """Test environment variable validation."""

    def test_validate_env_passes_with_all_vars_set(self):
        """validate_env should pass when all required vars are set."""
        env = {var: "test_value" for var in REQUIRED_ENV_VARS}
        with patch.dict(os.environ, env, clear=True):
            with patch("agent.VOICES", {"narrator": "voice_id", "torin": "voice_id2"}):
                with patch("agent.ROLE_VOICE_KEYS", ()):
                    validate_env()  # Should not raise

    def test_validate_env_raises_on_missing_vars(self):
        """validate_env should raise EnvironmentError if vars missing."""
        # Set all but one
        env = {var: "test_value" for var in REQUIRED_ENV_VARS[1:]}
        with patch.dict(os.environ, env, clear=True):
            with patch("agent.VOICES", {"narrator": "voice_id"}):
                with patch("agent.ROLE_VOICE_KEYS", ()):
                    with pytest.raises(EnvironmentError) as exc_info:
                        validate_env()

                    assert REQUIRED_ENV_VARS[0] in str(exc_info.value)

    def test_validate_env_warns_but_serves_on_an_empty_non_role_voice(self):
        """An empty NON-role voice stays a warning: COMPANION_SABLE is deliberately unset."""
        env = {var: "test_value" for var in REQUIRED_ENV_VARS}
        with patch.dict(os.environ, env, clear=True):
            with patch("agent.VOICES", {"DM_NARRATOR": "Clive", "COMPANION_SABLE": ""}):
                with patch("agent.ROLE_VOICE_KEYS", ()):
                    with patch("agent.logger") as mock_logger:
                        validate_env()  # Should not raise

                        mock_logger.warning.assert_called_once()
                        assert "COMPANION_SABLE" in mock_logger.warning.call_args[0][1]

    def test_validate_env_raises_naming_the_role_on_an_empty_role_voice(self):
        """A role voice registered but EMPTY would serve every guard in the narrator's voice.

        The warning must NOT also name it: a role voice is a hard failure, and logging it
        beside COMPANION_SABLE would file it under the tolerated empties this gate exists
        to separate it from.
        """
        env = {var: "test_value" for var in REQUIRED_ENV_VARS}
        with patch.dict(os.environ, env, clear=True):
            with patch("agent.VOICES", {"DM_NARRATOR": "Clive", "ROLE_GUARD": ""}):
                with patch("agent.ROLE_VOICE_KEYS", ("ROLE_GUARD",)):
                    with patch("agent.logger") as mock_logger:
                        with pytest.raises(EnvironmentError) as exc_info:
                            validate_env()

                    assert "ROLE_GUARD" in str(exc_info.value)
                    mock_logger.warning.assert_not_called()

    def test_validate_env_raises_when_a_role_voice_key_is_absent_entirely(self):
        """The gate must not be satisfiable by a MISSING key, only by a configured one."""
        env = {var: "test_value" for var in REQUIRED_ENV_VARS}
        with patch.dict(os.environ, env, clear=True):
            with patch("agent.VOICES", {"DM_NARRATOR": "Clive"}):
                with patch("agent.ROLE_VOICE_KEYS", ("ROLE_GUARD",)):
                    with pytest.raises(EnvironmentError) as exc_info:
                        validate_env()

                    assert "ROLE_GUARD" in str(exc_info.value)
