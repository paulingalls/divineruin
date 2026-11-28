"""Inventory the agent's event payload producers without importing gameplay code."""

import ast
from collections import defaultdict
from collections.abc import Iterator
from pathlib import Path

from _repo_inventory import EXCLUDED, repository_files

ROOT = Path(__file__).resolve().parents[1]
EVENT_TYPES = Path("event_types.py")
OWNERS = {
    "HP_CHANGED": ("hp_changed_payload.from_player", "hp_changed_payload.from_participant"),
    "DISPOSITION_CHANGED": ("disposition.build_disposition_changed_payload",),
    "DICE_ROLL": (
        "dice_roll_payloads.build_attack_dice_roll_payload",
        "dice_roll_payloads.build_skill_dice_roll_payload",
        "dice_roll_payloads.build_saving_throw_dice_roll_payload",
        "dice_roll_payloads.build_narrative_dice_roll_payload",
        "dice_roll_payloads.build_death_save_dice_roll_payload",
    ),
    "SESSION_INIT": ("db_session_queries.get_session_init_payload",),
    "CURRENCY_GAINED": ("db_mutations_inventory.credit_player_gold",),
    "CURRENCY_SPENT": ("db_mutations_inventory.debit_player_gold",),
    "DIVINE_FAVOR_CHANGED": ("favor_rules.build_divine_favor_changed_payload",),
    "COMBAT_UI_UPDATE": ("combat_ui_update.build_combat_ui_update",),
    "ITEM_ACQUIRED": ("tool_support.build_item_acquired_payload",),
    "INVENTORY_UPDATED": (
        "inventory_refresh.inventory_payload",
        "db_inventory_snapshot.get_inventory_snapshot",
        "db_queries.get_inventory_snapshot",
    ),
}
UNOWNED = {
    "PLAY_SOUND": "Sound playback command.",
    "SET_MUSIC_STATE": "Music state command.",
    "DICE_RESULT": "Client-only dice alias.",
    "SESSION_END": "Session recap contract.",
    "LEAVE_REQUESTED": "Session departure signal.",
    "LOCATION_CHANGED": "Location transition contract.",
    "COMBAT_STARTED": "Combat entry contract.",
    "COMBAT_ENDED": "Combat exit contract.",
    "SKILL_TIER_ADVANCED": "Skill progression notification.",
    "XP_AWARDED": "XP progression notification.",
    "LEVEL_UP": "Separate leveling builders.",
    "STATUS_EFFECT": "Status notification.",
    "PLAYER_PORTRAIT_READY": "Portrait notification.",
    "ITEM_DURABILITY_HIT": "Durability notification.",
    "QUEST_UPDATED": "Quest progression contract.",
    "QUEST_UPDATE": "Client-only quest alias.",
    "RESONANCE_CHANGED": "Separate resonance_events publisher.",
    "VEIL_WARD_CHANGED": "Separate veil_ward_events scope packet.",
    "HOLLOW_ECHO_RESULT": "Separate hollow_echo_events band packet.",
    "VAELTI_ECHO_WARNING": "Internal background warning signal.",
    "HOLLOW_CORRUPTION_CHANGED": "World corruption notification.",
    "WORLD_EVENT": "World notification contract.",
    "HIDDEN_REVEALED": "Separate game_events.publish_hidden_revealed publisher.",
    "TRANSCRIPT_ENTRY": "Transcript contract.",
    "COMPANION_CUE": "Companion HUD cue.",
    "CREATION_CARDS": "Character creation card contract.",
    "CREATION_CARD_SELECTED": "Character creation selection contract.",
    "SPECIALIZATION_CHOICE": "Specialization offer contract.",
    "CREATION_CARD_TAP": "Incoming creation hint.",
    "SPECIALIZATION_CHOICE_TAP": "Incoming specialization hint.",
    "PATRON_ABILITIES_UPDATED": "Separate patron_ability_events snapshot and wire validator.",
}
CONSUMER_SETS = {
    ("DISPOSITION_CHANGED", "REBUILD_EVENT_TYPES"): "Background rebuild routing after disposition changes.",
    ("DIVINE_FAVOR_CHANGED", "REBUILD_EVENT_TYPES"): "Background rebuild routing after favor changes.",
}
FIXTURE_PUBLISHERS = {
    ("native_transport_probe", "run_probe"): "Sends patched SESSION_INIT_FIXTURE to exercise native transport.",
    ("choir_capstone_probe", "receive_commands"): "Sends patched SESSION_INIT_FIXTURE for the native Choir journey.",
}
INVENTORY_INJECTION = {
    ("crafting_tools", "_rent_workspace_impl"),
    ("repair_item", "_repair_item_impl"),
}

