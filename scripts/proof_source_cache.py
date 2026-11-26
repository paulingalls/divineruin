"""Read and parse each source once per declaration generation process."""

import ast
from functools import cache
from pathlib import Path


@cache
def source_text(path: str) -> str:
    return Path(path).read_text()


@cache
def source_ast(path: str) -> ast.Module:
    return ast.parse(source_text(path), filename=path)
