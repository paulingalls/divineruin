import json
from typing import cast

import pytest

from encounter_references import validate_encounter_references


def assert_reference_fixture_walk(root):
    import ast

    paths = sorted(root.rglob("*.py"))
    assert paths, "missing Python fixture corpus"
    trees = {path: ast.parse(path.read_text()) for path in paths}
    parent_maps = {
        path: {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
        for path, tree in trees.items()
    }
    import_nodes = {
        path: [item for item in ast.walk(tree) if isinstance(item, (ast.Import, ast.ImportFrom))]
        for path, tree in trees.items()
    }
    scopes = {
        path: [tree, *[item for item in ast.walk(tree) if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))]]
        for path, tree in trees.items()
    }
    references = []

    def bindings(scope):
        pending = list(ast.iter_child_nodes(scope))
        while pending:
            item = pending.pop()
            yield item
            if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                pending.extend(ast.iter_child_nodes(item))

    def dictionary(node):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "dict":
            assert not node.args and all(k.arg for k in node.keywords), "unresolved dictionary constructor"
            return ast.copy_location(
                ast.Dict(keys=[ast.Constant(k.arg) for k in node.keywords], values=[k.value for k in node.keywords]),
                node,
            )
        return node

    def reject_mutations(node, path, scope, imported_names=(), checked=None):
        checked = set() if checked is None else checked
        key = (path, id(scope), id(node), tuple(imported_names))
        if key in checked:
            return
        checked.add(key)
        names = set(imported_names)
        items = list(bindings(scope))
        changed = True
        while changed:
            changed = False
            for item in items:
                if not isinstance(item, (ast.Assign, ast.AnnAssign)):
                    continue
                value = item.value
                value_root = value
                while isinstance(value_root, (ast.Subscript, ast.Attribute)):
                    value_root = value_root.value
                if (node is not None and value is node) or (
                    isinstance(value_root, ast.Name) and value_root.id in names
                ):
                    for target in item.targets if isinstance(item, ast.Assign) else [item.target]:
                        if isinstance(target, ast.Name) and target.id not in names:
                            names.add(target.id)
                            changed = True
        for item in items:
            targets = []
            if isinstance(item, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                targets = item.targets if isinstance(item, ast.Assign) else [item.target]
            elif isinstance(item, ast.Delete):
                targets = item.targets
            elif (
                isinstance(item, ast.Call)
                and isinstance(item.func, ast.Attribute)
                and item.func.attr
                in {
                    "append",
                    "extend",
                    "insert",
                    "pop",
                    "remove",
                    "clear",
                    "update",
                    "setdefault",
                    "__setitem__",
                    "__delitem__",
                }
            ):
                targets = [item.func.value]
            for target in targets:
                if isinstance(target, ast.Name) and not isinstance(item, (ast.Call, ast.Delete)):
                    continue
                while isinstance(target, (ast.Subscript, ast.Attribute)):
                    target = target.value
                assert not (isinstance(target, ast.Name) and target.id in names), (
                    f"mutated fixture producer: {path}:{cast(ast.stmt | ast.expr, item).lineno} {target.id}"
                )

        if scope is trees[path] and names:
            module = str(path.relative_to(root).with_suffix("")).replace("/", ".")
            for consumer in trees:
                imports = {
                    alias.asname or alias.name
                    for item in import_nodes[consumer]
                    if isinstance(item, ast.ImportFrom) and item.module in {module, f"{root.name}.{module}"}
                    for alias in item.names
                    if alias.name in names
                }
                imports.update(
                    alias.asname or alias.name.split(".")[0]
                    for item in import_nodes[consumer]
                    if isinstance(item, ast.Import)
                    for alias in item.names
                    if alias.name in {module, f"{root.name}.{module}"}
                )
                if imports:
                    for consumer_scope in scopes[consumer]:
                        reject_mutations(None, consumer, consumer_scope, sorted(imports), checked)

    def resolve(node, path, scope, trail=()):
        if not isinstance(node, ast.Name):
            reject_mutations(node, path, scope)
            return dictionary(node)
        edge = (path, node.id)
        assert edge not in trail, f"cyclic fixture producer: {edge}"
        assignments = [
            item
            for item in bindings(scope)
            if isinstance(item, (ast.Assign, ast.AnnAssign))
            and item.lineno < node.lineno
            and any(
                isinstance(target, ast.Name) and target.id == node.id
                for target in (item.targets if isinstance(item, ast.Assign) else [item.target])
            )
        ]
        if assignments:
            latest = max(assignments, key=lambda item: item.lineno)
            ancestor = parent_maps[path][latest]
            while ancestor is not scope:
                assert not isinstance(
                    ancestor, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.TryStar, ast.Match)
                ), f"conditional fixture producer: {path}:{latest.lineno} {node.id}"
                ancestor = parent_maps[path][ancestor]
            return resolve(latest.value, path, scope, (*trail, edge))
        for item in bindings(trees[path]):
            if isinstance(item, ast.ImportFrom) and item.module:
                for alias in item.names:
                    if (alias.asname or alias.name) == node.id:
                        imported = root / (item.module.replace(".", "/") + ".py")
                        assert imported in trees, f"missing fixture producer: {imported}"
                        exported = ast.Name(id=alias.name, lineno=10**9)
                        return resolve(exported, imported, trees[imported], (*trail, edge))
        raise AssertionError(f"unresolved fixture producer: {path}:{node.lineno} {node.id}")

    for path, tree in trees.items():
        parents = parent_maps[path]
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict) and not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "dict"
                and any(k.arg == "enemies" for k in node.keywords)
            ):
                continue
            scope = node
            while scope in parents and not isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
                scope = parents[scope]
            # The analyzer's validation envelope is not a combat-entry fixture.
            parent = parents.get(node)
            if (
                path.name == "_encounter_reference_proofs.py"
                and getattr(scope, "name", None) == "assert_reference_fixture_walk"
                and isinstance(parent, ast.Call)
                and isinstance(parent.func, ast.Name)
                and parent.func.id == "validate_encounter_references"
            ):
                continue
            original_node = node
            node = dictionary(node)
            assert isinstance(node, ast.Dict)
            for key, value in zip(node.keys, node.values, strict=True):
                if not isinstance(key, ast.Constant) or key.value != "enemies":
                    continue
                reject_mutations(original_node, path, scope)
                enemies = resolve(value, path, scope)
                assert isinstance(enemies, ast.List) and enemies.elts, (path, node.lineno, "empty/non-list enemies")
                for expression in enemies.elts:
                    enemy = resolve(expression, path, scope)
                    assert isinstance(enemy, ast.Dict), (path, node.lineno, "non-object enemy")
                    fields = {k.value for k in enemy.keys if isinstance(k, ast.Constant)}
                    assert fields == {"id", "creature_id", "role"} and len(enemy.keys) == 3, (
                        path,
                        enemy.lineno,
                        fields,
                    )
                    if all(isinstance(v, ast.Constant) for v in enemy.values):
                        reference = ast.literal_eval(enemy)
                        try:
                            validate_encounter_references(dict(recommended_party_level=1, enemies=[reference]))
                        except ValueError as error:
                            raise AssertionError(f"{path}:{enemy.lineno}: {error}") from error
                    references.append((path, enemy.lineno))
    assert references, "missing combat-entry fixture references"
    return references


