"""Tests for the pure Hollow Echo resolver (story-001, M3.2).

The Hollow Echo is the deterministic consequence rolled on a d20 when a spell is
cast at Overreach (Resonance 9+): the Veil tears and something may answer. Like the
Resonance engine this is a closed-table mechanic (CLAUDE.md golden rule #3) — the
LLM decides when to cast and narrates the result; this module only maps the roll to
a band. No IO, so these are plain unit tests with no fixtures or pool.

Spec source: docs/game_mechanics/game_mechanics_magic.md §Hollow Echo Table
(167-185): d20, at Resonance 12+ subtract 3, at 15+ subtract 6; bands 17-20 Nothing /
14-16 Whisper / 11-13 Veil scar / 8-10 Sympathetic / 5-7 Hollow attention /
2-4 Reality fracture / <=1 Breach.

Assumption recorded by this story: the resolver returns the band + a mechanical-effect
descriptor for the DM to narrate; the secondary mechanical follow-through (1d4 psychic
for Sympathetic, doubled Focus for Reality fracture, 1-3 creatures for Breach) is
DM/follow-up, NOT auto-applied here.
"""

import pytest

import hollow_echo

# --- band mapping by effective roll (res=9 -> no modifier, eff == d20_roll) ----


@pytest.mark.parametrize(
    "d20_roll,expected_band",
    [
        (20, "nothing"),
        (19, "nothing"),
        (18, "nothing"),
        (17, "nothing"),
        (16, "whisper"),
        (15, "whisper"),
        (14, "whisper"),
        (13, "veil_scar"),
        (12, "veil_scar"),
        (11, "veil_scar"),
        (10, "sympathetic"),
        (9, "sympathetic"),
        (8, "sympathetic"),
        (7, "hollow_attention"),
        (6, "hollow_attention"),
        (5, "hollow_attention"),
        (4, "reality_fracture"),
        (3, "reality_fracture"),
        (2, "reality_fracture"),
        (1, "breach"),
    ],
)
def test_band_by_roll_at_overreach_floor(d20_roll, expected_band):
    # At Resonance 9 (Overreach floor) no modifier applies, so effective == d20_roll.
    result = hollow_echo.resolve_hollow_echo(d20_roll, 9)
    assert result.band == expected_band
    assert result.effective_roll == d20_roll


# --- modifier at Resonance 12+ subtracts 3 (spec 169) -------------------------


@pytest.mark.parametrize(
    "d20_roll,expected_eff,expected_band",
    [
        (20, 17, "nothing"),
        (17, 14, "whisper"),
        (15, 12, "veil_scar"),  # the AC2 case: 15 at res 12 -> Veil scar, not Whisper
        (11, 8, "sympathetic"),
        (8, 5, "hollow_attention"),
        (5, 2, "reality_fracture"),
        (4, 1, "breach"),
    ],
)
def test_modifier_subtracts_three_at_twelve(d20_roll, expected_eff, expected_band):
    result = hollow_echo.resolve_hollow_echo(d20_roll, 12)
    assert result.effective_roll == expected_eff
    assert result.band == expected_band


# --- modifier at Resonance 15+ subtracts 6, clamps into Breach (spec 169) -----


@pytest.mark.parametrize(
    "d20_roll,expected_eff,expected_band",
    [
        (20, 14, "whisper"),
        (14, 8, "sympathetic"),
        (7, 1, "breach"),
        (4, -2, "breach"),  # AC3: 4 at res 15 -> effective -2 -> Breach
        (1, -5, "breach"),
    ],
)
def test_modifier_subtracts_six_at_fifteen(d20_roll, expected_eff, expected_band):
    result = hollow_echo.resolve_hollow_echo(d20_roll, 15)
    assert result.effective_roll == expected_eff
    assert result.band == expected_band


def test_fifteen_takes_six_not_three_plus_six():
    # The two thresholds do not stack: at 15+ the modifier is -6 total, not -3-6.
    at_eleven = hollow_echo.resolve_hollow_echo(14, 11)  # no modifier -> eff 14
    at_fourteen = hollow_echo.resolve_hollow_echo(14, 14)  # -3 -> eff 11
    at_fifteen = hollow_echo.resolve_hollow_echo(14, 15)  # -6 -> eff 8
    assert at_eleven.effective_roll == 14
    assert at_fourteen.effective_roll == 11
    assert at_fifteen.effective_roll == 8


# --- Veil Ward bonus shifts results milder (spec magic.md:198) ----------------


@pytest.mark.parametrize(
    "d20_roll,resonance,expected_eff,expected_band",
    [
        # +4 pushes a Whisper up into Nothing (14 -> eff 18).
        (14, 9, 18, "nothing"),
        # +4 offsets the -3 modifier at res 12 net +1 (13 -> eff 14).
        (13, 12, 14, "whisper"),
        # +4 against the -6 modifier at res 15 nets -2 (16 -> eff 14).
        (16, 15, 14, "whisper"),
        # Even a Breach-bound low roll is lifted out of Breach by the ward (1 -> eff 5).
        (1, 9, 5, "hollow_attention"),
    ],
)
def test_ward_bonus_shifts_band_milder(d20_roll, resonance, expected_eff, expected_band):
    result = hollow_echo.resolve_hollow_echo(d20_roll, resonance, ward_bonus=4)
    assert result.effective_roll == expected_eff
    assert result.band == expected_band


