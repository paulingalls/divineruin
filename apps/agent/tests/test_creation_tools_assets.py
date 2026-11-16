import hashlib
import json

from asset_utils import compute_asset_id


class TestComputeAssetId:
    def test_deterministic(self):
        a = compute_asset_id("npc_portrait", {"description": "a guard", "features": "tall"})
        b = compute_asset_id("npc_portrait", {"description": "a guard", "features": "tall"})
        assert a == b

    def test_different_vars_produce_different_ids(self):
        a = compute_asset_id("npc_portrait", {"description": "a guard", "features": "tall"})
        b = compute_asset_id("npc_portrait", {"description": "a mage", "features": "thin"})
        assert a != b

    def test_format(self):
        result = compute_asset_id("test", {"key": "val"})
        assert result.startswith("img_")
        assert len(result) == 4 + 16  # "img_" + 16 hex chars

    def test_matches_typescript_algorithm(self):
        template_id = "npc_portrait"
        vars = {"description": "a guard", "features": "tall"}
        sorted_entries = sorted(vars.items())
        payload = template_id + json.dumps(sorted_entries)
        expected_hash = hashlib.sha256(payload.encode()).hexdigest()[:16]
        expected = f"img_{expected_hash}"
        assert compute_asset_id(template_id, vars) == expected

    def test_key_order_independent(self):
        a = compute_asset_id("t", {"b": "2", "a": "1"})
        b = compute_asset_id("t", {"a": "1", "b": "2"})
        assert a == b