Scope = ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda | ast.ClassDef | ast.comprehension
Binding = ast.AST | str | None
FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
_MUTATORS = {"update", "setdefault", "pop", "popitem", "clear", "__setitem__", "__delitem__"}
COMPREHENSIONS = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)


class _Source:
    def __init__(self, module: str, tree: ast.Module) -> None:
        self.module = module
        self.scopes: dict[ast.AST, Scope] = {}
        self.parents: dict[ast.AST, ast.AST] = {}
        self.enclosing: dict[Scope, Scope] = {}
        self.bindings: dict[tuple[Scope, str], list[Binding]] = defaultdict(list)
        self.lambda_defaults: dict[ast.arg, ast.expr] = {}
        self.inventory_defaults: dict[ast.arg, ast.expr] = {}
        self._index(tree, tree)

    def _index(self, node: ast.AST, scope: Scope) -> None:
        self.scopes[node] = scope
        body_scope = scope
        body: set[ast.AST] | None = None
        if isinstance(node, (*FUNCTIONS, ast.ClassDef)):
            body_scope = node
            body = {node.body} if isinstance(node, ast.Lambda) else set(node.body)
            outer = self.enclosing[scope] if isinstance(scope, ast.ClassDef) else scope
            self.enclosing[node] = outer
            if not isinstance(node, ast.Lambda):
                identity = f"{self.module}.{node.name}" if isinstance(scope, ast.Module) else None
                self.bindings[scope, node.name].append(identity)
            if isinstance(node, FUNCTIONS):
                self._parameters(node)
        elif isinstance(node, COMPREHENSIONS):
            body_scope = node.generators[0]
            self.enclosing[body_scope] = scope
        for child in ast.iter_child_nodes(node):
            self.parents[child] = node
            if body is not None:
                # Defaults and decorators are evaluated in the enclosing scope.
                child_scope = body_scope if child in body else scope
            elif isinstance(node, ast.comprehension) and node is scope and child is node.iter:
                child_scope = self.enclosing[scope]
            else:
                child_scope = body_scope
            self._index(child, child_scope)
        self._bind(node, scope)

    def _parameters(self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda) -> None:
        args = node.args
        positional = args.posonlyargs + args.args
        defaults = dict(zip(positional[len(positional) - len(args.defaults) :], args.defaults, strict=True))
        defaults.update(
            (arg, value) for arg, value in zip(args.kwonlyargs, args.kw_defaults, strict=True) if value is not None
        )
        for arg in positional + args.kwonlyargs + [args.vararg, args.kwarg]:
            if arg is None:
                continue
            default = defaults.get(arg)
            self.bindings[node, arg.arg].append(arg)
            if isinstance(node, ast.Lambda) and default is not None:
                self.lambda_defaults[arg] = default
            if (
                default is not None
                and arg.arg == "inv_mutations_mod"
                and isinstance(node, ast.AsyncFunctionDef)
                and (self.module, node.name) in INVENTORY_INJECTION
            ):
                self.inventory_defaults[arg] = default

    def _bind(self, node: ast.AST, scope: Scope) -> None:
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.asname or alias.name.split(".")[0]
                self.bindings[scope, name].append(alias.name if alias.asname else name)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            for alias in node.names:
                self.bindings[scope, alias.asname or alias.name].append(f"{node.module}.{alias.name}")
        elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            parent = self.parents[node]
            value = parent.value if isinstance(parent, (ast.Assign, ast.AnnAssign)) else None
            if isinstance(parent, ast.NamedExpr):
                while isinstance(scope, ast.comprehension):
                    scope = self.enclosing[scope]
            self.bindings[scope, node.id].append(value)
        elif isinstance(node, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar)) and node.name:
            self.bindings[scope, node.name].append(None)
        elif isinstance(node, ast.MatchMapping) and node.rest:
            self.bindings[scope, node.rest].append(None)
        elif isinstance(node, ast.Global):
            for name in node.names:
                self.bindings[scope, name].append(None)
                self.bindings[self._module_scope(scope), name].append(None)
        elif isinstance(node, ast.Nonlocal):
            for name in node.names:
                self.bindings[scope, name].append(None)
                for outer in self._outer_scopes(scope):
                    if isinstance(outer, FUNCTIONS):
                        self.bindings[outer, name].append(None)

    def _outer_scopes(self, scope: Scope) -> Iterator[Scope]:
        while scope in self.enclosing:
            scope = self.enclosing[scope]
            yield scope

    def _module_scope(self, scope: Scope) -> Scope:
        return next(item for item in (scope, *self._outer_scopes(scope)) if isinstance(item, ast.Module))

    def _binding(self, node: ast.Name) -> tuple[Scope, list[Binding]]:
        scope = self.scopes[node]
        for candidate in (scope, *self._outer_scopes(scope)):
            if values := self.bindings.get((candidate, node.id)):
                return candidate, values
        return scope, []

    def identities(self, node: ast.AST) -> set[str | None]:
        if isinstance(node, ast.Attribute):
            return {f"{base}.{node.attr}" if base else None for base in self.identities(node.value)}
        if isinstance(node, ast.Name):
            _, values = self._binding(node)
            identities: set[str | None] = set()
            for value in values:
                if isinstance(value, str):
                    identities.add(value)
                elif isinstance(value, ast.arg) and (default := self.inventory_defaults.get(value)) is not None:
                    identities.update(self.identities(default))
                else:
                    identities.add(None)
            return identities
        return set()

    def _origins(self, value: Binding, owners: set[str]) -> Iterator[str | None]:
        if isinstance(value, ast.arg) and (default := self.lambda_defaults.get(value)) is not None:
            if isinstance(default, ast.Name):
                for binding in self._payload_bindings(default):
                    yield from self._origins(binding, owners)
            else:
                yield from self._origins(default, owners)
        elif isinstance(value, ast.IfExp):
            yield from self._origins(value.body, owners)
            yield from self._origins(value.orelse, owners)
        elif isinstance(value, ast.Constant) and value.value is None:
            return
        else:
            call = value.value if isinstance(value, ast.Await) else value
            if isinstance(call, ast.Call):
                identities = self.identities(call.func)
                if identities and identities <= owners:
                    yield None
                    return
            yield _binding_description(value)

    def _payload_bindings(self, name: ast.Name) -> list[Binding]:
        scope, values = self._binding(name)
        return values if values and isinstance(scope, FUNCTIONS) else [name]

    def _mutated(self, name: ast.Name) -> bool:
        scope = self._binding(name)[0]

        def same(node: ast.expr) -> bool:
            return isinstance(node, ast.Name) and node.id == name.id and self._binding(node)[0] is scope

        return any(
            (isinstance(node, ast.Subscript) and isinstance(node.ctx, (ast.Store, ast.Del)) and same(node.value))
            or (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in _MUTATORS
                and same(node.func.value)
            )
            for node in self.scopes
        )

    def invalid_payload(self, payload: ast.expr, owners: tuple[str, ...]) -> str | None:
        if isinstance(payload, ast.Name):
            # An owner's payload edited after the call is hand-built on top of it.
            if self._mutated(payload):
                return f"{payload.id} (mutated after its owner call)"
            values = self._payload_bindings(payload)
        elif isinstance(payload, (ast.Call, ast.Await)):
            values = [payload]
        else:
            return ast.unparse(payload)
        owner_set = set(owners)
        origins = {origin for value in values for origin in self._origins(value, owner_set)}
        invalid = sorted(description for description in origins if description is not None)
        if invalid or None not in origins:
            found = ", ".join(invalid) or "no owner call"
            return f"{ast.unparse(payload)} (origin: {found})"
        return None


