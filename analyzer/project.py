from __future__ import annotations

from pathlib import Path
from collections.abc import Sequence
import ast
import re

from .dependencies import imports_from_project, split_imports
from .models import ProjectAnalysis
from .package_resolver import resolve_packages

ENTRY_NAMES = ("main.py", "app.py", "run.py", "__main__.py")
IGNORED_DIRS = {".git", ".venv", "venv", "build", "dist", "__pycache__", ".pytest_cache", "workspace", "web-data"}


def _python_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*.py"):
        if not any(part in IGNORED_DIRS or part.startswith('.pytest-tmp') for part in path.relative_to(root).parts[:-1]):
            if path.is_symlink() or not path.resolve().is_relative_to(root):
                raise ValueError('Project contains an external link')
            files.append(path)
    return sorted(files)


def _internal_modules(root: Path, files: list[Path]) -> set[str]:
    modules: set[str] = set()
    for path in files:
        rel = path.relative_to(root)
        if len(rel.parts) == 1:
            if path.stem != "__init__":
                modules.add(path.stem)
        else:
            modules.add(rel.parts[0])
    return modules


def _looks_like_runnable_entry(path: Path) -> bool:
    """Return True when a Python file contains an executable application entry.

    This deliberately looks beyond conventional filenames. Real projects often
    keep launchers under scripts/ (for example run_gui.py) or expose a main()
    function from a package module.
    """
    try:
        source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=str(path))
    except (OSError, UnicodeError, SyntaxError):
        return False

    has_main_guard = False
    has_main_function = False
    has_gui_bootstrap = False
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "main":
            has_main_function = True
        if isinstance(node, ast.If):
            try:
                test = ast.unparse(node.test)
            except Exception:
                test = ""
            if "__name__" in test and "__main__" in test:
                has_main_guard = True
        if isinstance(node, ast.Call):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else (func.attr if isinstance(func, ast.Attribute) else "")
            if name in {"QApplication", "Tk", "mainloop"}:
                has_gui_bootstrap = True

    return has_main_guard or (has_main_function and has_gui_bootstrap)


def _entry_candidates(root: Path, files: list[Path]) -> list[Path]:
    conventional: list[Path] = []
    discovered: list[Path] = []
    by_name = {name: [] for name in ENTRY_NAMES}
    for path in files:
        rel_parts = path.relative_to(root).parts
        lowered = {part.lower() for part in rel_parts}
        if {"tests", "test"} & lowered or path.name.startswith("test_") or path.name.endswith("_test.py"):
            continue
        if path.name in by_name:
            by_name[path.name].append(path)
        if _looks_like_runnable_entry(path) and path.name not in ENTRY_NAMES:
            discovered.append(path)

    for name in ENTRY_NAMES:
        conventional.extend(sorted(by_name[name], key=lambda p: (len(p.relative_to(root).parts), str(p))))

    # Conventional names remain first for backward compatibility, while
    # executable launchers elsewhere in the repository are no longer hidden.
    seen: set[Path] = set()
    result: list[Path] = []
    for path in conventional + sorted(discovered, key=lambda p: (len(p.relative_to(root).parts), str(p))):
        if path not in seen:
            result.append(path)
            seen.add(path)
    return result



def _entry_app_type(path: Path) -> str:
    name = path.stem.lower()
    if any(token in name for token in ("gui", "ui", "app")):
        return "gui"
    try:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    except (OSError, UnicodeError, SyntaxError):
        return "cli"

    gui_modules = {"PySide6", "PyQt6", "PyQt5", "tkinter", "wx", "kivy"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name.split(".", 1)[0] in gui_modules for alias in node.names):
                return "gui"
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.split(".", 1)[0] in gui_modules:
                return "gui"
        elif isinstance(node, ast.Call):
            func = node.func
            call_name = (
                func.id if isinstance(func, ast.Name)
                else func.attr if isinstance(func, ast.Attribute)
                else ""
            )
            if call_name in {"QApplication", "Tk", "mainloop", "MainLoop"}:
                return "gui"
    return "cli"


def _entry_detail(root: Path, path: Path) -> dict[str, str | bool]:
    rel = path.relative_to(root).as_posix()
    name = path.stem.lower()
    parts = {part.lower() for part in path.relative_to(root).parts}
    auxiliary_tokens = (
        "smoke", "probe", "preflight", "diagnostic", "debug", "benchmark",
        "check", "verify", "validate", "audit", "qualify",
    )
    utility_dirs = {"tools", "tool", "packaging", "examples", "example"}
    auxiliary_names = {"eval", "evaluate", "train", "training", "manage"}
    auxiliary_prefixes = (
        "build_", "prepare_", "generate_", "clean_", "migrate_", "seed_",
    )
    auxiliary = (
        any(token in name for token in auxiliary_tokens)
        or name in auxiliary_names
        or name.startswith(auxiliary_prefixes)
        or bool(parts & utility_dirs)
    )
    internal = "src" in parts and not auxiliary
    if auxiliary:
        kind, confidence, recommended = "auxiliary", "low", False
    elif internal:
        kind, confidence, recommended = "internal", "medium", False
    else:
        kind, confidence, recommended = "application", "high", True
    app_type = _entry_app_type(path)
    return {
        "path": rel,
        "kind": kind,
        "confidence": confidence,
        "recommended": recommended,
        "app_type": app_type,
    }


