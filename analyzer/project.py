from __future__ import annotations

from pathlib import Path
from collections.abc import Sequence
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


def _entry_candidates(root: Path, files: list[Path]) -> list[Path]:
    by_name = {name: [] for name in ENTRY_NAMES}
    for path in files:
        if path.name in by_name:
            by_name[path.name].append(path)
    candidates: list[Path] = []
    for name in ENTRY_NAMES:
        candidates.extend(sorted(by_name[name], key=lambda p: (len(p.relative_to(root).parts), str(p))))
    return candidates


def _requirements(path: Path) -> list[str]:
    packages: list[str] = []
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith(("-r", "--", "git+", "http://", "https://")):
            continue
        packages.append(line)
    return packages


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

    pyproject = root / "pyproject.toml"
    requirements = root / "requirements.txt"
    runtime_files = [path for path in files
                     if not {'tests', 'test'} & set(path.relative_to(root).parts[:-1])
                     and not path.name.startswith('test_') and not path.name.endswith('_test.py')
                     and path.name != 'conftest.py']
    runtime_imports = imports_from_project(runtime_files) & third_party
    declared = _pyproject_dependencies(pyproject, resolve_packages(runtime_imports)) if pyproject.exists() else None
    if declared is not None:
        packages = declared
        dependency_source = "pyproject.toml"
    elif requirements.exists():
        packages = _requirements(requirements)
        dependency_source = "requirements.txt"
    else:
        packages = resolve_packages(third_party)
        dependency_source = "ast"

    if pyproject.exists() and declared is None:
        warnings.append(f"pyproject.toml has no readable [project].dependencies; used {dependency_source} fallback")

    if source.is_dir() and not candidates:
        warnings.append("No conventional entry point found; select an entry file manually")
    elif source.is_dir() and len(candidates) > 1:
        warnings.append("Multiple entry point candidates found; select one manually")

    return ProjectAnalysis(
        source=source,
        project_root=root,
        python_files=files,
        entry_point=entry,
        entry_candidates=candidates,
        imports=imports,
        stdlib_imports=stdlib_imports,
        internal_imports=internal_imports,
        third_party_imports=third_party,
        packages=packages,
        dependency_source=dependency_source,
        warnings=warnings,
    )
