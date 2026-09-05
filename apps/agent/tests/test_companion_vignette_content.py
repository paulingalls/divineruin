"""AC1/AC2/AC4: the four beat-3/4 vignettes are authored per companion, in the content row.

The prose lives in content/companions.json rather than in onboarding_prompt.py because
test_no_companion_literal's walker matches the FILE TEXT of every non-allowlisted, non-test
file: once onboarding_prompt.py comes off that allowlist (AC6), the module may not contain the
string "Kael" in any shape — not a constant, not a dict key, not a function name. The row the
renderer already reads is the only home left.

TWO AUTHORING RULES THIS FILE ENFORCES BLUNTLY, because a text guard cannot attribute a word
to a speaker. Both are stated here so the next author meets them as a rule, not as a red:

1. GENDERED PRONOUNS IN A VIGNETTE REFER TO THE COMPANION AND TO NO ONE ELSE. Three of the four
   scenes have named third parties (a vendor, a carter, a fishwife). The guard reads the whole
   field and cannot tell whose "she" it is reading, so a third party's pronoun both satisfies the
   companion's positive assertion vacuously AND false-reds a nonbinary companion's scene against
   correct prose. Name third parties by role on every mention, or use they/them.
2. NO SPEECH VERB APPEARS ANYWHERE IN SABLE'S TWO FIELDS — not even the fishwife's. Same reason:
   the guard cannot tell that the verb belongs to the vendor. Her name reveal is written around
   the list ("uses the name aloud"), which costs one phrasing and buys a check that reds.

they/them/their is NOT forbidden for the gendered companions. It is the neutral default and in
this prose it refers to THE PLAYER; forbidding it would make the guard unwritable against
correct text.
"""

import json
import re
from collections.abc import Sequence
from pathlib import Path

import pytest

from companion_profiles import parse_companion_row

_CONTENT_PATH = Path(__file__).resolve().parents[3] / "content" / "companions.json"
_RAW = json.loads(_CONTENT_PATH.read_text())

VIGNETTE_FIELDS = ("onboarding_meeting", "onboarding_suggestion")

# The map is the card's human decision (2026-09-04). Keyed by the row's own `gender`, so the
# content file is what says who is who — not a re-typed table of companion ids in a test.
PRONOUNS = {
    "male": ("he", "him", "his", "himself"),
    "female": ("she", "her", "hers", "herself"),
    "nonbinary": ("they", "them", "their", "theirs", "themselves"),
}
NEUTRAL = "nonbinary"

# Verbs that would put words in a non-verbal companion's mouth. growl / chirp / yip / whine /
# huff are Sable's register and are deliberately absent.
SPEECH_VERBS = [
    "says",
    "say",
    "said",
    "speaks",
    "speak",
    "spoke",
    "talks",
    "talk",
    "talking",
    "mutters",
    "mutter",
    "muttering",
    "whispers",
    "whisper",
    "whispering",
    "murmurs",
    "murmur",
    "murmuring",
    "hums",
    "hum",
    "humming",
    "sings",
    "sing",
    "singing",
    "asks",
    "ask",
    "asked",
    "answers",
    "answer",
    "answered",
    "replies",
    "reply",
    "replied",
    "shouts",
    "shout",
    "tells",
    "tell",
    "told",
]

_COMPANION_NAMES = {row["id"]: row["name"] for row in _RAW}


def _vignette_text(row: dict) -> str:
    return " ".join(row[f] for f in VIGNETTE_FIELDS)


def _present(words: Sequence[str], text: str) -> list[str]:
    return [w for w in words if re.search(rf"\b{w}\b", text, re.IGNORECASE)]


class TestVignetteFieldsExist:
    def test_every_row_declares_both_vignette_fields(self):
        for row in _RAW:
            for field in VIGNETTE_FIELDS:
                assert isinstance(row.get(field), str) and row[field].strip(), f"{row['id']}.{field}"

    @pytest.mark.parametrize("field", VIGNETTE_FIELDS)
    def test_a_row_missing_a_vignette_field_is_rejected(self, field):
        row = {k: v for k, v in _RAW[0].items() if k != field}
        with pytest.raises(ValueError):
            parse_companion_row(_RAW[0]["id"], row)

    def test_parsed_fields_round_trip(self):
        for row in _RAW:
            c = parse_companion_row(row["id"], row)
            assert c.onboarding_meeting == row["onboarding_meeting"]
            assert c.onboarding_suggestion == row["onboarding_suggestion"]


class TestVignettePronouns:
    """AC4: every pronoun in the four vignettes agrees with the row's own `gender`."""

    def test_no_vignette_uses_another_buckets_gendered_pronoun(self):
        for row in _RAW:
            text = _vignette_text(row)
            for bucket, words in PRONOUNS.items():
                if bucket == row["gender"] or bucket == NEUTRAL:
                    continue
                leaked = _present(words, text)
                assert not leaked, f"{row['id']} ({row['gender']}) uses {bucket} pronouns {leaked}"

    def test_every_gendered_vignette_carries_its_own_pronouns(self):
        """Without this, a pronoun-free vignette passes the check above vacuously.

        THE NEUTRAL BUCKET IS EXCLUDED, and excluding it is the honest move rather than the
        lazy one. they/them is also what this prose calls THE PLAYER, so a word search cannot
        tell a nonbinary companion's pronoun from the player's: measured, a rewrite of Tam's
        two fields in which every they/them refers to the player and none to Tam passed this
        assertion unchanged. A guard that greens on the defect it names is worse than none
        (constraint 1). A nonbinary row rests on the negative check above, which is not
        vacuous — a stray "he" or "she" in Tam's scene reds it.
        """
        for row in _RAW:
            if row["gender"] == NEUTRAL:
                continue
            own = _present(PRONOUNS[row["gender"]], _vignette_text(row))
            assert own, f"{row['id']} vignettes use no {row['gender']} pronoun at all"


class TestNonVerbalVignette:
    """AC2/AC4: Sable's scene carries her without giving her a voice."""

    def _non_verbal_rows(self) -> list[dict]:
        rows = [r for r in _RAW if r.get("non_verbal")]
        assert rows, "no non-verbal companion in the catalog — this guard would certify nothing"
        return rows

    def test_no_speech_is_attributed_in_a_non_verbal_vignette(self):
        for row in self._non_verbal_rows():
            spoken = _present(SPEECH_VERBS, _vignette_text(row))
            assert not spoken, f"{row['id']} vignettes use speech verbs {spoken}"

    def test_a_non_verbal_vignette_carries_no_quoted_line_or_voice_tag(self):
        for row in self._non_verbal_rows():
            text = _vignette_text(row)
            assert '"' not in text, f"{row['id']} vignettes quote a line"
            assert "[COMPANION_" not in text, f"{row['id']} vignettes carry a voice tag"


class TestVignetteNamesOnlyItsOwnCompanion:
    def test_no_other_companion_appears_in_a_vignette(self):
        for row in _RAW:
            text = _vignette_text(row)
            others = [n for cid, n in _COMPANION_NAMES.items() if cid != row["id"] and n in text]
            assert not others, f"{row['id']} vignettes name {others}"
