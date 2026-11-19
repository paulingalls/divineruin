import pytest
from _patron_engine_fixtures import configure
from _unbound_path_fixtures import cast, encounter, phase, row
from _unbound_path_fixtures import world as world


async def hidden_casting_composes_and_persists(world, archetype, hidden, expected):
    w = world
    await configure(w, "syrath", archetype, flags={"concealed": hidden})
    packet = await cast(w, sid="arcane_fireball")
    assert packet["resonance_generated"] == expected
    assert (await row(w, 0))["resonance"]["current"] == (9 if expected == 0 else 7 + expected)
    assert w.ctx.userdata.party.primary.resonance.current == (9 if expected == 0 else 7 + expected)


async def test_hidden_guest_declared_cast(world):
    w = world
    await configure(w, "syrath", "seeker", index=1, flags={"concealed": True})
    encounter(w)
    with w.ctx.userdata._bind_authenticated_actor(w.ids[1], 4, lambda *_: None):
        packet = await phase(w)
    assert packet["packets"]
    assert (await row(w))["resonance"]["current"] == 9
    assert (await row(w, 0))["resonance"]["current"] == 9


@pytest.mark.parametrize("ward,corruption,expected", [(False, 0, 1), (True, 1, 0)])
async def test_hidden_casting_positive_generation(world, ward, corruption, expected):
    w = world
    await configure(w, "syrath", "mage", level=20, flags={"concealed": True})
    w.ctx.userdata.party.primary.corruption_level = corruption
    packet = await cast(w, sid="arcane_wall_of_force", ward=ward)
    assert packet["resonance_generated"] == expected
    assert (await row(w, 0))["resonance"]["current"] == (8 if expected else 9)


SCENARIOS = {
    "syrath_silent_casting": (
        "cast_modifiers:apply_patron_generation",
        hidden_casting_composes_and_persists,
        [("mage", True, 0), ("seeker", True, 0), ("bard", True, 1), ("mage", False, 3)],
    ),
}