def _requirements(path: Path) -> list[str]:
    packages: list[str] = []
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith(("-r", "--", "git+", "http://", "https://")):
            continue
        packages.append(line)
    return packages


def _single_nested_metadata(root: Path, filename: str) -> Path | None:
    candidates: list[Path] = []
    for path in root.rglob(filename):
        relative = path.relative_to(root)
        lowered = {part.lower() for part in relative.parts[:-1]}
        if (
            any(part in IGNORED_DIRS or part.startswith(".pytest-tmp") for part in relative.parts[:-1])
            or {"tests", "test"} & lowered
        ):
            continue
        if path.is_file() and not path.is_symlink():
            candidates.append(path)
    return candidates[0] if len(candidates) == 1 else None


def _pyproject_dependencies(path: Path, imported_packages: Sequence[str] = ()) -> list[str] | None:
    try:
        import tomllib
        data = tomllib.loads(path.read_text(encoding="utf-8-sig"))
        project = data.get("project", {})
        deps = project.get("dependencies")
        if not isinstance(deps, list) or not all(isinstance(dep, str) for dep in deps):
            return None
        def name(requirement):
            match = re.match(r'[A-Za-z0-9][A-Za-z0-9_.-]*', requirement)
            return re.sub(r'[-_.]+', '-', match[0]).lower() if match else ''
        imported = {name(package) for package in imported_packages}
        declared = {name(dep) for dep in deps}
        optional = project.get('optional-dependencies', {})
        if isinstance(optional, dict):
            for requirements in optional.values():
                if not isinstance(requirements, list):
                    continue
                for dep in requirements:
                    if isinstance(dep, str) and name(dep) in imported and name(dep) not in declared:
                        deps.append(dep)
                        declared.add(name(dep))
        return deps
    except (OSError, ValueError):
        return None


def analyze_project(source: Path | str) -> ProjectAnalysis:
    source = Path(source).resolve()
    if source.is_file():
        if source.suffix.lower() != ".py":
            raise ValueError("Source file must be a .py file")
        root = source.parent
        files = [source]
        entry = source
        candidates = [source]
        internal = {source.stem}
    elif source.is_dir():
        root = source
        files = _python_files(root)
        if not files:
            raise ValueError("Project folder contains no Python files")
        internal = _internal_modules(root, files)
        candidates = _entry_candidates(root, files)
        entry = candidates[0] if len(candidates) == 1 else None
    else:
        raise FileNotFoundError(source)

    imports = imports_from_project(files)
    stdlib_imports, internal_imports, third_party = split_imports(imports, internal)
    warnings: list[str] = []

    root_pyproject = root / "pyproject.toml"
    root_requirements = root / "requirements.txt"
    pyproject = (
        root_pyproject
        if root_pyproject.exists()
        else _single_nested_metadata(root, "pyproject.toml")
    )
    requirements = (
        root_requirements
        if root_requirements.exists()
        else _single_nested_metadata(root, "requirements.txt")
    )
    runtime_files = [path for path in files
                     if not {'tests', 'test'} & set(path.relative_to(root).parts[:-1])
                     and not path.name.startswith('test_') and not path.name.endswith('_test.py')
                     and path.name != 'conftest.py']
    runtime_imports = imports_from_project(runtime_files) & third_party
    declared = _pyproject_dependencies(pyproject, resolve_packages(runtime_imports)) if pyproject else None
    if declared is not None:
        packages = declared
        dependency_source = pyproject.relative_to(root).as_posix()
    elif requirements:
        packages = _requirements(requirements)
        dependency_source = requirements.relative_to(root).as_posix()
    else:
        packages = resolve_packages(third_party)
        dependency_source = "ast"

    if pyproject and declared is None:
        warnings.append(
            f"{pyproject.relative_to(root).as_posix()} has no readable "
            f"[project].dependencies; used {dependency_source} fallback"
        )

    if source.is_dir() and not candidates:
        warnings.append("No conventional entry point found; select an entry file manually")
    elif source.is_dir() and len(candidates) > 1:
        warnings.append("Multiple entry point candidates found; select one manually")

    entry_details = [_entry_detail(root, path) for path in candidates]

    return ProjectAnalysis(
        source=source,
        project_root=root,
        python_files=files,
        entry_point=entry,
        entry_candidates=candidates,
        entry_details=entry_details,
        imports=imports,
        stdlib_imports=stdlib_imports,
        internal_imports=internal_imports,
        third_party_imports=third_party,
        packages=packages,
        dependency_source=dependency_source,
        warnings=warnings,
    )