def assert_reference_corpus_inventory(root):
    required = [
        "content/encounter_templates.json",
        "content/creatures.json",
        "packages/shared/fixtures/encounter_references.json",
        "packages/shared/src/entities/encounter.ts",
        "packages/shared/src/entities/encounter-references.test.ts",
        "scripts/seed_content.py",
        "apps/agent/combat_init.py",
        "apps/agent/encounter_references.py",
    ]
    assert all((root / path).is_file() for path in required), "missing reference corpus surface"
    cases = json.loads((root / required[2]).read_text())
    assert cases["invalid"] and cases["valid"] and cases["consumer_inventory"]
    catalog = json.loads((root / required[1]).read_text())
    assert catalog, "empty catalog corpus"
    ids = {row["id"] for row in catalog}
    templates = []

    def walk(value):
        if isinstance(value, dict):
            if "enemies" in value:
                validate_encounter_references(value, ids)
                templates.append(value)
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    for path in (root / "content").rglob("*.json"):
        walk(json.loads(path.read_text()))
    assert len(templates) == 11, "missing authored encounter corpus"
    needles = (
        "encounter_templates",
        "_start_combat_impl",
        "_make_start_combat_mocks",
        "SAMPLE_ENCOUNTER",
        "catalog_encounters",
    )
    discovered = {
        str(path.relative_to(root))
        for path in (root / "apps/agent/tests").rglob("*.py")
        if any(needle in path.read_text() for needle in needles)
    }
    assert discovered == set(cases["consumer_inventory"]), "unclassified or missing encounter consumer"
    assert_reference_fixture_walk(root / "apps/agent/tests")
    for case in cases["valid"]:
        validate_encounter_references(case, ids)
    for case in cases["invalid"]:
        with pytest.raises(ValueError, match=case["field"]):
            validate_encounter_references(case["encounter"], ids)
