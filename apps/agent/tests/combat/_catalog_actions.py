RALLY = {
    "name": "Rally",
    "kind": "healing",
    "healing": "1d8",
    "target_group": "allied_bandits",
    "recharge": {"kind": "encounter", "uses": 1},
}
DIRTY = {
    "name": "Dirty Fighting",
    "kind": "prepare_attack",
    "advantage": True,
    "on_hit": {"applies_condition": "blinded", "duration": 1},
    "recharge": {"kind": "encounter", "uses": 1},
}
BITE = {
    "name": "Bite",
    "damage": "1d1+19",
    "damage_type": "necrotic",
    "properties": [],
    "attack_source": "catalog",
    "to_hit": 9,
    "self_heal": "damage_dealt",
}
