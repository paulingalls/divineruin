import json
from pathlib import Path

import pytest
from _encounter_reference_proofs import assert_reference_corpus_inventory, assert_reference_fixture_walk

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
    initiative = MagicMock(wraps=combat_init.combat_resolution.roll_initiative)
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
        template = {
            **template,
            "enemies": [
                {"id": "first", "creature_id": "bandit", "role": "standard"},
                {"id": "second", "creature_id": "unknown", "role": "standard"},
            ],
        }
    mutations, queries, content = _make_start_combat_mocks()
    content.get_encounter_template = AsyncMock(return_value=template)
    content.load_creature_enemy = load_creature_enemy
    initiative = MagicMock(wraps=combat_init.combat_resolution.roll_initiative)
    event, sound = AsyncMock(), AsyncMock()
    monkeypatch.setattr(combat_init.combat_resolution, "roll_initiative", initiative)
    monkeypatch.setattr(combat_init, "publish_game_event", event)
    monkeypatch.setattr(combat_init, "_publish_sounds", sound)
    ctx = make_context()
    ctx.userdata.party.primary.weapon_used = True
    ctx.userdata.party.primary.draethar_inner_fire_used = True
    before = (list(ctx.userdata.recent_events), ctx.userdata.pre_combat_agent_type, ctx.userdata.party.to_dict())
    with pytest.raises(ToolError):
        await combat_init._start_combat_impl(
            ctx, "fixture", "corrupt", mutations=mutations, queries=queries, content=content
        )
    for mock in (initiative, event, sound, mutations.save_combat_state, mock_combat_agent_factory):
        mock.assert_not_called()
    assert ctx.userdata.combat_state is None and not ctx.userdata.in_combat
    assert (
        list(ctx.userdata.recent_events),
        ctx.userdata.pre_combat_agent_type,
        ctx.userdata.party.to_dict(),
    ) == before


def test_reference_corpora_and_discovered_fixture_absence():
    assert len(CASES["invalid"]) >= 50 and len(CASES["valid"]) >= 2 and CASES["fixture_catalog"]
    fixtures = assert_reference_fixture_walk(ROOT / "apps/agent/tests")
    assert any(path.name == "sample_fixtures.py" for path, _ in fixtures)
    assert any(path.name == "test_start_combat.py" for path, _ in fixtures)
    for case in CASES["valid"]:
        validate_encounter_references(case, CATALOG)


def test_reference_fixture_walk_rejects_missing_empty_and_moved_flat_fixture(tmp_path):
    with pytest.raises(AssertionError, match="missing Python"):
        assert_reference_fixture_walk(tmp_path / "missing")
    (tmp_path / "empty.py").write_text("x = {}")
    with pytest.raises(AssertionError, match="missing combat-entry"):
        assert_reference_fixture_walk(tmp_path)
    moved = tmp_path / "new_directory"
    moved.mkdir()
    fixture = moved / "fixture.py"
    fixture.write_text('x = {"enemies": [{"id": "one", "hp": 7}]}')
    with pytest.raises(AssertionError):
        assert_reference_fixture_walk(tmp_path)
    fixture.write_text('x = {"enemies": [{"id": "one", "creature_id": "bandit", "role": "standard"}]}')
    assert assert_reference_fixture_walk(tmp_path) == [(fixture, 1)]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "defect",
    [
        "no_state",
        "dead_player",
        "no_save",
        "stale_save",
        "no_packets",
        "no_companion",
        "defeat",
        "no_reward",
        "live_victory",
        "saved_victory",
        "unpaid_victory",
        "unknown",
    ],
)
async def test_boundary_result_refuses_uncommitted_or_unusable_outcomes(defect, monkeypatch):
    from unittest.mock import AsyncMock

    from acceptance._catalog_cutover_helpers import assert_boundary_result
    from combat._helpers import _make_combat_state
    from sample_fixtures import make_context, make_mock_room

    import db_mutations
    import db_queries

    ctx = make_context(room=make_mock_room())
    state = _make_combat_state()
    ctx.userdata.combat_state = state
    load = AsyncMock(return_value=state)
    monkeypatch.setattr(db_mutations, "load_combat_state", load)
    monkeypatch.setattr(db_queries, "get_player", AsyncMock(return_value={"xp": 2}))
    result = {"packets": [{"actor_id": "companion"}]}
    if defect in {"defeat", "no_reward", "live_victory", "saved_victory", "unpaid_victory"}:
        ctx.userdata.combat_state = None
        load.return_value = None
        outcome = {"outcome": "victory", "xp_total": 1}
        result = (None, json.dumps(outcome))
        await ctx.userdata.room.local_participant.publish_data(json.dumps({"packets": [{"actor_id": "companion"}]}))
        if defect == "defeat":
            outcome["outcome"] = "defeat"
        elif defect == "no_reward":
            outcome["xp_total"] = 0
        elif defect == "live_victory":
            ctx.userdata.combat_state = state
        elif defect == "saved_victory":
            load.return_value = state
        elif defect == "unpaid_victory":
            monkeypatch.setattr(db_queries, "get_player", AsyncMock(return_value={"xp": 1}))
        result = (None, json.dumps(outcome))
    elif defect == "no_state":
        ctx.userdata.combat_state = None
    elif defect == "dead_player":
        player = state.get_participant(ctx.userdata.player_id)
        assert player is not None
        player.hp_current = 0
    elif defect == "no_save":
        load.return_value = None
    elif defect == "stale_save":
        load.return_value = _make_combat_state(player_hp=1)
    elif defect == "no_packets":
        result = {"packets": []}
    elif defect == "no_companion":
        result = {"packets": [{"actor_id": ctx.userdata.player_id}]}
    elif defect == "unknown":
        result = None
    with pytest.raises(AssertionError):
        await assert_boundary_result(ctx, result, state.combat_id, "companion", 1)


