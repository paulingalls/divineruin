from types import SimpleNamespace
from unittest.mock import patch

import pytest
from _spell_heal_fixtures import HealWalk

import db_mutations
import db_queries

POTION = "healing_potion"
BERRY = "goodberry"
GOODBERRY = "primal_goodberry"


def heal_roll(total):
    return patch("dice.roll", return_value=SimpleNamespace(total=total))


class ItemHealWalk(HealWalk):
    async def put(self, item=POTION, quantity=2, *, tainted=False):
        await db_mutations.add_inventory_item(self.player, item, quantity, tainted=tainted)

    async def quantity(self, item=POTION, *, conn=None):
        slot = await db_queries.get_inventory_item(self.player, item, conn=conn)
        return slot["quantity"] if slot else 0

    async def consume(self, item=POTION, target=None, **kwargs):
        args = {"id": f"consume:{item}"}
        if target is not None:
            args["target_id"] = target
        return await self.command("activate", args, **kwargs)

    async def declare_item(self, item=POTION, target="", *, actor=None, **kwargs):
        actor = actor or self.player
        declarations = [{"kind": "consume", "actor_id": actor, "item_id": item, "target_id": target}]
        declarations.extend(
            {"kind": "defend", "actor_id": p.id}
            for p in self.fight_state.participants
            if p.id != actor and p.is_ally and not p.is_fallen
        )
        return await self.command("declare_phase", {"declarations": declarations}, **kwargs)

    async def resolve_item(self):
        result = await self.command("resolve_phase", {})
        return next(p for p in result["packets"] if p["actor_id"] == self.player)


@pytest.fixture(name="walk")
async def item_heal_walk(dev_db_pool):
    async with ItemHealWalk(dev_db_pool) as walk:
        await walk.patch(hp={"current": 5, "max": 20})
        yield walk
