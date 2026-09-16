from __future__ import annotations

import ast
import sys
import tokenize
from pathlib import Path


class DependencyAnalysisError(RuntimeError):
    pass


def imports_from_file(path: Path) -> set[str]:
    try:
        with tokenize.open(path) as source_file:
            source = source_file.read()
        tree = ast.parse(source, filename=str(path))
    except (OSError, UnicodeError, SyntaxError) as exc:
        raise DependencyAnalysisError(f"Cannot analyze {path}: {exc}") from exc

    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name.split(".", 1)[0])
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imports.add(node.module.split(".", 1)[0])
    return imports


def imports_from_project(files: list[Path]) -> set[str]:
    imports: set[str] = set()
    for path in files:
        imports.update(imports_from_file(path))
    return imports


def split_imports(imports: set[str], internal_modules: set[str]) -> tuple[set[str], set[str], set[str]]:
    stdlib = set(sys.stdlib_module_names)
    stdlib_imports = (imports & stdlib) - internal_modules
    internal_imports = imports & internal_modules
    third_party = imports - stdlib_imports - internal_imports
    return stdlib_imports, internal_imports, third_party
