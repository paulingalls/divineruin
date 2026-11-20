from contextlib import asynccontextmanager

from _mortaen_threshold_fixtures import FOE, active, declare, fight, rolls
from _patron_engine_fixtures import configure
from _zhael_fate_fixtures import attack
from test_patron_engine_death_ward import enemy_damage, resolve_until

EMBRACE = "orenthel_dawns_embrace"
SPENT = {EMBRACE: {"spent": True}}


@asynccontextmanager
async def embrace_fight(world, *, favor=75, gifts=None, donor_patron="orenthel", **target_options):
    options = {"hp": 4, "max_hp": 20, "patron": "aelora", "race": "draethar"} | target_options
    async with fight(world, guest=donor_patron, guest_class="cleric", guest_hp=7, **options) as call:
        await configure(
            world,
            donor_patron,
            "cleric",
            index=1,
            divine_favor={"patron": donor_patron, "level": favor, "max": 100},
            hp={"current": 7, "max": 100},
            patron_gifts=gifts or {},
        )
        yield call


async def aim(world, call, *targets):
    state = active(world)
    actions = []
    for index, target in enumerate(targets):
        foe = (FOE, "mawling_2")[index]
        position = dict(state.spatial["positions"][target])
        position["x"] += 5
        state.spatial["positions"][foe] = position
        state.get_participant(foe).initiative = 100 - index
        actions.append({**attack(foe, target), "action": "Claw"})
    await declare(world, call, *actions)


async def damage_ally(world, call, *, target_id=None, inner=False, damage=10):
    if inner:
        with rolls(19, damage=damage):
            return await call("activate", id="draethar_inner_fire")
    await aim(world, call, target_id or world.ids[0])
    with rolls(15, 15, 7, damage=damage):
        return await resolve_until(call, enemy_damage)
