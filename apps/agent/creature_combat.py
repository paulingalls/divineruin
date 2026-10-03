"""Pure catalog-to-runtime translation, before encounter role overlays."""

from copy import deepcopy

from action_contracts import validate_recharge
from combat_init_validation import validate_enemy_action_shapes
from creature_combat_effects import deferred_effects
from creature_schema import validate_creature_stat_block
from encounter_actions import action_kind, validate_encounter_actions
from encounter_roles import derive_role_stats
from hollow_resonance import amount

_ATTRIBUTES = dict(
    zip(
        ("STR", "DEX", "CON", "INT", "WIS", "CHA"),
        ("strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"),
        strict=True,
    )
)
_CATEGORIES = {"humanoid", "beast", "construct", "undead"}


def _action(source):
    action = deepcopy(source)
    damage = action.get("damage")
    if isinstance(damage, str) and damage.isdecimal():
        amount = int(damage)
        action["damage"] = f"1d1+{amount - 1}" if amount else "0"
    properties = list(action.get("properties", []))
    if action.get("type") == "ranged":
        properties.append("ranged")
    if action.get("type") == "area":
        properties.append("aoe")
    kind = action_kind(action)
    if "recharge" in action:
        validate_recharge(action["recharge"], f"action {action.get('name')!r}.recharge")
    if kind == "healing" or action.get("self_heal"):
        properties.append("healing")
    if kind in ("command", "prepare_attack"):
        properties.append("buff")
    action["properties"] = list(dict.fromkeys(properties))
    if kind == "attack" and "to_hit" in action:
        action["attack_source"] = "catalog"
    return action


def _translate(row, encounter_id, enemy_id, role):
    for key, value in (("creature_id", row.get("id")), ("encounter_id", encounter_id), ("enemy_id", enemy_id)):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{key}: expected nonempty identity")
    if role not in ("minion", "standard", "elite", "boss"):
        raise ValueError(f"unsupported role {role!r}; Named/custom mechanics require authored integration")
    problems = validate_creature_stat_block(row)
    if problems:
        names = [
            a.get("name")
            for group in ("attacks", "actives")
            if isinstance(row.get(group), list)
            for a in row[group]
            if isinstance(a, dict)
        ]
        raise ValueError(f"actions {names!r}: " + "; ".join(problems))
    category = row["category"]
    if category == "hollow":
        cls = row["hollow"]["class"]
        if cls == "named":
            raise ValueError("unsupported Named/custom hollow mechanics")
        category = f"hollow_{cls}"
    elif category not in _CATEGORIES:
        raise ValueError(f"unsupported category {category!r}")
    unknown_attributes = set(row["attributes"]) - _ATTRIBUTES.keys()
    if unknown_attributes:
        raise ValueError(f"attributes: unknown keys {sorted(unknown_attributes)!r}")
    if any(save not in _ATTRIBUTES for save in row["save_proficiencies"]):
        raise ValueError("save_proficiencies: unknown attribute")
    actions = [_action(a) for a in row["attacks"]]
    names = {a["name"] for a in actions}
    if len(names) != len(actions):
        raise ValueError("attacks: duplicate action name")
    for source in row["actives"]:
        if source["name"] in names:
            if row["id"] == "hollow_mawling" and source["name"] == "Lunge" and "kind" not in source:
                continue
            raise ValueError(f"action {source['name']!r}: unexpected duplicate")
        if "kind" in source:
            actions.append(_action(source))
            names.add(source["name"])
    enemy = {key: deepcopy(row[key]) for key in ("name", "hp", "ac", "level", "tier", "loot_table_id", "speed")}
    enemy.update(
        id=enemy_id,
        creature_id=row["id"],
        encounter_id=encounter_id,
        category=category,
        xp_value=row["xp_reward"],
        attributes={_ATTRIBUTES[k]: v for k, v in row["attributes"].items()},
        saving_throw_proficiencies=[_ATTRIBUTES[k] for k in row["save_proficiencies"]],
        resistance_tags=deepcopy(row.get("resistance_tags", [])),
        action_pool=actions,
        signature_ability=deepcopy(row.get("signature_ability")),
        catalog_narration=deepcopy(row["narration"]),
        catalog_audio=deepcopy(row["audio"]),
        deferred_effects=deferred_effects(row),
        hollow=(
            {key: amount(row["hollow"][key], key) for key in ("corruption_aura", "resonance_on_death")}
            if row["hollow"] is not None
            else None
        ),
    )
    validate_enemy_action_shapes([enemy])
    validate_encounter_actions([enemy])
    enemy = derive_role_stats(enemy, role)
    if not any(
        action_kind(a) == "attack" and a.get("damage") not in (None, "", "0", "0d0") for a in enemy["action_pool"]
    ):
        raise ValueError("action_pool: no usable damaging attack after role derivation")
    return enemy


def translate_creature(row, *, encounter_id, enemy_id, role):
    creature_id = row.get("id") if isinstance(row, dict) else "<missing>"
    try:
        if not isinstance(row, dict):
            raise ValueError("creature: expected object")
        return _translate(row, encounter_id, enemy_id, role)
    except ValueError as exc:
        raise ValueError(f"creature {creature_id!r}, encounter {encounter_id!r}, enemy {enemy_id!r}: {exc}") from exc
