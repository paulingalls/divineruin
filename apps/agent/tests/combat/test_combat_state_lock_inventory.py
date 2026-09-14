"""Closed inventory and concurrency guards for full CombatState persistence."""

import ast
import asyncio
from collections import Counter
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from combat._helpers import _declarations, _make_combat_state
from combat.test_combat_resolution_roles import _boss_combat_state
from combat.test_start_combat import _make_start_combat_mocks
from livekit.agents.llm import ToolError
from sample_fixtures import make_context
from test_veil_ward_tools import _combat_mod, _in_combat, _invoke, _mocks, _player

from combat_init import _start_combat_impl
from combat_turn import _consume_legendary_action_impl, _declare_phase_impl
from session_data import CombatState

_AGENT_ROOT = Path(__file__).resolve().parents[2]
EXEMPT_FULL_STATE_SAVES = frozenset()


class _ObservedLock:
    def __init__(self):
        self._lock = asyncio.Lock()
        self.attempted = asyncio.Event()

    async def acquire(self):
        self.attempted.set()
        return await self._lock.acquire()

    def release(self):
        self._lock.release()

    def locked(self):
        return self._lock.locked()

    async def __aenter__(self):
        await self.acquire()
        return self

    async def __aexit__(self, *_exc):
        self.release()


def _save_references() -> Counter:
    """Return every production reference to save_combat_state, including aliases."""
    found = Counter()

    for path in sorted(_AGENT_ROOT.glob("*.py")):
        tree = ast.parse(path.read_text())
        aliases = {
            alias.asname or alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
            if alias.name == "save_combat_state"
        }

        def visit(node, function="<module>", parent=None, *, module_name=path.name, imported_aliases=aliases):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                function = node.name
            if isinstance(node, ast.ImportFrom) and any(alias.name == "save_combat_state" for alias in node.names):
                found[(module_name, function, "import")] += 1
            if isinstance(node, ast.Attribute) and node.attr == "save_combat_state" and isinstance(node.ctx, ast.Load):
                found[
                    (module_name, function, "call" if isinstance(parent, ast.Call) and parent.func is node else "value")
                ] += 1
            if (
                isinstance(node, ast.Name)
                and node.id in ({"save_combat_state"} | imported_aliases)
                and isinstance(node.ctx, ast.Load)
            ):
                found[
                    (module_name, function, "call" if isinstance(parent, ast.Call) and parent.func is node else "value")
                ] += 1
            for child in ast.iter_child_nodes(node):
                visit(child, function, node)

        visit(tree)
    return found


