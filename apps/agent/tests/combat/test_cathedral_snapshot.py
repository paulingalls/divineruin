import pytest
from combat.test_combat_spatial import pos, spatial_state
from combat.test_entomb_snapshot import snapshot as snapshot

from combat_state import CombatState
from combat_structures import collapse_wall

ZONE = "b_cathedral"
CENTER = "b_cathedral_center"


def raised(state):
    owner = state.get_participant("b")
    owner.action_pool.append({"name": "Cathedral", "recharge": {"kind": "encounter", "uses": 1}})
    owner.action_ledger["cathedral"] = {"round": 1, "remaining": 0}
    state.spatial["locations"][CENTER] = pos(40)
    state.spatial["zones"][ZONE] = {"kind": "cathedral", "center_id": CENTER, "radius_ft": 60}
    return owner


@pytest.mark.parametrize("cast", ["old", "active", "ended"])
def test_cathedral_reads_old_active_and_ended_snapshots(snapshot, cast):
    if cast != "old":
        raised(snapshot)
    if cast == "ended":
        del snapshot.spatial["locations"][CENTER], snapshot.spatial["zones"][ZONE]
    data = snapshot.to_dict()
    assert CombatState.from_dict(data).to_dict() == data


@pytest.mark.parametrize(
    "defect,diagnostic",
    [
        ("orphan", "zone must belong"),
        ("foreign", "zone must belong"),
        ("wrong_kind", "zone must belong"),
        ("wrong_center", "fixed landmark"),
        ("non_landmark", "fixed landmark"),
        ("radius", "radius must be 60"),
        ("unspent", "spent action"),
        ("boolean_ledger", "spent action"),
        ("dead", "living owner inside"),
        ("outside", "living owner inside"),
    ],
)
def test_cathedral_refuses_corrupt_snapshots(snapshot, defect, diagnostic):
    owner = raised(snapshot)
    spatial = snapshot.spatial
    match defect:
        case "orphan":
            del spatial["zones"][ZONE]
        case "foreign":
            spatial["zones"]["foreign"] = {**spatial["zones"].pop(ZONE), "center_id": "b"}
            del spatial["locations"][CENTER]
        case "wrong_kind":
            spatial["zones"][ZONE].update(kind="silence", center_id="b")
            del spatial["locations"][CENTER]
        case "wrong_center":
            spatial["zones"][ZONE]["center_id"] = "b"
        case "non_landmark":
            spatial["positions"][CENTER] = spatial["locations"].pop(CENTER)
            del spatial["positions"]["a"]
            spatial["speeds"][CENTER] = spatial["speeds"].pop("a")
            snapshot.get_participant("a").id = CENTER
            snapshot.initiative_order[0] = CENTER
            spatial["zones"]["silence"]["center_id"] = CENTER
        case "radius":
            spatial["zones"][ZONE]["radius_ft"] = 61
        case "unspent":
            owner.action_ledger["cathedral"]["remaining"] = 1
        case "boolean_ledger":
            owner.action_ledger["cathedral"]["remaining"] = False
        case "dead":
            owner.hp_current = 0
            owner.is_dead = owner.is_fallen = True
            snapshot.architect_encounter["phase"] = "destroyed"
            for wall_id in snapshot.architect_encounter["structure_ids"]:
                collapse_wall(snapshot, snapshot.get_participant(wall_id))
        case "outside":
            spatial["positions"]["b"] = pos(40, 60, 1)
    with pytest.raises(ValueError, match=diagnostic):
        CombatState.from_dict(snapshot.to_dict())


def test_cathedral_requires_an_architect():
    state = spatial_state()
    raised(state)
    with pytest.raises(ValueError, match="Cathedral requires an Architect owner"):
        CombatState.from_dict(state.to_dict())


def test_authored_placement_refuses_runtime_cathedral():
    from combat_spatial import validate_scene

    with pytest.raises(ValueError, match="zone kind"):
        validate_scene(
            {
                "enemies": [{"id": "b"}],
                "scene_placement": {
                    "party_start": pos(),
                    "companion_start": pos(),
                    "actors": {"b": pos(40)},
                    "locations": {CENTER: pos(40)},
                    "zones": {ZONE: {"kind": "cathedral", "center_id": CENTER, "radius_ft": 60}},
                },
            }
        )