def _binding_description(value: Binding) -> str:
    if isinstance(value, (ast.expr, ast.arg)):
        return ast.unparse(value)
    return value if isinstance(value, str) else "<unsupported binding>"


def _declarations(tree: ast.Module) -> tuple[dict[str, tuple[str, int]], list[str]]:
    events: dict[str, tuple[str, int]] = {}
    failures = []
    for statement in tree.body:
        if isinstance(statement, ast.Assign):
            targets = statement.targets
        elif isinstance(statement, ast.AnnAssign):
            targets = [statement.target]
        else:
            continue
        for target in targets:
            if not isinstance(target, ast.Name) or not target.id.isupper():
                continue
            value = statement.value
            if not isinstance(value, ast.Constant) or not isinstance(value.value, str) or target.id in events:
                failures.append(f"apps/agent/{EVENT_TYPES}:{target.lineno}: invalid event declaration {target.id}")
            else:
                events[target.id] = (value.value, target.lineno)
    return events, failures


def _event_names(
    node: ast.Constant | ast.Name | ast.Attribute, parent: ast.AST, source: _Source, wire_names: dict[str, str]
) -> set[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        if isinstance(parent, ast.Dict) and node in parent.keys:
            return set()
        return {wire_names[node.value]} if node.value in wire_names else set()
    if isinstance(node, (ast.Name, ast.Attribute)) and isinstance(node.ctx, ast.Load):
        identities = source.identities(node)
        return {name for name in OWNERS if f"event_types.{name}" in identities}
    return set()


def _payload(node: ast.expr, parent: ast.AST) -> ast.expr | None:
    if isinstance(parent, ast.Tuple) and len(parent.elts) == 2 and parent.elts[0] is node:
        return parent.elts[1]
    if isinstance(parent, ast.Call) and node in parent.args:
        following = parent.args[parent.args.index(node) + 1 :]
        if following:
            return following[0]
        return next((keyword.value for keyword in parent.keywords if keyword.arg == "payload"), None)
    return None


def _consumer_set(node: ast.AST, parent: ast.AST, source: _Source, event: str) -> tuple[str, str] | None:
    if source.module == "bg_event_handlers" and isinstance(parent, ast.Set) and node in parent.elts:
        assignment = source.parents[parent]
        if isinstance(assignment, ast.Assign) and len(assignment.targets) == 1:
            target = assignment.targets[0]
            if isinstance(target, ast.Name) and (event, target.id) in CONSUMER_SETS:
                return event, target.id
    return None


def _fixture_publisher(
    node: ast.AST, parent: ast.AST, source: _Source, event: str, payload: ast.expr
) -> tuple[str, str] | None:
    scope = source.scopes[node]
    if (
        event == "SESSION_INIT"
        and isinstance(scope, ast.AsyncFunctionDef)
        and isinstance(source.enclosing[scope], ast.Module)
        and (source.module, scope.name) in FIXTURE_PUBLISHERS
        and isinstance(parent, ast.Call)
        and isinstance(parent.func, ast.Name)
        and parent.func.id == "publish_game_event"
        and isinstance(payload, ast.Name)
        and payload.id == "hydration"
    ):
        return source.module, scope.name
    return None


def test_event_payload_producers_use_their_owners() -> None:
    paths = sorted(
        path
        for path in repository_files(ROOT, "*.py", untracked=True)
        if not (set(path.parts) & (EXCLUDED | {"tests"}))
    )
    assert EVENT_TYPES in paths, f"apps/agent/{EVENT_TYPES}: missing from production source inventory"
    trees = {path: ast.parse((ROOT / path).read_bytes(), filename=str(path)) for path in paths}
    events, failures = _declarations(trees.pop(EVENT_TYPES))
    assert trees, "empty agent production source inventory"
    classified = OWNERS.keys() | UNOWNED.keys()
    failures.extend(
        f"apps/agent/{EVENT_TYPES}:{events[event][1]}: unclassified event {event}"
        for event in events.keys() - classified
    )
    failures.extend(f"stale event classification: {event}" for event in classified - events.keys())
    failures.extend(f"event both owned and unowned: {event}" for event in OWNERS.keys() & UNOWNED.keys())
    failures.extend(f"unowned event {event} needs a reason" for event, reason in UNOWNED.items() if not reason.strip())
    wire_names = {wire: event for event, (wire, _) in events.items() if event in OWNERS}
    checked: set[str] = set()
    consumer_sets: set[tuple[str, str]] = set()
    fixture_publishers: set[tuple[str, str]] = set()
    for path, tree in trees.items():
        source = _Source(".".join(path.with_suffix("").parts), tree)
        for node, parent in source.parents.items():
            if not isinstance(node, (ast.Constant, ast.Name, ast.Attribute)):
                continue
            for event in _event_names(node, parent, source, wire_names):
                location = f"apps/agent/{path}:{node.lineno}"
                if isinstance(parent, ast.Compare):
                    continue
                if consumer := _consumer_set(node, parent, source, event):
                    assert consumer not in consumer_sets, f"{location}: repeated consumer exemption {consumer}"
                    consumer_sets.add(consumer)
                    continue
                if (payload := _payload(node, parent)) is None:
                    failures.append(f"{location}: {event}: unclassified reference {ast.unparse(node)}")
                    continue
                if fixture := _fixture_publisher(node, parent, source, event, payload):
                    assert fixture not in fixture_publishers, f"{location}: repeated publisher exemption {fixture}"
                    fixture_publishers.add(fixture)
                    continue
                checked.add(event)
                if invalid := source.invalid_payload(payload, OWNERS[event]):
                    failures.append(f"{location}: {event}: expected {' or '.join(OWNERS[event])}; found {invalid}")
    failures.extend(f"no checked production publication for {event}" for event in OWNERS.keys() - checked)
    for listed, seen in ((CONSUMER_SETS, consumer_sets), (FIXTURE_PUBLISHERS, fixture_publishers)):
        failures.extend(f"stale event reference exemption: {entry}" for entry in listed.keys() - seen)
        failures.extend(
            f"event reference exemption {entry} needs a reason"
            for entry, reason in listed.items()
            if not reason.strip()
        )
    owner_list = "\n".join(f"{event}: {', '.join(owners)}" for event, owners in sorted(OWNERS.items()))
    assert not failures, "Event payload owners:\n" + owner_list + "\n\n" + "\n".join(sorted(failures))
