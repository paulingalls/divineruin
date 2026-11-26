"""Discover content filenames and seeded catalog queries in Python source."""

import ast
import re
from functools import cache
from pathlib import Path

from proof_source_cache import source_ast

SQL_READ = re.compile(r"\b(?:FROM|JOIN)\s+([a-z_]+)", re.IGNORECASE)
_TABLES = {}


def seed_tables():
    """`scripts/seed_content.py` TABLE_MAP: content file name -> seeded table."""
    if not _TABLES:
        tree = source_ast("scripts/seed_content.py")
        tables = [
            ast.literal_eval(n.value)
            for n in tree.body
            if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "TABLE_MAP" for t in n.targets)
        ]
        if len(tables) != 1 or not tables[0]:
            raise ValueError("scripts/seed_content.py: missing TABLE_MAP")
        _TABLES.update(tables[0])
    return _TABLES


@cache
def string_literals(path):
    docstrings, literals = set(), set()
    for node in ast.walk(source_ast(path)):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and (
            ast.get_docstring(node, clean=False) is not None
        ):
            docstrings.add(node.body[0].value)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and node not in docstrings:
            literals.add(node.value)
    return frozenset(literals)


def content_literals(path, content):
    literals = string_literals(path)
    return {source for source in content if source in literals or Path(source).name in literals}


def sql_reads(path, content):
    """Exclude INSERT and DELETE statements that set up test-owned fixture rows."""
    files = {table: f"content/{name}" for name, table in seed_tables().items()}
    return {
        files[table]
        for text in string_literals(path)
        if not text.lstrip().upper().startswith(("INSERT", "DELETE"))
        for table in SQL_READ.findall(text)
        if table in files and files[table] in content
    }
