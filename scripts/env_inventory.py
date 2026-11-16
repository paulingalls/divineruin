"""Compare tracked server/agent environment reads with both operator templates."""

import ast
import json
import os
import pathlib
import re
import runpy
import subprocess
import sys

NAME = r"[A-Z][A-Z0-9_]*"
TS_SITE = re.compile(r"Bun\.env|process\.env|requireEnv\s*\(")
TS_READ = re.compile(
    rf"""(?:Bun|process)\.env(?:\.({NAME})(?![\w$])|\[\s*["']({NAME})["']\s*\])|requireEnv\s*\(\s*["']({NAME})["']\s*\)"""
)


def assignment(tree, name):
    values = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        and any(
            isinstance(target, ast.Name) and target.id == name
            for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
        )
    ]
    if len(values) != 1:
        raise ValueError(f"expected one assignment for {name}")
    return values[0]


def assigned(tree, name):
    return ast.literal_eval(assignment(tree, name))


def required_names(node, tree, trees):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, (ast.Tuple, ast.List)):
        return [name for item in node.elts for name in required_names(item, tree, trees)]
    if isinstance(node, ast.Starred):
        return required_names(node.value, tree, trees)
    if isinstance(node, ast.Name):
        return required_names(assignment(tree, node.id), tree, trees)
    if isinstance(node, ast.Call) and not node.keywords:
        if ast.unparse(node.func) == "dict.fromkeys" and len(node.args) == 1:
            return required_names(node.args[0], tree, trees)
        if ast.unparse(node.func) == "gameplay_llm_api_key" and not node.args:
            return list(assigned(trees["apps/agent/gameplay_llm.py"], "PROVIDER_API_KEYS").values())
    raise ValueError(f"unresolved required-name expression: {ast.unparse(node)}")


def python_reads(path, relative, trees):
    tree = trees[relative]
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    # agent's CLI helper receives os.environ as `environ`; its current write is not a read.
    mappings = {"os.environ"} | ({"environ"} if relative == "apps/agent/agent.py" else set())
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and ast.unparse(node) == "os.environ":
            parent = parents[node]
            if not (
                isinstance(parent, ast.Subscript)
                or (isinstance(parent, ast.Attribute) and parent.attr == "get")
                or (
                    isinstance(parent, ast.Call)
                    and ast.unparse(parent.func) == "_livekit_cli_argv"
                    and relative == "apps/agent/agent.py"
                )
            ):
                raise ValueError(f"{relative}:{node.lineno}: unresolved environment mapping use")
        key = None
        if isinstance(node, ast.Call) and ast.unparse(node.func) in {"os.getenv", *(m + ".get" for m in mappings)}:
            if not node.args:
                raise ValueError(f"{relative}:{node.lineno}: environment read without name")
            key = node.args[0]
        elif isinstance(node, ast.Subscript) and ast.unparse(node.value) in mappings and isinstance(node.ctx, ast.Load):
            key = node.slice
        if key is None:
            continue
        location = f"{relative}:{node.lineno}"
        if isinstance(key, ast.Constant) and isinstance(key.value, str):
            names = [key.value]
        else:
            ancestor = node
            while ancestor in parents and not isinstance(ancestor, (ast.ListComp, ast.DictComp)):
                ancestor = parents[ancestor]
            expression = ast.unparse(key)
            if not isinstance(ancestor, (ast.ListComp, ast.DictComp)):
                raise ValueError(f"{location}: unresolved dynamic read {expression}")
            generators = ancestor.generators
            if len(generators) != 1 or ast.unparse(generators[0].target) not in (expression, "(key, var)"):
                raise ValueError(f"{location}: unresolved comprehension {expression}")
            iterable = generators[0].iter
            site = (relative, expression, ast.unparse(iterable))
            if site == ("apps/agent/agent.py", "v", "required"):
                names = required_names(assignment(tree, "required"), tree, trees)
            elif site == ("apps/agent/production_preflight.py", "name", ast.unparse(iterable)) and isinstance(
                iterable, ast.Tuple
            ):
                names = ast.literal_eval(iterable)
            elif site == ("apps/agent/voice_replay.py", "name", "required"):
                names = assigned(tree, "required")
            elif site == ("apps/agent/voices.py", "var", "VOICE_ENV_VARS.items()"):
                names = list(runpy.run_path(str(path))["VOICE_ENV_VARS"].values())
            else:
                raise ValueError(f"{location}: unresolved dynamic read {expression} over {ast.unparse(iterable)}")
        if not names or any(not re.fullmatch(NAME, name) for name in names):
            raise ValueError(f"{location}: invalid/empty environment names")
        for name in names:
            yield name, location


