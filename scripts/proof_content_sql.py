"""Which seeded content a test entry reads with its own SQL."""

import ast
import re
from pathlib import Path

SQL_READ = re.compile(r"\b(?:FROM|JOIN)\s+([a-z_]+)", re.IGNORECASE)
_TABLES = {}


def seed_tables():
    """`scripts/seed_content.py` TABLE_MAP: content file name -> seeded table."""
    if not _TABLES:
        tree = ast.parse(Path("scripts/seed_content.py").read_text())
        tables = [
            ast.literal_eval(n.value)
            for n in tree.body
            if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "TABLE_MAP" for t in n.targets)
        ]
        if len(tables) != 1 or not tables[0]:
            raise ValueError("scripts/seed_content.py: missing TABLE_MAP")
        _TABLES.update(tables[0])
    return _TABLES


def sql_reads(path, content):
    """Content whose seeded table the file SELECTs or JOINs.

    INSERT and DELETE statements are fixture rows the test writes itself, not catalog reads.
    """
    files = {table: f"content/{name}" for name, table in seed_tables().items()}
    literals = (
        n.value
        for n in ast.walk(ast.parse(Path(path).read_text()))
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    )
    return {
        files[table]
        for text in literals
        if not text.lstrip().upper().startswith(("INSERT", "DELETE"))
        for table in SQL_READ.findall(text)
        if table in files and files[table] in content
    }
