"""Sanitize untrusted text before interpolating into LLM prompts."""

import re

_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_INJECTION_RE = re.compile(r"\[(SYSTEM|INST|/INST|ASSISTANT|USER|HUMAN)", re.IGNORECASE)


def sanitize_for_prompt(text: str, max_len: int = 200) -> str:
    """Strip control chars, truncate, and neutralize prompt-injection markers.

    Args:
        text: Untrusted text from DB (NPC names, quest objectives, etc.)
        max_len: Maximum allowed length after sanitization.

    Returns:
        Cleaned text safe for interpolation into an LLM prompt.
    """
    # Strip control characters (preserve newlines and tabs)
    text = _CONTROL_CHAR_RE.sub("", text)
    # Truncate
    if len(text) > max_len:
        text = text[:max_len]
    # Neutralize prompt injection patterns: [SYSTEM -> (SYSTEM
    text = _INJECTION_RE.sub(lambda m: "(" + m.group(1), text)
    return text
