import json
from pathlib import Path

from gathering_tools import REGION_GATHERING_DC
from world_regions import REGION_IDS


def test_region_ids_match_shared_corpus_and_gathering_dc():
    corpus = Path(__file__).resolve().parents[3] / "packages/shared/fixtures/creature_blocks.json"
    expected = json.loads(corpus.read_text())["region_ids"]
    assert len(expected) == 7
    assert len(set(expected)) == 7
    assert list(REGION_IDS) == expected
    assert set(REGION_GATHERING_DC) == set(REGION_IDS)
