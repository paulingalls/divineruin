import pytest
from _encounter_reference_proofs import assert_reference_fixture_walk


@pytest.mark.parametrize(
    "mutation",
    [
        'entry["enemies"] = [{"id": "legacy", "hp": 7, "action_pool": []}]',
        'entry["enemies"].append({"id": "legacy", "hp": 7})',
        'entry.update(enemies=[{"id": "legacy", "hp": 7}])',
        'alias = entry\nalias["enemies"].clear()',
        'del entry["enemies"]',
        'enemies.append({"id": "legacy", "hp": 7})',
    ],
)
def test_walk_refuses_mutated_encounter_producers(tmp_path, mutation):
    source = (
        'enemies = [{"id": "one", "creature_id": "bandit", "role": "standard"}]\n'
        'entry = {"enemies": enemies}\n' + mutation
    )
    (tmp_path / "producer.py").write_text(source)
    with pytest.raises(AssertionError, match="mutated fixture producer"):
        assert_reference_fixture_walk(tmp_path)


@pytest.mark.parametrize(
    "statement",
    [
        'from producer import entry as imported\nimported["enemies"] = [{"id": "legacy", "hp": 7}]',
        'import producer as module\nmodule.entry["enemies"] = [{"id": "legacy", "hp": 7}]',
    ],
)
def test_walk_refuses_mutation_through_import(tmp_path, statement):
    (tmp_path / "producer.py").write_text(
        'entry = {"enemies": [{"id": "one", "creature_id": "bandit", "role": "standard"}]}'
    )
    (tmp_path / "consumer.py").write_text(statement)
    with pytest.raises(AssertionError, match="mutated fixture producer"):
        assert_reference_fixture_walk(tmp_path)
