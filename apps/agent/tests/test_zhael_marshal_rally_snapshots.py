"""Persisted rally ledger compatibility."""

import pytest
from _unbound_path_fixtures import world as world
from test_encounter_facts_damage import PRIOR, fight

import db_mutations
from combat_state import CombatState

CLAUSE = "zhael_moment_to_rally"


async def test_rally_snapshot_round_trip(world) -> None:
    async with fight(world, "zhael", archetype="marshal") as f:
        snapshot = f.session.combat_state.to_dict()
        for legacy in (None, PRIOR, {**PRIOR, "party_aggressors": {}}):
            if legacy is None:
                snapshot.pop("encounter_facts")
            else:
                snapshot["encounter_facts"] = legacy
            await db_mutations.save_combat_state(f.combat_id, snapshot)
            facts = (await f.reload()).encounter_facts
            assert facts["rally_pending"] == {}
            assert facts["once_spent"] == {}
            assert facts["party_aggressors"] == ({} if legacy and "party_aggressors" in legacy else None)

        spent = {CLAUSE: [f.hero]}
        for pending in ({f.hero: f.ally}, {}):
            snapshot["encounter_facts"] = {
                **PRIOR,
                "party_aggressors": {},
                "once_spent": spent,
                "rally_pending": pending,
            }
            await db_mutations.save_combat_state(f.combat_id, snapshot)
            facts = (await f.reload()).encounter_facts
            assert facts["rally_pending"] == pending
            assert facts["once_spent"] == spent


@pytest.mark.parametrize(
    "pending", [None, [], {" ": "ally"}, {1: "ally"}, {"marshal": ""}, {"marshal": 1}, {"unspent": "ally"}]
)
def test_malformed_rally_snapshot(pending: object) -> None:
    snapshot = CombatState("combat", [], []).to_dict()
    facts = {**snapshot["encounter_facts"], "once_spent": {CLAUSE: ["marshal"]}, "rally_pending": pending}
    with pytest.raises(ValueError, match=r"encounter_facts.rally_pending"):
        CombatState.from_dict({**snapshot, "encounter_facts": facts})
