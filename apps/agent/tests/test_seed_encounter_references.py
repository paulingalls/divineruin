import importlib.util
import json
from unittest.mock import AsyncMock

import pytest
from test_encounter_references import CASES, ROOT

spec = importlib.util.spec_from_file_location("seed_references", ROOT / "scripts/seed_content.py")
assert spec is not None and spec.loader is not None
seed_content = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seed_content)


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES["invalid"], ids=lambda case: case["name"])
async def test_seed_shared_reference_cases(case, tmp_path, monkeypatch):
    (tmp_path / "encounter_templates.json").write_text(json.dumps([case["encounter"]]))
    (tmp_path / "creatures.json").write_text((ROOT / "content/creatures.json").read_text())
    monkeypatch.setattr(seed_content, "CONTENT_DIR", tmp_path)
    conn = AsyncMock()
    with pytest.raises(seed_content.InvalidContent, match=case["field"]):
        await seed_content.seed(conn)
    assert not any("INSERT INTO encounter_templates" in call.args[0] for call in conn.execute.call_args_list)


@pytest.mark.asyncio
async def test_seed_all_eleven_templates():
    conn = AsyncMock()
    counts = await seed_content.seed(conn)
    assert counts["encounter_templates"] == 11
    writes = [
        json.loads(call.args[2])
        for call in conn.execute.call_args_list
        if "INSERT INTO encounter_templates" in call.args[0]
    ]
    assert len(writes) == 11
    assert all(set(enemy) == {"id", "creature_id", "role"} for row in writes for enemy in row["enemies"])


class StoredConnection:
    def __init__(self, encounters=None, creatures=None):
        self.encounters = (
            encounters
            if encounters is not None
            else json.loads((ROOT / "content/encounter_templates.json").read_text())
        )
        self.creatures = (
            creatures if creatures is not None else json.loads((ROOT / "content/creatures.json").read_text())
        )

    async def fetch(self, query):
        table = query.split("FROM ")[1].split()[0]
        if table == "encounter_templates":
            rows = self.encounters
        elif table == "creatures":
            rows = self.creatures
        else:
            path = ROOT / "content" / f"{table}.json"
            rows = json.loads(path.read_text()) if path.exists() else []
        return [{"id": row["id"], "data": json.dumps(row)} for row in rows]


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES["invalid"], ids=lambda case: case["name"])
async def test_seed_stored_reference_cases(case):
    conn = StoredConnection(encounters=[case["encounter"]])
    assert conn.creatures and conn.encounters
    errors = await seed_content.validate(conn)
    assert any(case["field"] in error and "fixture" in error for error in errors), errors


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [("tier", True), ("category", ""), ("loot_table_id", "unknown")])
async def test_seed_catalog_loot_and_tier_guards(field, value):
    conn = StoredConnection()
    row = next(row for row in conn.creatures if row["id"] == conn.encounters[0]["enemies"][0]["creature_id"])
    row[field] = value
    errors = await seed_content.validate(conn)
    assert any("Encounter" in error and field in error for error in errors), errors


@pytest.mark.asyncio
@pytest.mark.parametrize("corpus", ["encounters", "creatures"])
async def test_seed_empty_reference_corpora(corpus, tmp_path, monkeypatch):
    for name in ("encounter_templates", "creatures"):
        (tmp_path / f"{name}.json").write_text((ROOT / "content" / f"{name}.json").read_text())
    filename = "encounter_templates" if corpus == "encounters" else "creatures"
    (tmp_path / f"{filename}.json").write_text("[]")
    monkeypatch.setattr(seed_content, "CONTENT_DIR", tmp_path)
    with pytest.raises(seed_content.InvalidContent, match="nonempty"):
        await seed_content.seed(AsyncMock())
    conn = StoredConnection(**{corpus: []})
    errors = await seed_content.validate(conn)
    assert any("nonempty" in error for error in errors), errors