def _production_callers() -> dict[tuple[str, str], set[tuple[str, str]]]:
    functions: dict[str, list[tuple[str, str]]] = {}
    calls: list[tuple[str, str, str]] = []
    for path in sorted(_AGENT_ROOT.glob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            functions.setdefault(node.name, []).append((path.name, node.name))
            for child in ast.walk(node):
                if not isinstance(child, ast.Call):
                    continue
                if isinstance(child.func, ast.Name):
                    calls.append((path.name, node.name, child.func.id))
                elif isinstance(child.func, ast.Attribute):
                    calls.append((path.name, node.name, child.func.attr))
    callers: dict[tuple[str, str], set[tuple[str, str]]] = {}
    for caller_file, caller_name, callee_name in calls:
        for callee in functions.get(callee_name, []):
            callers.setdefault(callee, set()).add((caller_file, caller_name))
    return callers


def _lock_owners() -> set[tuple[str, str]]:
    owners = set()
    for path in sorted(_AGENT_ROOT.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for child in ast.walk(node):
                if isinstance(child, ast.AsyncWith) and any(
                    isinstance(part.context_expr, ast.Attribute) and part.context_expr.attr == "combat_end_lock"
                    for part in child.items
                ):
                    owners.add((path.name, node.name))
    return owners


def test_every_full_state_save_has_one_known_locked_route():
    expected = Counter(
        {
            ("combat_init.py", "_start_combat_locked", "call"): 1,
            ("veil_ward_tools.py", "_activate_veil_ward_locked", "call"): 1,
            ("veil_ward_tools.py", "_dismiss_impl", "call"): 1,
            ("combat_turn.py", "_declare_phase_locked", "call"): 1,
            ("combat_turn.py", "_resolve_phase_locked", "call"): 1,
            ("combat_turn.py", "_consume_legendary_action_locked", "call"): 1,
            ("combat_wrap.py", "wrap_phase", "call"): 1,
            ("combat_death_save.py", "_request_death_save_locked", "call"): 1,
            ("draethar_inner_fire.py", "_inner_fire_locked", "call"): 2,
        }
    )
    assert _save_references() == expected
    assert not EXEMPT_FULL_STATE_SAVES


FORMERLY_UNLOCKED = {"veil_raise", "veil_dismiss", "declare_phase", "consume_legendary_action", "combat_init"}


def test_runtime_inventory_names_all_five_formerly_unlocked_writers():
    assert {
        "veil_raise",
        "veil_dismiss",
        "declare_phase",
        "consume_legendary_action",
        "combat_init",
    } == FORMERLY_UNLOCKED


async def _run_writer(name, observations):
    if name.startswith("veil_"):
        ctx, db_mod, queries, persistence, ward_mut = _mocks(_player())
        combat = _in_combat(ctx)
        combat.veil_ward = {"source": "cleric", "rounds_remaining": None} if name == "veil_dismiss" else None
        mutations = _combat_mod()
        mutations.save_combat_state = AsyncMock(
            side_effect=lambda *_args, **_kwargs: observations.append(ctx.userdata.combat_end_lock.locked())
        )
        await _invoke(
            ctx,
            db_mod,
            queries,
            persistence,
            ward_mut,
            active=name == "veil_raise",
            combat_mod=mutations,
        )
        return ctx
    if name == "declare_phase":
        ctx = make_context()
        ctx.userdata.combat_state = _make_combat_state()
        mutations = MagicMock(
            save_combat_state=AsyncMock(
                side_effect=lambda *_args, **_kwargs: observations.append(ctx.userdata.combat_end_lock.locked())
            )
        )
        await _declare_phase_impl(ctx, _declarations(), mutations=mutations)
        return ctx
    if name == "consume_legendary_action":
        ctx = make_context()
        ctx.userdata.combat_state = _boss_combat_state()
        mutations = MagicMock(
            save_combat_state=AsyncMock(
                side_effect=lambda *_args, **_kwargs: observations.append(ctx.userdata.combat_end_lock.locked())
            )
        )
        await _consume_legendary_action_impl(ctx, "warlord_1", mutations=mutations)
        return ctx
    ctx = make_context()
    mutations, queries, content = _make_start_combat_mocks()
    mutations.save_combat_state = AsyncMock(
        side_effect=lambda *_args, **_kwargs: observations.append(ctx.userdata.combat_end_lock.locked())
    )
    await _start_combat_impl(ctx, "goblin_patrol", "Ambush!", mutations=mutations, queries=queries, content=content)
    return ctx


@pytest.mark.parametrize("writer", sorted(FORMERLY_UNLOCKED))
async def test_formerly_unlocked_writer_saves_under_the_session_lock(writer, mock_combat_agent_factory):
    seen = []
    await _run_writer(writer, seen)
    assert seen == [True]


class _OrderTransaction:
    def __init__(self, session, observations):
        self.session = session
        self.observations = observations
        self.conn = object()

    async def __aenter__(self):
        self.observations.append(self.session.combat_end_lock.locked())
        return self.conn

    async def __aexit__(self, *_exc):
        return False


@pytest.mark.parametrize("active", [True, False], ids=["raise", "dismiss"])
async def test_veil_ward_takes_session_lock_before_transaction(active):
    ctx, db_mod, queries, persistence, ward_mut = _mocks(_player(), remaining=None)
    combat = _in_combat(ctx)
    if not active:
        combat.veil_ward = {"source": "cleric", "rounds_remaining": None}
    observations = []
    db_mod.transaction = lambda: _OrderTransaction(ctx.userdata, observations)

    await _invoke(ctx, db_mod, queries, persistence, ward_mut, active=active)

    assert observations == [True]


EXISTING_STATE_MUTATORS = {"veil_raise", "veil_dismiss", "declare_phase", "consume_legendary_action"}


@pytest.mark.parametrize("writer", sorted(EXISTING_STATE_MUTATORS))
async def test_concurrent_holder_change_survives_real_full_state_mutator(writer):
    save_reached = asyncio.Event()
    continue_save = asyncio.Event()
    saved = []

    async def save(_combat_id, payload, **_kwargs):
        saved.append(payload)
        save_reached.set()
        await continue_save.wait()

    if writer.startswith("veil_"):
        ctx, db_mod, queries, persistence, ward_mut = _mocks(_player())
        state = _in_combat(ctx)
        state.veil_ward = {"source": "cleric", "rounds_remaining": None} if writer == "veil_dismiss" else None
        mutations = _combat_mod()
        mutations.save_combat_state = AsyncMock(side_effect=save)

        async def invoke():
            await _invoke(
                ctx,
                db_mod,
                queries,
                persistence,
                ward_mut,
                active=writer == "veil_raise",
                combat_mod=mutations,
            )
    elif writer == "declare_phase":
        ctx = make_context()
        ctx.userdata.combat_state = _make_combat_state()
        mutations = MagicMock(save_combat_state=AsyncMock(side_effect=save))

        async def invoke():
            await _declare_phase_impl(ctx, _declarations(), mutations=mutations)
    else:
        ctx = make_context()
        ctx.userdata.combat_state = _boss_combat_state()
        mutations = MagicMock(save_combat_state=AsyncMock(side_effect=save))

        async def invoke():
            await _consume_legendary_action_impl(ctx, "warlord_1", mutations=mutations)

    lock = _ObservedLock()
    ctx.userdata.combat_end_lock = lock
    await lock.acquire()
    lock.attempted.clear()
    holder_state = CombatState.from_dict(ctx.userdata.combat_state.to_dict())
    holder_state.round_number += 10
    task = asyncio.create_task(invoke())
    attempted = asyncio.create_task(lock.attempted.wait())
    reached = asyncio.create_task(save_reached.wait())
    done, pending = await asyncio.wait({attempted, reached}, return_when=asyncio.FIRST_COMPLETED)
    assert done
    for wait in pending:
        wait.cancel()

    saved.append(holder_state.to_dict())
    ctx.userdata.combat_state = holder_state
    lock.release()
    continue_save.set()
    await task

    assert len(saved) == 2
    assert ctx.userdata.combat_state.round_number == holder_state.round_number
    if writer == "veil_raise":
        assert ctx.userdata.combat_state.veil_ward is not None
    elif writer == "veil_dismiss":
        assert ctx.userdata.combat_state.veil_ward is None
    elif writer == "declare_phase":
        assert ctx.userdata.combat_state.beat == "resolution"
    else:
        boss = ctx.userdata.combat_state.get_participant("warlord_1")
        assert boss is not None and boss.legendary_actions == 0


async def test_two_concurrent_combat_starts_create_one_row_and_refuse_one(mock_combat_agent_factory):
    ctx = make_context()
    lock = _ObservedLock()
    ctx.userdata.combat_end_lock = lock
    mutations, queries, content = _make_start_combat_mocks()
    first_save = asyncio.Event()
    release_first = asyncio.Event()
    saved_ids = []

    async def save(combat_id, _payload):
        saved_ids.append(combat_id)
        if len(saved_ids) == 1:
            first_save.set()
            await release_first.wait()

    mutations.save_combat_state = AsyncMock(side_effect=save)
    first = asyncio.create_task(
        _start_combat_impl(ctx, "goblin_patrol", "First", mutations=mutations, queries=queries, content=content)
    )
    await first_save.wait()
    lock.attempted.clear()
    second = asyncio.create_task(
        _start_combat_impl(ctx, "goblin_patrol", "Second", mutations=mutations, queries=queries, content=content)
    )
    attempted = asyncio.create_task(lock.attempted.wait())
    second_save = asyncio.create_task(_wait_for_second(saved_ids))
    _done, pending = await asyncio.wait({attempted, second_save}, return_when=asyncio.FIRST_COMPLETED)
    for wait in pending:
        wait.cancel()
    release_first.set()
    results = await asyncio.gather(first, second, return_exceptions=True)

    errors = [result for result in results if isinstance(result, ToolError)]
    assert len(set(saved_ids)) == 1
    assert len(errors) == 1 and "Already in combat" in str(errors[0])
    assert ctx.userdata.combat_state.combat_id == saved_ids[0]
    assert content.get_encounter_template.await_count == 1
    assert queries.get_player.await_count == 1


async def _wait_for_second(items):
    while len(items) < 2:
        await asyncio.sleep(0)


def test_locked_helpers_have_only_their_named_production_callers():
    callers = _production_callers()
    owners = {
        ("combat_init.py", "_start_combat_impl"),
        ("veil_ward_tools.py", "_activate_veil_ward_impl"),
        ("combat_turn.py", "_declare_phase_impl"),
        ("combat_turn.py", "_resolve_phase_impl"),
        ("combat_turn.py", "_consume_legendary_action_impl"),
        ("combat_death_save.py", "_request_death_save_impl"),
        ("draethar_inner_fire.py", "_inner_fire_impl"),
    }
    assert owners <= _lock_owners()
    expected = {
        ("combat_init.py", "_start_combat_locked"): {("combat_init.py", "_start_combat_impl")},
        ("veil_ward_tools.py", "_activate_veil_ward_locked"): {("veil_ward_tools.py", "_activate_veil_ward_impl")},
        ("veil_ward_tools.py", "_dismiss_impl"): {("veil_ward_tools.py", "_activate_veil_ward_locked")},
        ("combat_turn.py", "_declare_phase_locked"): {("combat_turn.py", "_declare_phase_impl")},
        ("combat_turn.py", "_resolve_phase_locked"): {("combat_turn.py", "_resolve_phase_impl")},
        ("combat_wrap.py", "wrap_phase"): {("combat_turn.py", "_resolve_phase_locked")},
        ("combat_turn.py", "_consume_legendary_action_locked"): {("combat_turn.py", "_consume_legendary_action_impl")},
        ("combat_death_save.py", "_request_death_save_locked"): {("combat_death_save.py", "_request_death_save_impl")},
        ("draethar_inner_fire.py", "_inner_fire_locked"): {("draethar_inner_fire.py", "_inner_fire_impl")},
    }
    for helper, named_callers in expected.items():
        assert callers[helper] == named_callers