def inventory(root, *, snapshot=False):
    for folder in ("apps/server/src", "apps/agent"):
        if not (root / folder).is_dir():
            raise ValueError(f"missing source root: {folder}")
    if snapshot:
        # Proof materializes the tracked tree without Git metadata; inspect that supplied snapshot.
        paths = []
        for folder in ("apps/server/src", "apps/agent"):
            for base, dirs, files in os.walk(root / folder):
                dirs[:] = sorted(d for d in dirs if d not in {".venv", "node_modules", "tests", "test-fixtures"})
                paths.extend(str((pathlib.Path(base) / name).relative_to(root)) for name in sorted(files))
    else:
        paths = subprocess.check_output(["git", "ls-files", "--cached"], cwd=root, text=True).splitlines()
    paths = sorted(set(paths))
    ts = [
        p
        for p in paths
        if p.startswith("apps/server/src/")
        and p.endswith(".ts")
        and not p.endswith(".test.ts")
        and pathlib.Path(p).name not in ("test-env.ts", "activities-test-mock.ts")
        and not {"test-fixtures", ".venv", "node_modules"} & set(pathlib.Path(p).parts)
    ]
    py = [
        p
        for p in paths
        if p.startswith("apps/agent/")
        and p.endswith(".py")
        and not {"tests", ".venv", "node_modules"} & set(pathlib.Path(p).parts)
    ]
    if not ts or not py:
        raise ValueError("no source files in one or both languages")
    result = {}
    counts = []
    for group in (ts, py):
        found = set()
        trees = {p: ast.parse((root / p).read_text(), filename=p) for p in py} if group is py else {}
        for relative in group:
            path = root / relative
            if group is py:
                reads = python_reads(path, relative, trees)
            else:
                source = path.read_text()
                reads = []
                matches = {m.start(): m for m in TS_READ.finditer(source)}
                for site in TS_SITE.finditer(source):
                    location = f"{relative}:{source.count(chr(10), 0, site.start()) + 1}"
                    match = matches.get(site.start())
                    if match:
                        reads.append((next(name for name in match.groups() if name), location))
                    elif relative == "apps/server/src/env.ts" and (
                        source[site.start() :].startswith("Bun.env[name]")
                        or source[site.start() :].startswith("requireEnv(name: string)")
                    ):
                        continue
                    else:
                        raise ValueError(f"{location}: unresolved TypeScript environment read")
            for name, location in reads:
                found.add(name)
                result.setdefault(name, []).append(location)
        counts.append(len(found))
    if not all(counts):
        raise ValueError("no environment names in one or both languages")
    return result


def compare(root, *, snapshot=False):
    names = inventory(root, snapshot=snapshot)
    errors = []
    for template in (".env.example", "deploy/env.production.example"):
        declared = set(re.findall(rf"^\s*(?:#\s*)?({NAME})=", (root / template).read_text(), re.M))
        if not declared:
            raise ValueError(f"{template}: no environment declarations")
        errors.extend(
            f"{template}: missing {name} ({', '.join(names[name])})" for name in sorted(names.keys() - declared)
        )
    if errors:
        raise ValueError("\n".join(errors))
    return names


if __name__ == "__main__":
    try:
        print(json.dumps(compare(pathlib.Path(sys.argv[1]).resolve(), snapshot="--snapshot" in sys.argv[2:])))
    except (ValueError, OSError, SyntaxError) as error:
        sys.exit(str(error))