def test_ward_bonus_is_never_milder_than_no_ward():
    # The ward only ever helps: with a ward the effective roll is >= the unwarded roll
    # at the same resonance, so the band is the same or milder across the whole d20.
    for d20_roll in range(1, 21):
        warded = hollow_echo.resolve_hollow_echo(d20_roll, 12, ward_bonus=4)
        unwarded = hollow_echo.resolve_hollow_echo(d20_roll, 12)
        assert warded.effective_roll == unwarded.effective_roll + 4


def test_ward_bonus_defaults_to_zero():
    # Omitting ward_bonus matches passing 0 — no ward, no shift.
    assert (
        hollow_echo.resolve_hollow_echo(10, 9).effective_roll
        == hollow_echo.resolve_hollow_echo(10, 9, ward_bonus=0).effective_roll
    )


def test_negative_ward_bonus_fails_loud():
    # A ward only ever helps; a negative bonus is a caller bug, not a stricter ward.
    with pytest.raises(ValueError):
        hollow_echo.resolve_hollow_echo(10, 9, ward_bonus=-4)


# --- Vaelti echo-save advantage: best of two rolls (M3.4 story-004, spec 246-252) ---
# Advantage = roll two d20s, take the higher (higher -> milder band). The engine takes the
# second roll (advantage_roll); the caller supplies both (story-006 rolls it for a Vaelti).


@pytest.mark.parametrize(
    "d20_roll,advantage_roll,expected_base,expected_band",
    [
        # A Breach-bound low primary is rescued by a high advantage roll (max 18 -> Nothing).
        (3, 18, 18, "nothing"),
        # The primary already higher than the advantage roll wins (max stays 14).
        (14, 5, 14, "whisper"),
        # Equal rolls behave like a single roll.
        (8, 8, 8, "sympathetic"),
    ],
)
def test_advantage_takes_the_milder_of_two_rolls(d20_roll, advantage_roll, expected_base, expected_band):
    result = hollow_echo.resolve_hollow_echo(d20_roll, 9, advantage_roll=advantage_roll)
    assert result.effective_roll == expected_base  # res 9 -> no modifier, no ward
    assert result.band == expected_band


def test_advantage_is_never_harsher_than_no_advantage():
    # Advantage only ever helps: across every (primary, advantage) pair the effective roll is
    # >= the no-advantage roll, so the band is the same or milder.
    for d20_roll in range(1, 21):
        plain = hollow_echo.resolve_hollow_echo(d20_roll, 12)  # independent of advantage_roll
        for advantage_roll in range(1, 21):
            adv = hollow_echo.resolve_hollow_echo(d20_roll, 12, advantage_roll=advantage_roll)
            assert adv.effective_roll >= plain.effective_roll


def test_advantage_roll_defaults_to_none_unchanged():
    # Omitting advantage_roll matches the single-roll path (no second die).
    assert (
        hollow_echo.resolve_hollow_echo(10, 9).effective_roll
        == hollow_echo.resolve_hollow_echo(10, 9, advantage_roll=None).effective_roll
    )


@pytest.mark.parametrize("bad_roll", [0, 21, -1])
def test_advantage_roll_out_of_range_fails_loud(bad_roll):
    # The second roll is a real d20 — validated 1-20 like the primary.
    with pytest.raises(ValueError):
        hollow_echo.resolve_hollow_echo(10, 9, advantage_roll=bad_roll)


def test_advantage_still_honors_primary_and_overreach_guards():
    # The primary d20 range guard and the Overreach floor still fire with advantage supplied.
    with pytest.raises(ValueError):
        hollow_echo.resolve_hollow_echo(0, 9, advantage_roll=15)  # bad primary
    with pytest.raises(ValueError):
        hollow_echo.resolve_hollow_echo(10, 8, advantage_roll=15)  # below Overreach


# --- result shape: each band carries a display name + mechanical descriptor ----


def test_result_carries_name_and_effect():
    result = hollow_echo.resolve_hollow_echo(1, 9)
    assert result.band == "breach"
    assert result.name == "Breach"
    assert result.effect  # non-empty mechanical descriptor for the DM to narrate


@pytest.mark.parametrize(
    "d20_roll,expected_name",
    [
        (18, "Nothing stirs"),
        (15, "Whisper"),
        (12, "Veil scar"),
        (9, "Sympathetic resonance"),
        (6, "Hollow attention"),
        (3, "Reality fracture"),
        (1, "Breach"),
    ],
)
def test_band_display_names(d20_roll, expected_name):
    assert hollow_echo.resolve_hollow_echo(d20_roll, 9).name == expected_name


def test_every_band_has_a_distinct_nonempty_effect():
    effects = {
        hollow_echo.resolve_hollow_echo(roll, 9).band: hollow_echo.resolve_hollow_echo(roll, 9).effect
        for roll in range(1, 21)
    }
    assert len(effects) == 7  # all seven bands reached across d20 1-20 at res 9
    assert all(effects.values())  # none empty


# --- fail-loud guards (echo only meaningful at Overreach; d20 is 1-20) --------


@pytest.mark.parametrize("resonance", [0, 4, 8])
def test_below_overreach_fails_loud(resonance):
    # The cast path only rolls at Overreach (9+); calling below that is a misuse.
    with pytest.raises(ValueError):
        hollow_echo.resolve_hollow_echo(15, resonance)


@pytest.mark.parametrize("d20_roll", [0, 21, -1])
def test_out_of_range_roll_fails_loud(d20_roll):
    with pytest.raises(ValueError):
        hollow_echo.resolve_hollow_echo(d20_roll, 9)
