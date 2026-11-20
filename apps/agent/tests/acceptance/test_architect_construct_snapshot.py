import pytest
from acceptance.test_architect_constructs import summon
from acceptance.test_architect_entomb import fight as fight
from acceptance.test_architect_entomb import isolated_content_cache as isolated_content_cache
from acceptance.test_architect_entomb import mock_combat_agent_factory as mock_combat_agent_factory

import architect_encounter
import db_mutations


@pytest.mark.parametrize(
    "defect,why",
    [
        ("missing_ids", "Invalid Architect encounter record"),
        ("bad_id_list", "Invalid Architect construct IDs"),
        ("nonstring_id", "Invalid Architect construct IDs"),
        ("duplicate_id", "Duplicate Architect construct IDs"),
        ("orphan_id", "must match their summoned participants"),
        ("duplicate_participant", "must match their summoned participants"),
        ("non_enemy", "summons must be enemies"),
        ("unspent", "matching spent summon"),
        ("bool_remaining", "matching spent summon"),
        ("missing_ledger", "matching spent summon"),
        ("spent_without_summons", "matching spent summon"),
        ("future_round", "summon round is invalid"),
        ("zero_round", "summon round is invalid"),
        ("noninteger_round", "summon round is invalid"),
        ("live_at_expiry", "still owns live constructs"),
        ("live_after_owner_death", "still owns live constructs"),
        ("positive_hp_at_expiry", "still owns live constructs"),
        ("not_fallen_at_expiry", "still owns live constructs"),
        ("not_dead_at_expiry", "still owns live constructs"),
    ],
)
async def test_corrupt_construct_snapshots_fail_on_database_reload(fight, defect, why):
    if defect == "spent_without_summons":
        state = await fight.reload()
        owner = state.get_participant(state.architect_encounter["owner_id"])
        owner.action_ledger["summon constructs"]["remaining"] = 0
    else:
        await summon(fight, 2)
        state = await fight.reload()
    if defect == "live_after_owner_death":
        owner = state.get_participant(state.architect_encounter["owner_id"])
        owner.hp_current = 0
        owner.is_fallen = owner.is_dead = True
        architect_encounter.destroyed(state)

    data = state.to_dict()
    record = data["architect_encounter"]
    ids = record["construct_ids"]
    owner_row = next(p for p in data["participants"] if p["id"] == record["owner_id"])
    ledger = owner_row["action_ledger"]["summon constructs"]
    construct = next(p for p in data["participants"] if p["id"] in ids) if ids else {}
    if defect.endswith("_at_expiry"):
        data["round_number"] = ledger["round"] + 11
        if defect != "live_at_expiry":
            for actor in data["participants"]:
                if actor["id"] in ids:
                    actor.update(hp_current=0, is_fallen=True, is_dead=True)

    match defect:
        case "missing_ids":
            del record["construct_ids"]
        case "bad_id_list":
            record["construct_ids"] = {actor_id: True for actor_id in ids}
        case "nonstring_id":
            ids[0] = 123
        case "duplicate_id":
            ids.append(ids[0])
        case "orphan_id":
            ids[0] = "missing"
        case "duplicate_participant":
            data["participants"].append(dict(construct))
        case "non_enemy":
            construct["type"] = "companion"
        case "unspent":
            ledger["remaining"] = 1
        case "bool_remaining":
            ledger["remaining"] = False
        case "missing_ledger":
            owner_row["action_ledger"].pop("summon constructs")
        case "future_round":
            ledger["round"] = state.round_number + 1
        case "zero_round":
            ledger["round"] = 0
        case "noninteger_round":
            ledger["round"] = True
        case "positive_hp_at_expiry":
            construct["hp_current"] = 1
        case "not_fallen_at_expiry":
            construct["is_fallen"] = False
        case "not_dead_at_expiry":
            construct["is_dead"] = False
        case "live_after_owner_death":
            construct.update(hp_current=20, is_fallen=False, is_dead=False)

    await db_mutations.save_combat_state(state.combat_id, data)
    with pytest.raises(ValueError, match=why):
        await db_mutations.load_combat_state(state.combat_id)
