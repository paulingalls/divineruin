from contextlib import asynccontextmanager

from acceptance.test_paladin_oath_swear import stored, timed
from acceptance.test_valdris_party_yield import registered
from test_encounter_facts_damage import GOBLIN, dice, fight


@asynccontextmanager
async def promised_fight(world, **kwargs):
    async with fight(world, "zhael", archetype="paladin", **kwargs) as f:
        registered(f)
        f.session.combat_state.round_number = 2
        f.session.combat_state.encounter_id = "reusable_encounter"
        yield f


async def select_oath(f, *, objective="defeat_target", target=GOBLIN, deadline=3):
    offer = (await f.call("query_info", kind="combat"))["oath_choice"]
    return await f.call("select", **timed(offer, objective=objective, target=target, deadline=deadline))


async def oath_record(f):
    book = await stored(f.hero)
    assert book is not None
    [record] = book["records"]
    return record


async def manual_save(f, face=9):
    with dice(face):
        return await f.call(
            "check", roll={"kind": "save", "save_type": "constitution", "dc": 10, "effect_on_fail": "stagger"}
        )


async def wrap(f, *faces):
    with dice(*faces):
        for _ in range(5):
            result = await f.call("resolve_phase")
            if isinstance(result, tuple):
                return result[1]
            if "fate_offer" in result or result["beat"] == "declaration":
                return result
    raise AssertionError("Round did not wrap")