@pytest.mark.parametrize(
    "producer",
    [
        'flat = {"id": "old", "hp": 7}\nentry = {"enemies": [flat]}',
        'flat = [{"id": "old", "hp": 7}]\nentry = {"enemies": flat}',
        'from legacy import enemies\nentry = {"enemies": enemies}',
    ],
)
def test_reference_walk_refuses_unresolved_flat_producers(tmp_path, producer):
    (tmp_path / "valid.py").write_text(
        'entry = {"enemies": [{"id": "one", "creature_id": "bandit", "role": "standard"}]}'
    )
    (tmp_path / "legacy.py").write_text('enemies = [{"id": "old", "hp": 7}]')
    (tmp_path / "indirect.py").write_text(producer)
    with pytest.raises(AssertionError):
        assert_reference_fixture_walk(tmp_path)


@pytest.mark.parametrize(
    "producer",
    [
        'enemy = {"id": "one", "creature_id": "bandit", "role": "standard"}\nentry = {"enemies": [enemy]}',
        'enemies = [{"id": "one", "creature_id": "bandit", "role": "standard"}]\nentry = {"enemies": enemies}',
        'from catalog_fixture import enemies\nentry = {"enemies": enemies}',
    ],
)
def test_reference_walk_accepts_resolved_reference_producers(tmp_path, producer):
    (tmp_path / "catalog_fixture.py").write_text(
        'enemies = [{"id": "one", "creature_id": "bandit", "role": "standard"}]'
    )
    (tmp_path / "entry.py").write_text(producer)
    assert assert_reference_fixture_walk(tmp_path)


@pytest.mark.parametrize("defect", ["empty", "missing_import", "cycle", "call", "invalid_role", "missing_id", "spread"])
def test_reference_walk_corpus_floors(tmp_path, defect):
    sources = {
        "empty": 'entry = {"enemies": []}',
        "spread": 'entry = {"enemies": [{"id": "one", "creature_id": "bandit", "role": "standard", **overrides}]}',
        "missing_import": 'from missing import enemies\nentry = {"enemies": enemies}',
        "cycle": 'one = two\ntwo = one\nentry = {"enemies": two}',
        "call": 'entry = {"enemies": produce()}',
        "invalid_role": 'entry = {"enemies": [{"id": "one", "creature_id": "bandit", "role": "named"}]}',
        "missing_id": 'entry = {"enemies": [{"creature_id": "bandit", "role": "standard"}]}',
    }
    (tmp_path / "entry.py").write_text(sources[defect])
    with pytest.raises(AssertionError):
        assert_reference_fixture_walk(tmp_path)


@pytest.mark.parametrize(
    "field",
    [
        "hp",
        "ac",
        "level",
        "tier",
        "name",
        "attributes",
        "action_pool",
        "xp_value",
        "loot_table_id",
        "category",
        "sound_signature",
        "signature_ability",
        "legendary_actions",
        "currency",
        "audio",
        "narration",
        "override",
    ],
)
def test_reference_walk_rejects_inline_fields(tmp_path, field):
    moved = tmp_path / "moved"
    moved.mkdir()
    (moved / "producer.py").write_text(
        f'enemy = {{"id": "one", "creature_id": "bandit", "role": "standard", "{field}": 1}}\n'
        'enemies = [enemy]\nentry = {"enemies": enemies}'
    )
    with pytest.raises(AssertionError):
        assert_reference_fixture_walk(tmp_path)


@pytest.mark.asyncio
async def test_start_validation_precedes_each_effect(monkeypatch, mock_combat_agent_factory):
    await test_corrupt_catalog_fails_before_effects("second_reference", monkeypatch, mock_combat_agent_factory)


