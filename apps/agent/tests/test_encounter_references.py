import json
from pathlib import Path

import pytest

from encounter_references import validate_encounter_references

ROOT = Path(__file__).resolve().parents[3]
CASES = json.loads((ROOT / "packages/shared/fixtures/encounter_references.json").read_text())
CATALOG = {row["id"] for row in json.loads((ROOT / "content/creatures.json").read_text())}


@pytest.mark.parametrize("case", CASES["invalid"], ids=lambda case: case["name"])
def test_shared_reference_cases(case):
    with pytest.raises(ValueError, match=case["field"]):
        validate_encounter_references(case["encounter"], CATALOG)


@pytest.mark.parametrize("encounter", CASES["valid"])
def test_recommended_party_level_cases(encounter):
    validate_encounter_references(encounter, CATALOG)


def test_all_ten_reference_templates():
    templates = json.loads((ROOT / "content/encounter_templates.json").read_text())
    assert len(templates) == 10 and CATALOG
    for template in templates:
        assert all(set(enemy) == {"id", "creature_id", "role"} for enemy in template["enemies"])
        validate_encounter_references(template, CATALOG)


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES["invalid"], ids=lambda case: case["name"])
async def test_start_reference_failures_have_no_side_effects(case, monkeypatch, mock_combat_agent_factory):
    from unittest.mock import AsyncMock, MagicMock

    from livekit.agents.llm import ToolError
    from sample_fixtures import make_context

    import combat_init
    from tests.combat.test_start_combat import _make_start_combat_mocks

    mutations, queries, content = _make_start_combat_mocks()
    content.get_encounter_template = AsyncMock(return_value=case["encounter"])
    from sample_fixtures import load_test_creature

    content.load_creature_enemy = load_test_creature
    initiative = MagicMock()
    event = AsyncMock()
    sound = AsyncMock()
    monkeypatch.setattr(combat_init.combat_resolution, "roll_initiative", initiative)
    monkeypatch.setattr(combat_init, "publish_game_event", event)
    monkeypatch.setattr(combat_init, "_publish_sounds", sound)
    ctx = make_context()
    with pytest.raises(ToolError, match=case["field"]):
        await combat_init._start_combat_impl(
            ctx, "fixture", "test", mutations=mutations, queries=queries, content=content
        )
    initiative.assert_not_called()
    mutations.save_combat_state.assert_not_called()
    event.assert_not_called()
    sound.assert_not_called()
    mock_combat_agent_factory.assert_not_called()
    assert ctx.userdata.combat_state is None and not ctx.userdata.in_combat


@pytest.mark.asyncio
@pytest.mark.parametrize("role,hp_factor", [("minion", 0.5), ("standard", 1), ("elite", 1.5), ("boss", 2)])
async def test_roles_are_applied_once(role, hp_factor):
    import math
    from unittest.mock import AsyncMock

    from sample_fixtures import make_context

    import combat_init
    from creature_combat import translate_creature
    from tests.combat.test_start_combat import _make_start_combat_mocks

    row = next(row for row in json.loads((ROOT / "content/creatures.json").read_text()) if row["id"] == "bandit")
    template = {
        "id": "fixture",
        "recommended_party_level": 20,
        "enemies": [{"id": "one", "creature_id": "bandit", "role": role}],
    }
    mutations, queries, content = _make_start_combat_mocks()
    content.get_encounter_template = AsyncMock(return_value=template)

    async def load(creature_id, **kwargs):
        return translate_creature(row, **kwargs)

    content.load_creature_enemy = load
    ctx = make_context()
    await combat_init._start_combat_impl(ctx, "fixture", "test", mutations=mutations, queries=queries, content=content)
    enemy = next(p for p in ctx.userdata.combat_state.participants if p.type == "enemy")
    assert enemy.hp_max == (
        max(1, int(row["hp"] * hp_factor)) if role == "minion" else math.ceil(row["hp"] * hp_factor)
    )
    assert enemy.creature_id == "bandit"
    assert enemy.catalog_audio == row["audio"]


@pytest.mark.asyncio
async def test_recommended_level_is_not_an_access_gate():
    await test_roles_are_applied_once("standard", 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("defect", ["missing", "identity", "hp", "tier", "to_hit", "second_reference"])
async def test_corrupt_catalog_fails_before_effects(defect, monkeypatch, mock_combat_agent_factory):
    from copy import deepcopy
    from unittest.mock import AsyncMock, MagicMock

    from livekit.agents.llm import ToolError
    from sample_fixtures import TEST_CREATURES, make_context

    import combat_init
    import creature_catalog
    from creature_combat_loader import load_creature_enemy
    from tests.combat.test_start_combat import _make_start_combat_mocks

    row = deepcopy(TEST_CREATURES["bandit"])
    if defect == "identity":
        row["id"] = "wrong"
    elif defect in ("hp", "tier"):
        row[defect] = True
    elif defect == "to_hit":
        row["attacks"][0]["to_hit"] = True

    async def query(creature_id):
        if defect == "missing" or creature_id == "unknown":
            raise creature_catalog.CreatureNotFoundError(creature_id)
        return row

    monkeypatch.setattr(creature_catalog, "query_creature_by_id", query)
    template = {
        "id": "fixture",
        "recommended_party_level": 1,
        "enemies": [{"id": "first", "creature_id": "bandit", "role": "standard"}],
    }
    if defect == "second_reference":
        template["enemies"].append({"id": "second", "creature_id": "unknown", "role": "standard"})
    mutations, queries, content = _make_start_combat_mocks()
    content.get_encounter_template = AsyncMock(return_value=template)
    content.load_creature_enemy = load_creature_enemy
    initiative = MagicMock()
    event, sound = AsyncMock(), AsyncMock()
    monkeypatch.setattr(combat_init.combat_resolution, "roll_initiative", initiative)
    monkeypatch.setattr(combat_init, "publish_game_event", event)
    monkeypatch.setattr(combat_init, "_publish_sounds", sound)
    ctx = make_context()
    with pytest.raises(ToolError):
        await combat_init._start_combat_impl(
            ctx, "fixture", "corrupt", mutations=mutations, queries=queries, content=content
        )
    for mock in (initiative, event, sound, mutations.save_combat_state, mock_combat_agent_factory):
        mock.assert_not_called()
    assert ctx.userdata.combat_state is None and not ctx.userdata.in_combat
