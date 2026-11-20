import pytest
from combat.test_combat_spatial import pos, spatial_state

import architect_encounter
from combat_state import CombatState
from combat_structures import add_wall
from conditions import apply_condition


@pytest.fixture
def snapshot():
    state = spatial_state()
    owner = state.get_participant("b")
    assert owner is not None
    owner.creature_id = "hollow_architect"
    owner.hollow = {"corruption_aura": 2640}
    architect_encounter.initialize(state)
    return state


def encase(state, chamber):
    add_wall(state, chamber, "Entomb chamber", pos(), pos(10))
    state.architect_encounter["structure_ids"].append(chamber)
    state.spatial["positions"][chamber] = pos()
    del state.spatial["structures"][chamber]
    state.spatial.setdefault("chambers", {})[chamber] = {"target_id": "a"}
    target = state.get_participant("a")
    target.conditions.extend(apply_condition([], "restrained", source=chamber))


@pytest.mark.parametrize("shape", ["absent", "empty", "live"])
def test_entomb_snapshot_roundtrip(snapshot, shape):
    if shape == "empty":
        snapshot.spatial["chambers"] = {}
    if shape == "live":
        encase(snapshot, "b_chamber_2")
    data = snapshot.to_dict()
    assert CombatState.from_dict(data).to_dict() == data


@pytest.mark.parametrize(
    "defect,diagnostic",
    [
        ("missing_source", "permanent Restrained"),
        ("wrong_source", "permanent Restrained"),
        ("wrong_condition", "permanent Restrained"),
        ("duplicate_source", "permanent Restrained"),
        ("timed_source", "permanent Restrained"),
        ("orphaned_source", "no matching Entomb link"),
        ("stray_source", "no matching Entomb link"),
        ("stray_nonstandard_source", "no matching Entomb link"),
        ("orphaned_chamber", "exactly the live structures"),
        ("orphaned_victim", "creature target"),
        ("structure_victim", "creature target"),
        ("duplicate_victim", "only one Entomb chamber"),
        ("destroyed_chamber", "exactly the live structures"),
        ("missing_link", "exactly the live structures"),
        ("segment_overlap", "exactly the live structures"),
        ("unowned", "must be owned"),
        ("initiative", "cannot have an initiative turn"),
        ("malformed_map", "expected map"),
        ("malformed_link", "Invalid Entomb chamber link"),
        ("extra_link_key", "Invalid Entomb chamber link"),
    ],
)
def test_entomb_snapshot_rejects_corruption(snapshot, defect, diagnostic):
    chamber = "b_chamber_2"
    encase(snapshot, chamber)
    if defect == "duplicate_victim":
        encase(snapshot, "b_chamber_3")
    data = snapshot.to_dict()
    spatial = data["spatial"]
    participants = {p["id"]: p for p in data["participants"]}
    owned = data["architect_encounter"]["structure_ids"]
    match defect:
        case "missing_source":
            participants["a"]["conditions"].clear()
        case "wrong_condition":
            participants["a"]["conditions"][0]["type"] = "prone"
        case "duplicate_source":
            participants["a"]["conditions"].extend(apply_condition([], "restrained", source=chamber))
        case "wrong_source":
            participants["a"]["conditions"][0]["source"] = "other"
        case "timed_source":
            participants["a"]["conditions"][0]["duration"] = 1
        case "orphaned_source" | "orphaned_chamber":
            data["participants"].remove(participants[chamber])
            del spatial["positions"][chamber], spatial["speeds"][chamber]
            owned.remove(chamber)
            if defect == "orphaned_source":
                del spatial["chambers"][chamber]
        case "stray_source":
            participants["b"]["conditions"] = apply_condition([], "restrained", source=chamber)
        case "stray_nonstandard_source":
            participants[chamber]["id"] = "chamber"
            owned[owned.index(chamber)] = "chamber"
            for key in ("chambers", "positions", "speeds"):
                spatial[key]["chamber"] = spatial[key].pop(chamber)
            participants["a"]["conditions"][0]["source"] = "chamber"
            participants["b"]["conditions"] = apply_condition([], "restrained", source="chamber")
        case "orphaned_victim":
            spatial["chambers"][chamber]["target_id"] = "missing"
        case "structure_victim":
            spatial["chambers"][chamber]["target_id"] = chamber
            participants[chamber]["conditions"] = participants["a"]["conditions"]
            participants["a"]["conditions"] = []
        case "destroyed_chamber":
            participants[chamber].update(is_fallen=True, is_dead=True, hp_current=0)
        case "missing_link":
            spatial["chambers"].clear()
        case "segment_overlap":
            spatial["structures"][chamber] = {"start": pos(), "end": pos(10)}
        case "unowned":
            owned.remove(chamber)
        case "initiative":
            data["initiative_order"].append(chamber)
        case "malformed_map":
            spatial["chambers"] = []
        case "malformed_link":
            spatial["chambers"][chamber] = {"target_id": []}
        case "extra_link_key":
            spatial["chambers"][chamber]["extra"] = "unexpected"
    with pytest.raises(ValueError, match=diagnostic):
        CombatState.from_dict(data)