@pytest.mark.asyncio
@pytest.mark.parametrize("victory", [False, True])
async def test_boundary_result_accepts_committed_controls(victory, monkeypatch):
    from unittest.mock import AsyncMock

    from acceptance._catalog_cutover_helpers import assert_boundary_result
    from combat._helpers import _make_combat_state
    from sample_fixtures import make_context, make_mock_room

    import db_mutations
    import db_queries

    ctx = make_context(room=make_mock_room())
    state = _make_combat_state()
    ctx.userdata.combat_state = None if victory else state
    monkeypatch.setattr(db_mutations, "load_combat_state", AsyncMock(return_value=None if victory else state))
    monkeypatch.setattr(db_queries, "get_player", AsyncMock(return_value={"xp": 2}))
    if victory:
        await ctx.userdata.room.local_participant.publish_data(json.dumps({"packets": [{"actor_id": "companion"}]}))
        result = (None, json.dumps({"outcome": "victory", "xp_total": 1}))
    else:
        result = {"packets": [{"actor_id": "companion"}]}
    await assert_boundary_result(ctx, result, state.combat_id, "companion", 1)


def test_reference_inventory_has_reachable_corpus_floors(tmp_path):
    import shutil

    assert_reference_corpus_inventory(ROOT)
    for directory in ("content", "packages/shared", "apps/agent/tests"):
        shutil.copytree(ROOT / directory, tmp_path / directory)
    for file in ("scripts/seed_content.py", "apps/agent/combat_init.py", "apps/agent/encounter_references.py"):
        target = tmp_path / file
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / file, target)
    assert_reference_corpus_inventory(tmp_path)
    for file, replacement in [
        ("content/creatures.json", "[]"),
        ("content/encounter_templates.json", "[]"),
        ("packages/shared/fixtures/encounter_references.json", None),
        ("packages/shared/src/entities/encounter.ts", None),
        ("scripts/seed_content.py", None),
        ("apps/agent/combat_init.py", None),
        ("apps/agent/tests/sample_fixtures.py", None),
    ]:
        target = tmp_path / file
        original = target.read_bytes()
        target.unlink() if replacement is None else target.write_text(replacement)
        try:
            with pytest.raises(AssertionError):
                assert_reference_corpus_inventory(tmp_path)
        finally:
            target.write_bytes(original)


def test_reference_walk_validates_dictionary_constructor_producers(tmp_path):
    (tmp_path / "valid.py").write_text(
        'entry = {"enemies": [{"id": "one", "creature_id": "bandit", "role": "standard"}]}'
    )
    fixture = tmp_path / "constructor.py"
    fixture.write_text('entry = dict(enemies=[dict(id="one", hp=7)])')
    with pytest.raises(AssertionError):
        assert_reference_fixture_walk(tmp_path)
    fixture.write_text('entry = dict(enemies=[dict(id="one", creature_id="bandit", role="standard")])')
    assert assert_reference_fixture_walk(tmp_path)


def test_reference_walk_does_not_exempt_analyzer_named_fixture_functions(tmp_path):
    (tmp_path / "valid.py").write_text(
        'entry = {"enemies": [{"id": "one", "creature_id": "bandit", "role": "standard"}]}'
    )
    (tmp_path / "moved.py").write_text(
        'def assert_reference_fixture_walk():\n    entry = {"enemies": [{"id": "one", "hp": 7}]}'
    )
    with pytest.raises(AssertionError):
        assert_reference_fixture_walk(tmp_path)


def test_catalog_projection_rejects_reference_overrides(tmp_path, monkeypatch):
    import sample_fixtures

    templates = json.loads((ROOT / "content/encounter_templates.json").read_text())
    templates[0]["enemies"][0]["hp"] = 7
    content = tmp_path / "content"
    content.mkdir()
    (content / "encounter_templates.json").write_text(json.dumps(templates))
    monkeypatch.setattr(sample_fixtures, "CONTENT_ROOT", tmp_path)
    with pytest.raises(ValueError, match="forbidden reference fields"):
        sample_fixtures.catalog_encounters()


@pytest.mark.parametrize("nested", [False, True])
def test_reference_walk_does_not_resolve_from_unrelated_scopes(tmp_path, nested):
    valid = '[{"id": "one", "creature_id": "bandit", "role": "standard"}]'
    lines = [
        'enemies = [{"id": "old", "hp": 7}]',
        "def unrelated():",
        f"    enemies = {valid}",
        'entry = {"enemies": enemies}',
    ]
    if nested:
        lines = ["def producer():", *["    " + line for line in lines]]
    (tmp_path / "producer.py").write_text("\n".join(lines))
    (tmp_path / "valid.py").write_text(f'entry = {{"enemies": {valid}}}')
    with pytest.raises(AssertionError):
        assert_reference_fixture_walk(tmp_path)


def test_reference_walk_refuses_conditional_producer(tmp_path):
    (tmp_path / "producer.py").write_text(
        'enemies = [{"id": "old", "hp": 7}]\n'
        "if flag:\n"
        '    enemies = [{"id": "one", "creature_id": "bandit", "role": "standard"}]\n'
        'entry = {"enemies": enemies}'
    )
    with pytest.raises(AssertionError, match="conditional fixture producer"):
        assert_reference_fixture_walk(tmp_path)
