import asyncio
import copy
import json

import asyncpg
import pytest
from acceptance.test_creature_catalog import ROOT, seed_content


def test_seed_rejects_invalid_creature_terrains(fresh_migrated_db, tmp_path, monkeypatch):
    monkeypatch.setattr(seed_content, "CONTENT_DIR", tmp_path)
    (tmp_path / "encounter_templates.json").write_bytes((ROOT / "content/encounter_templates.json").read_bytes())
    authored = json.loads((ROOT / "content/creatures.json").read_text())
    cases = [
        (None, "terrains: required"),
        ("forest", "terrains: expected array"),
        ([], "terrains: expected non-empty array"),
        (["forest", "atlantis"], "terrains[1]: unknown terrain"),
        ([{}], "terrains[0]: expected string"),
    ]

    async def check():
        conn = await asyncpg.connect(fresh_migrated_db)
        try:
            for value, diagnostic in cases:
                rows = copy.deepcopy(authored)
                if value is None:
                    rows[0].pop("terrains", None)
                else:
                    rows[0]["terrains"] = value
                (tmp_path / "creatures.json").write_text(json.dumps(rows))
                with pytest.raises(seed_content.InvalidContent) as error:
                    async with conn.transaction():
                        await seed_content.seed(conn)
                assert str(error.value) == f"{rows[0]['id']}: {diagnostic}"
        finally:
            await conn.close()

    asyncio.run(check())
